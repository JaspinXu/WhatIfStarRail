from __future__ import annotations

import hashlib
import json

from astral_agents.domain.models import (
    CanonicalEvent,
    DiscoveryRecord,
    RelationshipState,
    RunStatus,
    ScenarioBundle,
    StateDiff,
    WorldState,
)


class InvalidStateChange(ValueError):
    """Raised when an event attempts an illegal world-state transition."""


def create_initial_state(
    bundle: ScenarioBundle,
    run_id: str,
    seed: int,
    story_background: str = "",
) -> WorldState:
    character_ids = [character.id for character in bundle.characters]
    relationships: dict[str, dict[str, RelationshipState]] = {}
    for source in character_ids:
        relationships[source] = {}
        for target in character_ids:
            if source == target:
                continue
            relationships[source][target] = RelationshipState(
                trust=0.48,
                suspicion=0.02,
                affinity=0.38,
                obligation=0.25,
                influence=0.20,
            )
    return WorldState(
        run_id=run_id,
        scenario_id=bundle.scenario.id,
        seed=seed,
        story_background=story_background,
        phase=bundle.scenario.start_phase,
        status=RunStatus.READY,
        locations={
            character.id: character.starting_location for character in bundle.characters
        },
        resources={
            resource.id: resource.initial for resource in bundle.scenario.resources
        },
        resource_limits={
            resource.id: (resource.minimum, resource.maximum)
            for resource in bundle.scenario.resources
        },
        relationships=relationships,
        active_conflicts=list(bundle.scenario.active_conflicts),
        open_threads=list(bundle.scenario.open_threads),
        public_fact_ids=[fact.id for fact in bundle.canon_facts],
        constraints=list(bundle.scenario.constraints),
    )


def apply_event(
    state: WorldState,
    event: CanonicalEvent,
    bundle: ScenarioBundle,
) -> tuple[WorldState, list[StateDiff]]:
    next_state = state.model_copy(deep=True)
    diffs: list[StateDiff] = []
    characters = bundle.character_map
    locations = bundle.scenario.location_map
    resources = bundle.scenario.resource_map
    clues = bundle.scenario.clue_map

    for change in event.changes:
        if change.kind == "set_location":
            if change.subject_id not in characters:
                raise InvalidStateChange(f"unknown character {change.subject_id!r}")
            destination = str(change.value)
            if destination not in locations:
                raise InvalidStateChange(f"unknown destination {destination!r}")
            before = next_state.locations[change.subject_id]
            if before != destination and destination not in bundle.scenario.adjacency.get(
                before, []
            ):
                raise InvalidStateChange(f"illegal move {before!r} -> {destination!r}")
            next_state.locations[change.subject_id] = destination
            diffs.append(
                StateDiff(
                    path=f"locations.{change.subject_id}",
                    before=before,
                    after=destination,
                    label=f"{characters[change.subject_id].display_name}的位置",
                )
            )
        elif change.kind == "adjust_resource":
            resource_id = change.subject_id
            if resource_id not in resources:
                raise InvalidStateChange(f"unknown resource {resource_id!r}")
            before = next_state.resources[resource_id]
            after = round(before + float(change.value or 0), 2)
            minimum, maximum = next_state.resource_limits[resource_id]
            if not minimum <= after <= maximum:
                raise InvalidStateChange(
                    f"resource {resource_id!r} would leave [{minimum}, {maximum}]"
                )
            next_state.resources[resource_id] = after
            diffs.append(
                StateDiff(
                    path=f"resources.{resource_id}",
                    before=before,
                    after=after,
                    label=resources[resource_id].display_name,
                )
            )
        elif change.kind == "set_flag":
            before = next_state.flags.get(change.subject_id)
            next_state.flags[change.subject_id] = change.value
            diffs.append(
                StateDiff(
                    path=f"flags.{change.subject_id}",
                    before=before,
                    after=change.value,
                    label=f"场景标记 · {change.subject_id}",
                )
            )
        elif change.kind == "discover_clue":
            clue_id = change.subject_id
            actor_id = change.target_id
            if clue_id not in clues or actor_id not in characters:
                raise InvalidStateChange(
                    f"illegal discovery clue={clue_id!r}, actor={actor_id!r}"
                )
            if clue_id in next_state.discovered_clues:
                raise InvalidStateChange(f"clue {clue_id!r} was already discovered")
            next_state.discovered_clues[clue_id] = DiscoveryRecord(
                clue_id=clue_id,
                discovered_by=actor_id,
                event_id=event.id,
                round_no=event.round_no,
            )
            diffs.append(
                StateDiff(
                    path=f"discovered_clues.{clue_id}",
                    before=None,
                    after=actor_id,
                    label=f"发现线索 · {clues[clue_id].display_name}",
                )
            )
        elif change.kind == "share_clue":
            clue_id = change.subject_id
            if clue_id not in next_state.discovered_clues:
                raise InvalidStateChange(f"cannot share undiscovered clue {clue_id!r}")
            before = clue_id in next_state.shared_clue_ids
            if not before:
                next_state.shared_clue_ids.append(clue_id)
                next_state.discovered_clues[clue_id].shared = True
            diffs.append(
                StateDiff(
                    path=f"shared_clue_ids.{clue_id}",
                    before=before,
                    after=True,
                    label=f"共享线索 · {clues[clue_id].display_name}",
                )
            )
        elif change.kind == "adjust_relationship":
            source = change.subject_id
            target = change.target_id
            dimension = change.dimension
            if (
                source not in next_state.relationships
                or target not in next_state.relationships[source]
                or dimension not in RelationshipState.model_fields
            ):
                raise InvalidStateChange(
                    f"invalid relationship change {source!r}->{target!r}.{dimension!r}"
                )
            relation = next_state.relationships[source][target]
            before = float(getattr(relation, dimension))
            after = max(-1.0, min(1.0, round(before + float(change.value or 0), 3)))
            setattr(relation, dimension, after)
            diffs.append(
                StateDiff(
                    path=f"relationships.{source}.{target}.{dimension}",
                    before=before,
                    after=after,
                    label=f"关系变化 · {source}→{target} {dimension}",
                )
            )
        elif change.kind == "close_thread":
            thread_id = change.subject_id
            before = thread_id in next_state.open_threads
            if before:
                next_state.open_threads.remove(thread_id)
            if thread_id not in next_state.resolved_threads:
                next_state.resolved_threads.append(thread_id)
            diffs.append(
                StateDiff(
                    path=f"open_threads.{thread_id}",
                    before=before,
                    after=False,
                    label=f"关闭悬念 · {thread_id}",
                )
            )
        elif change.kind == "set_phase":
            before = next_state.phase
            next_state.phase = str(change.value)
            diffs.append(
                StateDiff(
                    path="phase",
                    before=before,
                    after=next_state.phase,
                    label="任务阶段",
                )
            )
        elif change.kind == "set_status":
            before = next_state.status
            next_state.status = RunStatus(str(change.value))
            diffs.append(
                StateDiff(
                    path="status",
                    before=before.value,
                    after=next_state.status.value,
                    label="运行状态",
                )
            )
        else:
            raise InvalidStateChange(f"unsupported state change kind: {change.kind}")

    next_state.round_no = max(next_state.round_no, event.round_no)
    event_payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    next_state.timeline_hash = hashlib.sha256(
        f"{state.timeline_hash}|{event_payload}".encode()
    ).hexdigest()[:16]
    return WorldState.model_validate(next_state.model_dump()), diffs

