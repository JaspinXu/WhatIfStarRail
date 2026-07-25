import pytest

from astral_agents.domain.models import CanonicalEvent, StateChange
from astral_agents.simulation.reducer import (
    InvalidStateChange,
    apply_event,
    create_initial_state,
)


def test_reducer_is_pure_and_moves_to_adjacent_location(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 7)
    event = CanonicalEvent(
        id="R001-E01-move",
        round_no=1,
        event_type="character_moved",
        participants=["march_7th"],
        observers=["march_7th"],
        public_summary="三月七前往档案室。",
        changes=[
            StateChange(
                kind="set_location",
                subject_id="march_7th",
                value="archive",
            )
        ],
    )

    updated, diffs = apply_event(state, event, bundle)

    assert state.locations["march_7th"] == "cargo_bay"
    assert updated.locations["march_7th"] == "archive"
    assert diffs[0].before == "cargo_bay"
    assert diffs[0].after == "archive"


def test_illegal_transition_does_not_mutate_input(bundle) -> None:
    state = create_initial_state(bundle, "test-run", 7)
    initial_power = state.resources["power"]
    event = CanonicalEvent(
        id="R001-E01-invalid",
        round_no=1,
        event_type="invalid_test",
        participants=[],
        observers=[],
        public_summary=None,
        changes=[
            StateChange(kind="adjust_resource", subject_id="power", value=-1),
            StateChange(kind="adjust_resource", subject_id="power", value=-500),
        ],
    )

    with pytest.raises(InvalidStateChange):
        apply_event(state, event, bundle)

    assert state.resources["power"] == initial_power
    assert state.round_no == 0


def test_unknown_patch_kind_is_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        StateChange(kind="overwrite_canon", subject_id="canon", value=True)

