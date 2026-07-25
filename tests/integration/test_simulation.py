from pathlib import Path

from astral_agents.domain.models import RunConfig, RunStatus
from astral_agents.evaluation.metrics import evaluate_run
from astral_agents.simulation.engine import SimulationEngine
from astral_agents.storage.repository import SQLiteRepository


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
    assert metrics["critical_findings"] == 0
    assert metrics["leakage_findings"] == 0
    assert metrics["evidence_validity_rate"] == 1.0
    assert metrics["narrative_event_coverage"] == 1.0


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

