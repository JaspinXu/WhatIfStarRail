from __future__ import annotations

from collections import defaultdict

from astral_agents.domain.models import (
    ActionIntent,
    ActionType,
    CanonicalEvent,
    ObservationPacket,
    ScenarioBundle,
    Severity,
    StateChange,
    ValidationFinding,
    WorldState,
)


class AdjudicationResult:
    def __init__(
        self,
        actions: list[ActionIntent],
        events: list[CanonicalEvent],
        findings: list[ValidationFinding],
    ) -> None:
        self.actions = actions
        self.events = events
        self.findings = findings


def adjudicate_actions(
    actions: list[ActionIntent],
    observations: dict[str, ObservationPacket],
    state: WorldState,
    bundle: ScenarioBundle,
    round_no: int,
) -> AdjudicationResult:
    normalized: list[ActionIntent] = []
    findings: list[ValidationFinding] = []
    events: list[CanonicalEvent] = []
    event_index = 1
    resource_claims: defaultdict[str, list[str]] = defaultdict(list)
    reserved_clues: set[str] = set()

    for action in sorted(actions, key=lambda item: item.actor_id):
        issue = validate_action(action, observations[action.actor_id], state, bundle)
        if issue:
            findings.append(issue)
            rejected = action.model_copy(deep=True)
            rejected.action_type = ActionType.WAIT
            rejected.target_ids = []
            rejected.location_id = None
            rejected.public_content = None
            rejected.private_content = None
            rejected.intended_effects = ["非法行动已安全回退为等待"]
            rejected.rationale = f"裁决器回退：{issue.message}"
            normalized.append(rejected)
            events.append(
                CanonicalEvent(
                    id=_event_id(round_no, event_index, "rejected", action.actor_id),
                    round_no=round_no,
                    event_type="action_rejected",
                    participants=[action.actor_id],
                    observers=[action.actor_id],
                    public_summary=f"{bundle.character_map[action.actor_id].display_name}的行动未通过权限校验。",
                    private_payloads={action.actor_id: issue.message},
                    caused_by_action_ids=[action.id],
                    tags=["audit", "rejected"],
                )
            )
            event_index += 1
            continue
        normalized.append(action)
        if action.action_type == ActionType.USE_RESOURCE and action.target_ids:
            resource_claims[action.target_ids[0]].append(action.actor_id)

    for action in normalized:
        if any(action.id in event.caused_by_action_ids for event in events):
            continue
        generated = _event_for_action(
            action,
            state,
            bundle,
            round_no,
            event_index,
            resource_claims,
            reserved_clues,
        )
        events.append(generated)
        if generated.event_type == "clue_discovered":
            reserved_clues.update(
                tag for tag in generated.tags if tag in bundle.scenario.clue_map
            )
        event_index += 1

    decay_changes = []
    decay_amounts = {"power": -2.2, "life_support": -1.4, "phase_stability": -0.8}
    for resource_id, amount in decay_amounts.items():
        current = state.resources.get(resource_id)
        if current is None:
            continue
        minimum = state.resource_limits[resource_id][0]
        safe_amount = max(amount, minimum - current)
        if safe_amount:
            decay_changes.append(
                StateChange(
                    kind="adjust_resource",
                    subject_id=resource_id,
                    value=safe_amount,
                )
            )
    events.append(
        CanonicalEvent(
            id=_event_id(round_no, event_index, "decay", "system"),
            round_no=round_no,
            event_type="system_decay",
            participants=[],
            observers=list(bundle.character_map),
            public_summary="运输舰的能源与生命维持继续缓慢衰减。",
            changes=decay_changes,
            tags=["public", "system", "pressure"],
        )
    )
    return AdjudicationResult(normalized, events, findings)


