from __future__ import annotations

import hashlib
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from astral_agents.domain.models import (
    CanonicalEvent,
    NarrativeEpisode,
    RoundRecord,
    RunConfig,
    RunManifest,
    RunStatus,
    ScenarioBundle,
    Severity,
    StateChange,
    StateDiff,
    ValidationFinding,
    WorldState,
)
from astral_agents.memory.service import MemoryService
from astral_agents.narrative.writer import TemplateNarrativeWriter
from astral_agents.simulation.adjudicator import adjudicate_actions
from astral_agents.simulation.checks import (
    assert_observation_isolation,
    check_information_boundaries,
    check_world_and_events,
)
from astral_agents.simulation.observation import build_observation
from astral_agents.simulation.policies import provider_for
from astral_agents.simulation.reducer import apply_event, create_initial_state
from astral_agents.storage.repository import SQLiteRepository


@dataclass(frozen=True)
class ReplayResult:
    run_id: str
    rounds_replayed: int
    expected_digest: str
    actual_digest: str
    expected_timeline_hash: str
    actual_timeline_hash: str
    event_sources_consistent: bool
    matched: bool


class SimulationEngine:
    def __init__(
        self,
        bundle: ScenarioBundle,
        repository: SQLiteRepository,
    ) -> None:
        self.bundle = bundle
        self.repository = repository
        self.memory = MemoryService(repository)
        self.narrative = TemplateNarrativeWriter()

    def create_run(self, config: RunConfig) -> str:
        suffix = uuid.uuid4().hex[:8]
        run_id = f"{self.bundle.scenario.id}-{config.seed}-{suffix}"
        state = create_initial_state(self.bundle, run_id, config.seed)
        opening_events = self._opening_events()
        for event in opening_events:
            state, _ = apply_event(state, event, self.bundle)
        state.status = RunStatus.READY
        memories, beliefs = self.memory.form_memories(
            run_id, opening_events, self.bundle
        )
        memories.extend(
            self.memory.initial_private_memories(opening_events, self.bundle)
        )
        manifest = RunManifest(
            run_id=run_id,
            scenario_id=self.bundle.scenario.id,
            scenario_version=self.bundle.scenario.version,
            config_digest=self.bundle.config_digest,
            seed=config.seed,
            policy=config.policy,
            model=config.model,
            memory_strategy=config.memory_strategy,
        )
        self.repository.create_run(
            manifest, state, opening_events, memories, beliefs
        )
        return run_id

    def step(self, run_id: str) -> RoundRecord:
        started = time.perf_counter()
        manifest = self.repository.get_manifest(run_id)
        state_before = self.repository.get_state(run_id)
        if state_before.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.BLOCKED,
        }:
            raise RuntimeError(
                f"run {run_id} is terminal ({state_before.status.value})"
            )
        round_no = state_before.round_no + 1
        max_rounds = self.bundle.scenario.max_rounds
        if round_no > max_rounds:
            raise RuntimeError(f"run {run_id} already reached max rounds")

        all_events = self.repository.get_events(run_id)
        observations = {
            character.id: build_observation(
                character.id, state_before, all_events, self.bundle
            )
            for character in self.bundle.characters
        }
        for observation in observations.values():
            assert_observation_isolation(observation, self.bundle)

        provider = provider_for(manifest.policy, manifest.model)
        actions = []
        retrievals = {}
        model_calls = []
        for character in sorted(self.bundle.characters, key=lambda item: item.id):
            retrieved, hits = self.memory.retrieve(
                run_id,
                character,
                observations[character.id],
                manifest.memory_strategy,
            )
            retrievals[character.id] = hits
            rng = random.Random(
                _derived_seed(manifest.seed, round_no, character.id)
            )
            outcome = provider.decide(
                character,
                observations[character.id],
                retrieved,
                self.bundle,
                rng,
            )
            actions.append(outcome.action)
            if outcome.trace:
                model_calls.append(outcome.trace)

        findings = check_information_boundaries(
            actions, observations, self.bundle, round_no
        )
        adjudication = adjudicate_actions(
            actions, observations, state_before, self.bundle, round_no
        )
        actions = adjudication.actions
        events = adjudication.events
        findings.extend(adjudication.findings)

        state_after = state_before.model_copy(deep=True)
        diffs: list[StateDiff] = []
        try:
            for event in events:
                state_after, event_diffs = apply_event(
                    state_after, event, self.bundle
                )
                diffs.extend(event_diffs)
            resolution_event = self._resolution_event(state_after, round_no, len(events) + 1)
            if resolution_event:
                state_after, event_diffs = apply_event(
                    state_after, resolution_event, self.bundle
                )
                events.append(resolution_event)
                diffs.extend(event_diffs)
        except Exception as exc:
            findings.append(
                ValidationFinding(
                    code="REDUCER_REJECTED",
                    severity=Severity.CRITICAL,
                    message=str(exc),
                    round_no=round_no,
                    blocked=True,
                )
            )

        findings.extend(
            check_world_and_events(
                state_before, state_after, events, self.bundle, round_no
            )
        )
        if any(finding.blocked for finding in findings):
            block_event = CanonicalEvent(
                id=f"R{round_no:03d}-E99-audit-block",
                round_no=round_no,
                event_type="round_blocked",
                participants=[],
                observers=list(self.bundle.character_map),
                public_summary="连续性检查阻止了本轮状态变更；候选事件未被应用。",
                changes=[
                    StateChange(
                        kind="set_status",
                        subject_id="run",
                        value=RunStatus.BLOCKED.value,
                    )
                ],
                tags=["public", "audit", "blocked"],
            )
            state_after, diffs = apply_event(
                state_before, block_event, self.bundle
            )
            events = [block_event]

        new_memories, new_beliefs = self.memory.form_memories(
            run_id, events, self.bundle
        )
        episode = self._maybe_episode(run_id, round_no, state_after, events)
        duration_ms = int((time.perf_counter() - started) * 1000)
        record = RoundRecord(
            run_id=run_id,
            round_no=round_no,
            actions=actions,
            events=events,
            findings=findings,
            state_before=state_before,
            state_after=state_after,
            diffs=diffs,
            retrievals=retrievals,
            model_calls=model_calls,
            episode_id=episode.id if episode else None,
            duration_ms=duration_ms,
        )
        self.repository.commit_round(
            record, new_memories, new_beliefs, episode
        )
        return record

    def run(self, run_id: str, rounds: int | None = None) -> list[RoundRecord]:
        records: list[RoundRecord] = []
        remaining = rounds or self.bundle.scenario.max_rounds
        for _ in range(remaining):
            state = self.repository.get_state(run_id)
            if state.status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.BLOCKED,
            }:
                break
            records.append(self.step(run_id))
        return records

    def replay(self, run_id: str) -> ReplayResult:
        records = self.repository.get_rounds(run_id)
        state = self.repository.get_state_at_round(run_id, 0)
        canonical_events = self.repository.get_events(run_id, start_round=1)
        for event in canonical_events:
            state, _ = apply_event(state, event, self.bundle)
        record_events = [event for record in records for event in record.events]
        event_sources_consistent = [
            event.model_dump(mode="json") for event in canonical_events
        ] == [event.model_dump(mode="json") for event in record_events]
        expected_state = self.repository.get_state(run_id)
        expected = expected_state.state_digest()
        actual = state.state_digest()
        matched = (
            expected == actual
            and expected_state.timeline_hash == state.timeline_hash
            and event_sources_consistent
        )
        return ReplayResult(
            run_id=run_id,
            rounds_replayed=len(records),
            expected_digest=expected,
            actual_digest=actual,
            expected_timeline_hash=expected_state.timeline_hash,
            actual_timeline_hash=state.timeline_hash,
            event_sources_consistent=event_sources_consistent,
            matched=matched,
        )

    def _opening_events(self) -> list[CanonicalEvent]:
        return [
            CanonicalEvent(
                id=f"R000-E{index:02d}-opening",
                round_no=0,
                event_type=event.event_type,
                participants=event.participants,
                observers=event.observers,
                public_summary=event.public_summary,
                private_payloads=event.private_payloads,
                tags=event.tags,
            )
            for index, event in enumerate(self.bundle.opening_events, start=1)
        ]

    def _resolution_event(
        self,
        state: WorldState,
        round_no: int,
        event_index: int,
    ) -> CanonicalEvent | None:
        rules = self.bundle.scenario.resolution
        failure_value = state.resources[rules.failure_resource]
        if failure_value <= rules.failure_threshold:
            return CanonicalEvent(
                id=f"R{round_no:03d}-E{event_index:02d}-resolution",
                round_no=round_no,
                event_type="resolution",
                participants=list(self.bundle.character_map),
                observers=list(self.bundle.character_map),
                public_summary="生命维持跌破安全线，团队停止调查并紧急撤离运输舰。",
                changes=[
                    StateChange(
                        kind="set_status",
                        subject_id="run",
                        value=RunStatus.FAILED.value,
                    ),
                    StateChange(
                        kind="set_phase",
                        subject_id="phase",
                        value="紧急撤离",
                    ),
                ],
                tags=["public", "resolution", "failure"],
            )

        resources_ready = all(
            state.resources[resource_id]
            / self.bundle.scenario.resource_map[resource_id].maximum
            >= rules.minimum_resource_ratio
            for resource_id in rules.repaired_resources
        )
        success_ready = (
            round_no >= rules.earliest_success_round
            and state.resources["evidence"] >= rules.evidence_required
            and resources_ready
            and not state.open_threads
        )
        if success_ready:
            return CanonicalEvent(
                id=f"R{round_no:03d}-E{event_index:02d}-resolution",
                round_no=round_no,
                event_type="resolution",
                participants=list(self.bundle.character_map),
                observers=list(self.bundle.character_map),
                public_summary=(
                    "三组证据完成交叉签名，旧导航缓存被安全切离；"
                    "运输舰重新出现在稳定航线上。"
                ),
                changes=[
                    StateChange(
                        kind="set_flag",
                        subject_id="route_calibrated",
                        value=True,
                    ),
                    StateChange(
                        kind="set_flag",
                        subject_id="echo_contained",
                        value=True,
                    ),
                    StateChange(
                        kind="set_status",
                        subject_id="run",
                        value=RunStatus.SUCCEEDED.value,
                    ),
                    StateChange(
                        kind="set_phase",
                        subject_id="phase",
                        value="归航",
                    ),
                ],
                tags=["public", "resolution", "success"],
            )

        if round_no >= self.bundle.scenario.max_rounds:
            return CanonicalEvent(
                id=f"R{round_no:03d}-E{event_index:02d}-resolution",
                round_no=round_no,
                event_type="resolution",
                participants=list(self.bundle.character_map),
                observers=list(self.bundle.character_map),
                public_summary="调查窗口结束，团队带着未完成的证据链撤离。",
                changes=[
                    StateChange(
                        kind="set_status",
                        subject_id="run",
                        value=RunStatus.FAILED.value,
                    ),
                    StateChange(
                        kind="set_phase",
                        subject_id="phase",
                        value="撤离",
                    ),
                ],
                tags=["public", "resolution", "failure"],
            )
        if state.status == RunStatus.READY:
            return CanonicalEvent(
                id=f"R{round_no:03d}-E{event_index:02d}-start",
                round_no=round_no,
                event_type="phase_changed",
                participants=[],
                observers=list(self.bundle.character_map),
                public_summary="调查正式进入同步行动阶段。",
                changes=[
                    StateChange(
                        kind="set_status",
                        subject_id="run",
                        value=RunStatus.RUNNING.value,
                    ),
                    StateChange(
                        kind="set_phase",
                        subject_id="phase",
                        value="调查",
                    ),
                ],
                tags=["public", "phase"],
            )
        return None

    def _maybe_episode(
        self,
        run_id: str,
        round_no: int,
        state: WorldState,
        current_events: list[CanonicalEvent],
    ) -> NarrativeEpisode | None:
        terminal = state.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.BLOCKED,
        }
        interval = self.bundle.scenario.episode_interval
        if round_no % interval != 0 and not terminal:
            return None
        episodes = self.repository.get_episodes(run_id)
        start_round = episodes[-1].end_round + 1 if episodes else 1
        if start_round > round_no:
            return None
        prior_events = self.repository.get_events(
            run_id, start_round=start_round, end_round=round_no
        )
        by_id = {event.id: event for event in [*prior_events, *current_events]}
        return self.narrative.write(
            run_id,
            start_round,
            round_no,
            sorted(by_id.values(), key=lambda item: (item.round_no, item.id)),
            self.bundle,
        )


def _derived_seed(seed: int, round_no: int, actor_id: str) -> int:
    payload = f"{seed}:{round_no}:{actor_id}".encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:16], 16)
