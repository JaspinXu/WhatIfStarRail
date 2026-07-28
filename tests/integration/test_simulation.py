import json
from pathlib import Path

import pytest

from astral_agents.domain.models import RunConfig, RunStatus
from astral_agents.evaluation.metrics import evaluate_run
from astral_agents.simulation.engine import IncompatibleRunError, SimulationEngine
from astral_agents.simulation.observation import build_observation
from astral_agents.storage.repository import ConcurrentRunUpdateError, SQLiteRepository


def _create_engine(bundle, path: Path) -> SimulationEngine:
    return SimulationEngine(bundle, SQLiteRepository(path))


def test_complete_offline_demo_succeeds_and_replays(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=42, policy="heuristic")
    )

    records = engine.run(run_id)
    state = repository.get_state(run_id)
    replay = engine.replay(run_id)
    metrics = evaluate_run(repository, run_id)

    assert len(records) == 10
    assert state.status == RunStatus.SUCCEEDED
    assert state.round_no == 10
    assert not state.open_threads
    assert len(repository.get_episodes(run_id)) == 4
    assert replay.matched
    assert replay.event_sources_consistent
    assert replay.expected_timeline_hash == replay.actual_timeline_hash
    assert metrics["critical_findings"] == 0
    assert metrics["leakage_findings"] == 0
    assert metrics["evidence_validity_rate"] == 1.0
    assert metrics["narrative_event_coverage"] == 1.0
    assert all(
        action.public_content
        for record in records
        for action in record.actions
    )


def test_custom_story_background_reaches_every_character_and_replays(
    bundle, repository
) -> None:
    engine = SimulationEngine(bundle, repository)
    story_background = (
        "星穹列车误入一座会重写访客记忆的海上城市，"
        "众人必须在黎明前确认谁仍记得真实航线。"
    )
    run_id = engine.create_run(
        RunConfig(
            scenario_id=bundle.scenario.id,
            seed=23,
            policy="heuristic",
            story_background=story_background,
        )
    )

    state = repository.get_state(run_id)
    opening_events = repository.get_events(run_id, end_round=0)
    observations = [
        build_observation(character.id, state, opening_events, bundle)
        for character in bundle.characters
    ]
    record = engine.step(run_id)
    replay = engine.replay(run_id)

    assert state.story_background == story_background
    assert repository.get_manifest(run_id).story_background == story_background
    assert {item.story_background for item in observations} == {story_background}
    assert all(action.public_content for action in record.actions)
    assert replay.matched


def test_same_seed_produces_same_structural_state(bundle, tmp_path: Path) -> None:
    first = _create_engine(bundle, tmp_path / "first.sqlite")
    first_id = first.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=17, policy="scripted")
    )
    first.run(first_id)

    second = _create_engine(bundle, tmp_path / "second.sqlite")
    second_id = second.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=17, policy="scripted")
    )
    second.run(second_id)

    assert (
        first.repository.get_state(first_id).state_digest()
        == second.repository.get_state(second_id).state_digest()
    )
    assert (
        first.repository.get_state(first_id).timeline_hash
        == second.repository.get_state(second_id).timeline_hash
    )


def test_pause_and_resume_matches_continuous_run(bundle, tmp_path: Path) -> None:
    resumed_engine = _create_engine(bundle, tmp_path / "resumed.sqlite")
    resumed_id = resumed_engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=9, policy="heuristic")
    )
    resumed_engine.run(resumed_id, rounds=5)

    reloaded_engine = _create_engine(
        bundle, resumed_engine.repository.path
    )
    reloaded_engine.run(resumed_id)
    resumed_state = reloaded_engine.repository.get_state(resumed_id)

    continuous_engine = _create_engine(bundle, tmp_path / "continuous.sqlite")
    continuous_id = continuous_engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=9, policy="heuristic")
    )
    continuous_engine.run(continuous_id)
    continuous_state = continuous_engine.repository.get_state(continuous_id)

    assert resumed_state.state_digest() == continuous_state.state_digest()
    assert resumed_state.timeline_hash == continuous_state.timeline_hash


