from astral_agents.domain.models import ActionIntent, ActionType
from astral_agents.simulation.adjudicator import validate_action
from astral_agents.simulation.checks import assert_observation_isolation
from astral_agents.simulation.observation import build_observation
from astral_agents.simulation.reducer import create_initial_state


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