def validate_action(
    action: ActionIntent,
    observation: ObservationPacket,
    state: WorldState,
    bundle: ScenarioBundle,
) -> ValidationFinding | None:
    if action.actor_id != observation.character_id:
        return _finding(action, "ACTOR_MISMATCH", "行动者与观察包所有者不一致。")
    if action.round_no != observation.round_no:
        return _finding(action, "ROUND_MISMATCH", "行动轮次与观察轮次不一致。")
    illegal_evidence = set(action.evidence_event_ids) - set(
        observation.accessible_event_ids
    )
    if illegal_evidence:
        return _finding(
            action,
            "INVISIBLE_EVIDENCE",
            f"行动引用了不可见事件：{sorted(illegal_evidence)}",
            severity=Severity.CRITICAL,
            blocked=True,
        )
    if action.action_type == ActionType.MOVE:
        destination = action.location_id or (action.target_ids[0] if action.target_ids else None)
        if destination not in bundle.scenario.location_map:
            return _finding(action, "UNKNOWN_LOCATION", "移动目标不是已知地点。")
        origin = state.locations[action.actor_id]
        if destination not in bundle.scenario.adjacency.get(origin, []):
            return _finding(
                action,
                "NON_ADJACENT_MOVE",
                f"无法从 {origin} 直接移动到 {destination}。",
            )
    if action.action_type == ActionType.INVESTIGATE:
        if action.location_id != observation.current_location:
            return _finding(action, "REMOTE_INVESTIGATION", "角色不能远程调查其他地点。")
    if action.action_type == ActionType.REVEAL:
        if not action.target_ids:
            return _finding(action, "MISSING_CLUE", "分享行动没有指定线索。")
        clue_id = action.target_ids[0]
        if clue_id not in observation.known_clue_ids:
            return _finding(
                action,
                "UNKNOWN_CLUE",
                f"角色试图分享自己尚未知晓的线索 {clue_id!r}。",
                severity=Severity.CRITICAL,
                blocked=True,
            )
    if action.action_type == ActionType.USE_RESOURCE:
        if not action.target_ids or action.target_ids[0] not in bundle.scenario.resource_map:
            return _finding(action, "UNKNOWN_RESOURCE", "资源操作没有合法目标。")
    return None


