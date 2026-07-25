from __future__ import annotations

from astral_agents.domain.models import (
    ActionIntent,
    CanonicalEvent,
    ObservationPacket,
    ScenarioBundle,
    Severity,
    ValidationFinding,
    WorldState,
)


def check_information_boundaries(
    actions: list[ActionIntent],
    observations: dict[str, ObservationPacket],
    bundle: ScenarioBundle,
    round_no: int,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    canary_owners = {
        fact.canary: character.id
        for character in bundle.characters
        for fact in character.private_facts
        if fact.canary
    }
    for action in actions:
        accessible = set(observations[action.actor_id].accessible_event_ids)
        illegal = set(action.evidence_event_ids) - accessible
        if illegal:
            findings.append(
                ValidationFinding(
                    code="INVISIBLE_EVIDENCE",
                    severity=Severity.CRITICAL,
                    message=f"行动引用不可见事件：{sorted(illegal)}",
                    round_no=round_no,
                    actor_id=action.actor_id,
                    blocked=True,
                )
            )
        text = " ".join(
            part
            for part in [
                action.public_content,
                action.private_content,
                action.rationale,
            ]
            if part
        )
        for canary, owner_id in canary_owners.items():
            if canary in text and owner_id != action.actor_id:
                findings.append(
                    ValidationFinding(
                        code="CANARY_LEAK",
                        severity=Severity.CRITICAL,
                        message=f"{action.actor_id} 提及了属于 {owner_id} 的私密 canary。",
                        round_no=round_no,
                        actor_id=action.actor_id,
                        blocked=True,
                    )
                )
    return findings


def check_world_and_events(
    before: WorldState,
    after: WorldState,
    events: list[CanonicalEvent],
    bundle: ScenarioBundle,
    round_no: int,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    known_characters = set(bundle.character_map)
    known_locations = set(bundle.scenario.location_map)

    if set(after.locations) != known_characters:
        findings.append(
            _critical(round_no, "CHARACTER_SET_DRIFT", "世界状态中的角色集合发生漂移。")
        )
    for character_id, location_id in after.locations.items():
        if location_id not in known_locations:
            findings.append(
                _critical(
                    round_no,
                    "UNKNOWN_LOCATION",
                    f"{character_id} 位于未知地点 {location_id!r}。",
                )
            )
    for event in events:
        unknown = (
            set(event.participants)
            | set(event.observers)
            | set(event.private_payloads)
        ) - known_characters
        if unknown:
            findings.append(
                _critical(
                    round_no,
                    "UNKNOWN_EVENT_ACTOR",
                    f"事件 {event.id} 引用了未知角色：{sorted(unknown)}",
                )
            )
        unauthorized_private = set(event.private_payloads) - (
            set(event.observers) | set(event.participants)
        )
        if unauthorized_private:
            findings.append(
                _critical(
                    round_no,
                    "PRIVATE_VISIBILITY_MISMATCH",
                    f"事件 {event.id} 的私密接收者不在可见集合："
                    f"{sorted(unauthorized_private)}",
                )
            )
    if before.scenario_id != after.scenario_id or before.seed != after.seed:
        findings.append(
            _critical(round_no, "IMMUTABLE_STATE_DRIFT", "场景 ID 或随机种子被改写。")
        )
    if after.round_no != round_no:
        findings.append(
            _critical(
                round_no,
                "ROUND_STATE_MISMATCH",
                f"提交后的状态轮次为 {after.round_no}，预期为 {round_no}。",
            )
        )
    return findings


def assert_observation_isolation(
    observation: ObservationPacket,
    bundle: ScenarioBundle,
) -> None:
    serialized = observation.model_dump_json()
    for character in bundle.characters:
        if character.id == observation.character_id:
            continue
        for fact in character.private_facts:
            if fact.canary and fact.canary in serialized:
                raise AssertionError(
                    f"observation for {observation.character_id} contains "
                    f"{character.id}'s canary"
                )
            if fact.content in serialized:
                raise AssertionError(
                    f"observation for {observation.character_id} contains "
                    f"{character.id}'s private fact"
                )


def _critical(round_no: int, code: str, message: str) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=Severity.CRITICAL,
        message=message,
        round_no=round_no,
        blocked=True,
    )

