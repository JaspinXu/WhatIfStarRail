from __future__ import annotations

from astral_agents.domain.models import (
    ActionType,
    CanonicalEvent,
    ObservationPacket,
    ScenarioBundle,
    WorldState,
)


def build_observation(
    character_id: str,
    state: WorldState,
    events: list[CanonicalEvent],
    bundle: ScenarioBundle,
    *,
    history_limit: int = 16,
) -> ObservationPacket:
    profile = bundle.character_map[character_id]
    current_location = state.locations[character_id]
    visible_characters = sorted(
        actor_id
        for actor_id, location_id in state.locations.items()
        if location_id == current_location and actor_id != character_id
    )

    public_events: list[dict[str, object]] = []
    witnessed_events: list[dict[str, object]] = []
    private_messages: list[dict[str, object]] = []
    accessible_ids: list[str] = []

    for event in events[-history_limit:]:
        is_public = "public" in event.tags
        is_witness = character_id in event.observers or character_id in event.participants
        if is_public and event.public_summary:
            public_events.append(_event_view(event))
            accessible_ids.append(event.id)
        elif is_witness and event.public_summary:
            witnessed_events.append(_event_view(event))
            accessible_ids.append(event.id)
        if character_id in event.private_payloads:
            private_messages.append(
                {
                    "event_id": event.id,
                    "round_no": event.round_no,
                    "content": event.private_payloads[character_id],
                    "tags": event.tags,
                }
            )
            accessible_ids.append(event.id)

    known_clues = sorted(
        clue_id
        for clue_id, discovery in state.discovered_clues.items()
        if discovery.discovered_by == character_id or clue_id in state.shared_clue_ids
    )
    shared_clues = sorted(set(known_clues) & set(state.shared_clue_ids))
    public_resource_ids = {
        resource.id for resource in bundle.scenario.resources if resource.public
    }
    canon_facts = [
        {
            "id": fact.id,
            "subject_id": fact.subject_id,
            "predicate": fact.predicate,
            "value": fact.value,
        }
        for fact in bundle.canon_facts
        if fact.subject_id == character_id
    ]
    return ObservationPacket(
        character_id=character_id,
        round_no=state.round_no + 1,
        phase=state.phase,
        current_location=current_location,
        visible_characters=visible_characters,
        visible_resources={
            key: value for key, value in state.resources.items() if key in public_resource_ids
        },
        public_events=public_events,
        witnessed_events=witnessed_events,
        private_messages=private_messages,
        canon_facts=canon_facts,
        known_clue_ids=known_clues,
        shared_clue_ids=shared_clues,
        accessible_event_ids=sorted(set(accessible_ids)),
        active_goals=profile.goals,
        open_threads=list(state.open_threads),
        allowed_actions=list(ActionType),
    )


def _event_view(event: CanonicalEvent) -> dict[str, object]:
    return {
        "event_id": event.id,
        "round_no": event.round_no,
        "event_type": event.event_type,
        "summary": event.public_summary,
        "participants": event.participants,
        "tags": event.tags,
    }