def _event_for_action(
    action: ActionIntent,
    state: WorldState,
    bundle: ScenarioBundle,
    round_no: int,
    event_index: int,
    resource_claims: dict[str, list[str]],
    reserved_clues: set[str],
) -> CanonicalEvent:
    profile = bundle.character_map[action.actor_id]
    observers_here = sorted(
        actor_id
        for actor_id, location_id in state.locations.items()
        if location_id == state.locations[action.actor_id]
    )
    event_id = _event_id(round_no, event_index, action.action_type.value, action.actor_id)

    if action.action_type == ActionType.MOVE:
        destination = action.location_id or action.target_ids[0]
        destination_observers = [
            actor_id
            for actor_id, location_id in state.locations.items()
            if location_id == destination
        ]
        return CanonicalEvent(
            id=event_id,
            round_no=round_no,
            event_type="character_moved",
            participants=[action.actor_id],
            observers=sorted(set(observers_here + destination_observers)),
            public_summary=(
                f"{profile.display_name}从"
                f"{bundle.scenario.location_map[state.locations[action.actor_id]].display_name}"
                f"前往{bundle.scenario.location_map[destination].display_name}。"
            ),
            changes=[
                StateChange(
                    kind="set_location",
                    subject_id=action.actor_id,
                    value=destination,
                )
            ],
            caused_by_action_ids=[action.id],
            tags=["movement", destination],
        )

    if action.action_type == ActionType.INVESTIGATE:
        candidates = [
            clue
            for clue in bundle.scenario.clues
            if clue.location_id == state.locations[action.actor_id]
            and clue.earliest_round <= round_no
            and (not clue.discoverers or action.actor_id in clue.discoverers)
            and clue.id not in state.discovered_clues
            and clue.id not in reserved_clues
        ]
        if action.target_ids:
            candidates.sort(
                key=lambda clue: (clue.id != action.target_ids[0], clue.id)
            )
        else:
            candidates.sort(key=lambda clue: clue.id)
        if not candidates:
            return CanonicalEvent(
                id=event_id,
                round_no=round_no,
                event_type="investigation_completed",
                participants=[action.actor_id],
                observers=observers_here,
                public_summary=f"{profile.display_name}完成调查，但没有发现新的可验证证据。",
                caused_by_action_ids=[action.id],
                tags=["investigation", state.locations[action.actor_id]],
            )
        clue = candidates[0]
        changes = [
            StateChange(
                kind="discover_clue",
                subject_id=clue.id,
                target_id=action.actor_id,
                value=True,
            ),
            StateChange(
                kind="adjust_resource",
                subject_id="evidence",
                value=clue.evidence_points,
            ),
        ]
        if clue.sets_flag:
            changes.append(
                StateChange(kind="set_flag", subject_id=clue.sets_flag, value=True)
            )
        if clue.resolves_thread:
            changes.append(
                StateChange(kind="close_thread", subject_id=clue.resolves_thread, value=True)
            )
        return CanonicalEvent(
            id=event_id,
            round_no=round_no,
            event_type="clue_discovered",
            participants=[action.actor_id],
            observers=observers_here,
            public_summary=f"{profile.display_name}确认了一项新证据：{clue.public_summary}",
            private_payloads={action.actor_id: clue.private_detail},
            changes=changes,
            caused_by_action_ids=[action.id],
            tags=["investigation", clue.location_id, clue.id, *clue.tags],
        )

    if action.action_type == ActionType.REVEAL:
        clue_id = action.target_ids[0]
        clue = bundle.scenario.clue_map[clue_id]
        already_shared = clue_id in state.shared_clue_ids
        return CanonicalEvent(
            id=event_id,
            round_no=round_no,
            event_type="clue_shared",
            participants=[action.actor_id],
            observers=list(bundle.character_map),
            public_summary=(
                action.public_content
                or f"{profile.display_name}向团队共享了线索：{clue.public_summary}"
            ),
            changes=(
                []
                if already_shared
                else [StateChange(kind="share_clue", subject_id=clue_id, value=True)]
            ),
            caused_by_action_ids=[action.id],
            tags=["public", "evidence", clue_id, *clue.tags],
        )

    if action.action_type == ActionType.USE_RESOURCE:
        resource_id = action.target_ids[0]
        definition = bundle.scenario.resource_map[resource_id]
        current = state.resources[resource_id]
        amount = min(10.0, definition.maximum - current)
        claimants = sorted(resource_claims.get(resource_id, []))
        if len(claimants) > 1 and action.actor_id != claimants[0]:
            amount = min(4.0, max(0.0, definition.maximum - current))
        changes: list[StateChange] = []
        if amount > 0:
            changes.append(
                StateChange(
                    kind="adjust_resource",
                    subject_id=resource_id,
                    value=amount,
                )
            )
        return CanonicalEvent(
            id=event_id,
            round_no=round_no,
            event_type="system_repaired",
            participants=[action.actor_id],
            observers=observers_here,
            public_summary=(
                action.public_content
                or f"{profile.display_name}让{definition.display_name}恢复了{amount:g}{definition.unit}。"
            ),
            changes=changes,
            caused_by_action_ids=[action.id],
            tags=["repair", resource_id],
        )

    if action.action_type in {
        ActionType.SPEAK,
        ActionType.ASK,
        ActionType.NEGOTIATE,
        ActionType.ASSIST,
        ActionType.OPPOSE,
    }:
        relationship_changes = []
        for target in action.target_ids:
            if target in state.relationships.get(action.actor_id, {}):
                relationship_changes.append(
                    StateChange(
                        kind="adjust_relationship",
                        subject_id=target,
                        target_id=action.actor_id,
                        dimension="trust",
                        value=0.02 if action.action_type != ActionType.OPPOSE else -0.02,
                    )
                )
        return CanonicalEvent(
            id=event_id,
            round_no=round_no,
            event_type=f"social_{action.action_type.value}",
            participants=[action.actor_id, *action.target_ids],
            observers=observers_here,
            public_summary=action.public_content or f"{profile.display_name}与现场成员交换了意见。",
            changes=relationship_changes,
            caused_by_action_ids=[action.id],
            tags=["dialogue", action.action_type.value],
        )

    return CanonicalEvent(
        id=event_id,
        round_no=round_no,
        event_type="character_waited",
        participants=[action.actor_id],
        observers=observers_here,
        public_summary=action.public_content or f"{profile.display_name}保持观察，没有贸然行动。",
        caused_by_action_ids=[action.id],
        tags=["wait"],
    )


def _finding(
    action: ActionIntent,
    code: str,
    message: str,
    *,
    severity: Severity = Severity.ERROR,
    blocked: bool = False,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity,
        message=message,
        round_no=action.round_no,
        actor_id=action.actor_id,
        blocked=blocked,
    )


def _event_id(round_no: int, index: int, kind: str, actor: str) -> str:
    compact_kind = kind.replace("_", "-")[:12]
    compact_actor = actor.replace("_", "-")[:10]
    return f"R{round_no:03d}-E{index:02d}-{compact_kind}-{compact_actor}"
