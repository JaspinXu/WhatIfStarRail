from astral_agents.domain.models import ActionIntent, ActionType
from astral_agents.simulation.adjudicator import adjudicate_actions, validate_action
from astral_agents.simulation.checks import (
    assert_observation_isolation,
    check_information_boundaries,
)
from astral_agents.simulation.observation import build_observation
from astral_agents.simulation.reducer import apply_event, create_initial_state


def test_observations_do_not_contain_other_characters_private_facts(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 42)

    for character in bundle.characters:
        observation = build_observation(character.id, state, [], bundle)
        assert_observation_isolation(observation, bundle)
        serialized = observation.model_dump_json()
        for other in bundle.characters:
            if other.id == character.id:
                continue
            assert all(fact.content not in serialized for fact in other.private_facts)


def test_invisible_evidence_is_a_blocking_finding(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 42)
    observation = build_observation("dan_heng", state, [], bundle)
    action = ActionIntent(
        id="A-001-dan_heng",
        actor_id="dan_heng",
        round_no=1,
        action_type=ActionType.WAIT,
        evidence_event_ids=["SECRET-EVENT"],
    )

    finding = validate_action(action, observation, state, bundle)

    assert finding is not None
    assert finding.code == "INVISIBLE_EVIDENCE"
    assert finding.blocked


def test_character_cannot_reveal_unknown_clue(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 42)
    observation = build_observation("welt", state, [], bundle)
    action = ActionIntent(
        id="A-001-welt",
        actor_id="welt",
        round_no=1,
        action_type=ActionType.REVEAL,
        target_ids=["manifest_hash"],
    )

    finding = validate_action(action, observation, state, bundle)

    assert finding is not None
    assert finding.code == "UNKNOWN_CLUE"
    assert finding.blocked


def test_any_canary_repeated_in_an_action_blocks_the_round(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 42)
    observations = {
        character.id: build_observation(character.id, state, [], bundle)
        for character in bundle.characters
    }
    actions = [
        ActionIntent(
            id="A-001-march_7th",
            actor_id="march_7th",
            round_no=1,
            action_type=ActionType.WAIT,
            rationale="M7-CANARY-GLASS-COMET",
        ),
        ActionIntent(
            id="A-001-dan_heng",
            actor_id="dan_heng",
            round_no=1,
            action_type=ActionType.WAIT,
            public_content="WT-CANARY-GRAVITY-PAPER",
        ),
        ActionIntent(
            id="A-001-himeko",
            actor_id="himeko",
            round_no=1,
            action_type=ActionType.WAIT,
            intended_effects=["将 HM-CANARY-AMBER-RAIL 写入审计记录"],
        ),
    ]

    findings = check_information_boundaries(
        actions, observations, bundle, round_no=1
    )

    assert [finding.code for finding in findings] == [
        "CANARY_LEAK",
        "CANARY_LEAK",
        "CANARY_LEAK",
    ]
    assert all(finding.blocked for finding in findings)


def test_simultaneous_investigations_reserve_a_clue_once(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 42)
    state.locations["march_7th"] = "comm_array"
    state.locations["dan_heng"] = "comm_array"
    state.round_no = 1
    observations = {
        actor_id: build_observation(actor_id, state, [], bundle)
        for actor_id in ["march_7th", "dan_heng"]
    }
    actions = [
        ActionIntent(
            id=f"A-002-{actor_id}",
            actor_id=actor_id,
            round_no=2,
            action_type=ActionType.INVESTIGATE,
            location_id="comm_array",
            target_ids=["canceling_signal"],
        )
        for actor_id in observations
    ]

    result = adjudicate_actions(actions, observations, state, bundle, 2)

    assert sum(event.event_type == "clue_discovered" for event in result.events) == 1
    assert sum(
        event.event_type == "investigation_completed" for event in result.events
    ) == 1


def test_simultaneous_repairs_do_not_overfill_a_resource(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 42)
    state.resources["power"] = 95
    actor_ids = ["himeko", "welt"]
    observations = {
        actor_id: build_observation(actor_id, state, [], bundle)
        for actor_id in actor_ids
    }
    actions = [
        ActionIntent(
            id=f"A-001-{actor_id}",
            actor_id=actor_id,
            round_no=1,
            action_type=ActionType.USE_RESOURCE,
            target_ids=["power"],
        )
        for actor_id in actor_ids
    ]

    result = adjudicate_actions(actions, observations, state, bundle, 1)
    final_state = state
    for event in result.events:
        final_state, _ = apply_event(final_state, event, bundle)

    assert final_state.resources["power"] <= final_state.resource_limits["power"][1]
