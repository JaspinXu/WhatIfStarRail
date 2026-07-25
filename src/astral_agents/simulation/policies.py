from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from astral_agents.domain.models import (
    ActionIntent,
    ActionType,
    CharacterProfile,
    Memory,
    ModelCallTrace,
    ObservationPacket,
    ScenarioBundle,
)


@dataclass(frozen=True)
class DecisionOutcome:
    action: ActionIntent
    trace: ModelCallTrace | None = None


class DecisionProvider(Protocol):
    def decide(
        self,
        profile: CharacterProfile,
        observation: ObservationPacket,
        memories: list[Memory],
        bundle: ScenarioBundle,
        rng: random.Random,
    ) -> DecisionOutcome: ...


class HeuristicDecisionProvider:
    """An offline policy that consumes only an actor's filtered context."""

    def decide(
        self,
        profile: CharacterProfile,
        observation: ObservationPacket,
        memories: list[Memory],
        bundle: ScenarioBundle,
        rng: random.Random,
    ) -> DecisionOutcome:
        round_no = observation.round_no
        action_id = f"A-{round_no:03d}-{profile.id}"
        evidence_ids = _memory_evidence(memories, observation.accessible_event_ids)
        known = set(observation.known_clue_ids)
        shared = set(observation.shared_clue_ids)

        discoverable_here = [
            clue
            for clue in bundle.scenario.clues
            if clue.location_id == observation.current_location
            and clue.earliest_round <= round_no
            and (not clue.discoverers or profile.id in clue.discoverers)
            and clue.id not in known
        ]
        if discoverable_here:
            clue = sorted(discoverable_here, key=lambda item: item.id)[0]
            return DecisionOutcome(
                ActionIntent(
                    id=action_id,
                    actor_id=profile.id,
                    round_no=round_no,
                    action_type=ActionType.INVESTIGATE,
                    location_id=observation.current_location,
                    target_ids=[clue.id],
                    intended_effects=["核验现场证据"],
                    evidence_event_ids=evidence_ids[:2],
                    confidence=0.82,
                    rationale=f"当前位置可能推进目标：{profile.goals[0].description}",
                )
            )

        unshared = sorted(known - shared)
        if unshared and round_no >= profile.strategy.reveal_after_round:
            clue_id = unshared[0]
            clue = bundle.scenario.clue_map[clue_id]
            return DecisionOutcome(
                ActionIntent(
                    id=action_id,
                    actor_id=profile.id,
                    round_no=round_no,
                    action_type=ActionType.REVEAL,
                    target_ids=[clue_id],
                    public_content=_voice(
                        profile,
                        f"我已确认“{clue.display_name}”。先共享证据，再讨论下一步。",
                    ),
                    intended_effects=["将已验证线索加入团队证据链"],
                    evidence_event_ids=_evidence_for_clue(memories, clue_id) or evidence_ids[:2],
                    confidence=0.91,
                    rationale="独立线索尚未进入团队共享集合。",
                )
            )

        repair_id = profile.strategy.repair_resource
        if repair_id and repair_id in observation.visible_resources:
            definition = bundle.scenario.resource_map[repair_id]
            ratio = observation.visible_resources[repair_id] / definition.maximum
            if ratio < 0.72 and (known or round_no >= 3):
                return DecisionOutcome(
                    ActionIntent(
                        id=action_id,
                        actor_id=profile.id,
                        round_no=round_no,
                        action_type=ActionType.USE_RESOURCE,
                        target_ids=[repair_id],
                        location_id=observation.current_location,
                        public_content=_voice(
                            profile,
                            f"我来稳定{definition.display_name}，避免调查窗口继续缩小。",
                        ),
                        intended_effects=[f"修复资源 {repair_id}"],
                        evidence_event_ids=evidence_ids[:1],
                        confidence=0.79,
                        rationale=f"{definition.display_name}当前仅为{ratio:.0%}。",
                    )
                )

        destination = _next_destination(profile, observation, bundle)
        if destination and destination != observation.current_location:
            return DecisionOutcome(
                ActionIntent(
                    id=action_id,
                    actor_id=profile.id,
                    round_no=round_no,
                    action_type=ActionType.MOVE,
                    target_ids=[destination],
                    location_id=destination,
                    intended_effects=["前往下一调查区域"],
                    evidence_event_ids=evidence_ids[:1],
                    confidence=0.74,
                    rationale="当前区域没有新的可验证线索，转向下一优先地点。",
                )
            )

        if observation.visible_characters:
            target = sorted(observation.visible_characters)[0]
            content = _voice(profile, "现有证据可以互相校验。把你观察到的时间顺序告诉我。")
            return DecisionOutcome(
                ActionIntent(
                    id=action_id,
                    actor_id=profile.id,
                    round_no=round_no,
                    action_type=ActionType.ASK,
                    target_ids=[target],
                    public_content=content,
                    intended_effects=["核对双方观察"],
                    evidence_event_ids=evidence_ids[:2],
                    confidence=0.66,
                    rationale="通过现场交流寻找证据之间的对应关系。",
                )
            )

        return DecisionOutcome(
            ActionIntent(
                id=action_id,
                actor_id=profile.id,
                round_no=round_no,
                action_type=ActionType.WAIT,
                public_content=_voice(profile, "暂时没有足够依据，先保持观察。"),
                intended_effects=["等待新的可见事件"],
                evidence_event_ids=evidence_ids[:1],
                confidence=0.58,
                rationale="没有安全且能推进目标的行动。",
            )
        )