def test_memory_queries_are_owner_isolated(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=1)
    )
    engine.run(run_id, rounds=3)

    for character in bundle.characters:
        memories = repository.get_memories(run_id, character.id)
        assert memories
        assert {memory.owner_id for memory in memories} == {character.id}

    dan_hits = repository.search_memory_ids(run_id, "dan_heng", "archive manifest")
    assert dan_hits
    dan_memory_ids = {
        memory.id for memory in repository.get_memories(run_id, "dan_heng")
    }
    assert set(dan_hits) <= dan_memory_ids


def test_canaries_are_seeded_only_into_their_owners_memories(
    bundle, repository
) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=3)
    )

    for owner in bundle.characters:
        owner_text = " ".join(
            memory.content
            for memory in repository.get_memories(run_id, owner.id)
        )
        for character in bundle.characters:
            for fact in character.private_facts:
                if not fact.canary:
                    continue
                if character.id == owner.id:
                    assert fact.canary in owner_text
                else:
                    assert fact.canary not in owner_text


def test_replay_detects_event_table_tampering(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=42)
    )
    engine.run(run_id, rounds=2)
    original = repository.get_events(run_id, start_round=1)[0]
    tampered = original.model_copy(
        update={"public_summary": f"{original.public_summary}（篡改）"}
    )

    with repository.transaction() as connection:
        connection.execute(
            """
            UPDATE events
            SET public_summary = ?, event_json = ?
            WHERE run_id = ? AND event_id = ?
            """,
            (
                tampered.public_summary,
                json.dumps(
                    tampered.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                run_id,
                tampered.id,
            ),
        )

    replay = engine.replay(run_id)

    assert not replay.matched
    assert not replay.event_sources_consistent
    assert replay.expected_timeline_hash != replay.actual_timeline_hash


def test_replay_detects_opening_event_tampering(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=42)
    )
    engine.run(run_id, rounds=1)
    original = repository.get_events(run_id, end_round=0)[0]
    tampered = original.model_copy(
        update={"public_summary": f"{original.public_summary}（篡改）"}
    )

    with repository.transaction() as connection:
        connection.execute(
            """
            UPDATE events
            SET public_summary = ?, event_json = ?
            WHERE run_id = ? AND event_id = ?
            """,
            (
                tampered.public_summary,
                json.dumps(
                    tampered.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                run_id,
                tampered.id,
            ),
        )

    replay = engine.replay(run_id)

    assert not replay.matched
    assert not replay.event_sources_consistent
    assert replay.expected_timeline_hash != replay.actual_timeline_hash


def test_run_zero_rounds_is_a_noop(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(RunConfig(scenario_id=bundle.scenario.id, seed=4))

    assert engine.run(run_id, rounds=0) == []
    assert repository.get_state(run_id).round_no == 0


def test_run_respects_configured_round_limit(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=4, max_rounds=2)
    )

    records = engine.run(run_id)

    assert len(records) == 2
    assert repository.get_state(run_id).status == RunStatus.FAILED


def test_create_run_rejects_a_different_scenario_id(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)

    with pytest.raises(IncompatibleRunError, match="does not match"):
        engine.create_run(RunConfig(scenario_id="another_scenario", seed=4))


def test_existing_run_rejects_scenario_config_drift(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(RunConfig(scenario_id=bundle.scenario.id, seed=4))
    changed_bundle = bundle.model_copy(update={"config_digest": "changed"})

    with pytest.raises(IncompatibleRunError, match="config digest"):
        SimulationEngine(changed_bundle, repository).step(run_id)


def test_stale_round_commit_is_rejected_atomically(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(RunConfig(scenario_id=bundle.scenario.id, seed=4))
    record = engine.step(run_id)

    with pytest.raises(ConcurrentRunUpdateError, match="changed while"):
        repository.commit_round(record, [], [], None)

    assert len(repository.get_rounds(run_id)) == 1


def test_recent_events_are_ordered_and_bounded(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(RunConfig(scenario_id=bundle.scenario.id, seed=4))
    engine.run(run_id, rounds=2)

    recent = repository.get_recent_events(run_id, limit=3)

    assert len(recent) == 3
    assert [(event.round_no, event.id) for event in recent] == sorted(
        (event.round_no, event.id) for event in recent
    )