class ScriptedDecisionProvider(HeuristicDecisionProvider):
    """A named, stable policy for golden demos; it intentionally has no randomness."""


class DecisionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: ActionType
    target_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    public_content: str | None = None
    private_content: str | None = None
    intended_effects: list[str] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    rationale: str


class OpenAIDecisionProvider:
    def __init__(self, model: str, fallback: DecisionProvider | None = None) -> None:
        self.model = model
        self.fallback = fallback or HeuristicDecisionProvider()
        self._system_prompt = (
            Path(__file__).resolve().parents[3]
            / "prompts"
            / "character_decision"
            / "system_v1.txt"
        ).read_text(encoding="utf-8")

    def decide(
        self,
        profile: CharacterProfile,
        observation: ObservationPacket,
        memories: list[Memory],
        bundle: ScenarioBundle,
        rng: random.Random,
    ) -> DecisionOutcome:
        if not os.getenv("OPENAI_API_KEY"):
            return self._fallback(
                profile, observation, memories, bundle, rng, "OPENAI_API_KEY 未配置"
            )
        started = time.perf_counter()
        try:
            from openai import OpenAI

            client = OpenAI()
            context = {
                "character": {
                    "id": profile.id,
                    "display_name": profile.display_name,
                    "values": profile.values,
                    "behavioral_rules": profile.behavioral_rules,
                    "hard_constraints": profile.hard_constraints,
                    "speech_style": profile.speech_style.model_dump(mode="json"),
                    "goals": [
                        goal.model_dump(mode="json") for goal in observation.active_goals
                    ],
                },
                "observation": observation.model_dump(mode="json"),
                "retrieved_memories": [
                    memory.model_dump(mode="json") for memory in memories
                ],
            }
            response = client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False, sort_keys=True),
                    },
                ],
                text_format=DecisionDraft,
            )
            draft = response.output_parsed
            if draft is None:
                raise ValueError("模型未返回可解析的行动")
            if not set(draft.evidence_event_ids) <= set(observation.accessible_event_ids):
                raise ValueError("模型引用了不可见事件")
            action = ActionIntent(
                id=f"A-{observation.round_no:03d}-{profile.id}",
                actor_id=profile.id,
                round_no=observation.round_no,
                **draft.model_dump(),
            )
            usage = getattr(response, "usage", None)
            trace = ModelCallTrace(
                provider="openai",
                model=self.model,
                actor_id=profile.id,
                round_no=observation.round_no,
                duration_ms=int((time.perf_counter() - started) * 1000),
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            )
            return DecisionOutcome(action=action, trace=trace)
        except Exception as exc:
            return self._fallback(profile, observation, memories, bundle, rng, str(exc))

    def _fallback(
        self,
        profile: CharacterProfile,
        observation: ObservationPacket,
        memories: list[Memory],
        bundle: ScenarioBundle,
        rng: random.Random,
        error: str,
    ) -> DecisionOutcome:
        outcome = self.fallback.decide(profile, observation, memories, bundle, rng)
        return DecisionOutcome(
            action=outcome.action,
            trace=ModelCallTrace(
                provider="openai",
                model=self.model,
                actor_id=profile.id,
                round_no=observation.round_no,
                duration_ms=0,
                retries=1,
                error=f"已回退离线策略：{error[:300]}",
            ),
        )


def provider_for(policy: str, model: str) -> DecisionProvider:
    if policy == "llm":
        return OpenAIDecisionProvider(model)
    if policy == "scripted":
        return ScriptedDecisionProvider()
    return HeuristicDecisionProvider()


def _memory_evidence(memories: list[Memory], accessible: list[str]) -> list[str]:
    allowed = set(accessible)
    return list(
        dict.fromkeys(
            event_id
            for memory in memories
            for event_id in memory.source_event_ids
            if event_id in allowed
        )
    )


def _evidence_for_clue(memories: list[Memory], clue_id: str) -> list[str]:
    return list(
        dict.fromkeys(
            event_id
            for memory in memories
            if clue_id in memory.tags
            for event_id in memory.source_event_ids
        )
    )[:3]


def _next_destination(
    profile: CharacterProfile,
    observation: ObservationPacket,
    bundle: ScenarioBundle,
) -> str | None:
    current = observation.current_location
    priorities = profile.strategy.investigation_priorities
    known_clues = set(observation.known_clue_ids)
    eligible_locations = {
        clue.location_id
        for clue in bundle.scenario.clues
        if clue.id not in known_clues
        and clue.earliest_round <= observation.round_no
        and (not clue.discoverers or profile.id in clue.discoverers)
    }
    desired = next(
        (location for location in priorities if location in eligible_locations),
        priorities[observation.round_no % len(priorities)] if priorities else current,
    )
    if desired == current:
        return current
    if desired in bundle.scenario.adjacency[current]:
        return desired
    neighbors = bundle.scenario.adjacency[current]
    for neighbor in neighbors:
        if desired in bundle.scenario.adjacency.get(neighbor, []):
            return neighbor
    return sorted(neighbors)[0] if neighbors else None


def _voice(profile: CharacterProfile, content: str) -> str:
    if profile.id == "march_7th":
        return f"等等，{content}"
    if profile.id == "dan_heng":
        return content.replace("。", "。", 1)
    if profile.id == "himeko":
        return f"{content} 我们按这个顺序推进。"
    if profile.id == "welt":
        return f"{content} 先把风险边界留清楚。"
    return content
