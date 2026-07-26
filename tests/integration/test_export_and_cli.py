import io
import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from astral_agents.cli import app
from astral_agents.domain.models import (
    ActionIntent,
    ActionType,
    RunConfig,
    RunStatus,
)
from astral_agents.exporter import build_demo_archive, build_export_payload
from astral_agents.simulation.engine import SimulationEngine
from astral_agents.simulation.policies import DecisionOutcome

runner = CliRunner()


def test_sanitized_export_omits_private_trace(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=42)
    )
    engine.run(run_id, rounds=2)

    archive_bytes = build_demo_archive(repository, run_id)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "events.jsonl",
            "world_snapshots.jsonl",
            "chapters.md",
            "metrics.csv",
            "README.txt",
        }
        combined = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
        assert "旧哈希早于求援信号十二分钟" not in combined
        assert "-CANARY-" not in combined
        assert '"private_payloads": {}' in combined
        assert "OPENAI_API_KEY=" not in combined


def test_private_export_is_explicit_and_labeled(bundle, repository) -> None:
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=42)
    )
    engine.run(run_id, rounds=1)

    archive_bytes = build_demo_archive(
        repository, run_id, include_private=True
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert "private_trace.json" in archive.namelist()
        trace = archive.read("private_trace.json").decode("utf-8")
        assert "full_research_trace" in trace
        assert "旧哈希早于求援信号十二分钟" in trace
        assert "M7-CANARY-GLASS-COMET" in trace
        assert "DH-CANARY-INK-ORBIT" in trace
        assert "HM-CANARY-AMBER-RAIL" in trace
        assert "WT-CANARY-GRAVITY-PAPER" in trace


def test_sanitized_export_redacts_a_blocked_canary_action(
    bundle, repository, monkeypatch
) -> None:
    class CanaryProvider:
        def decide(self, profile, observation, memories, bundle, rng):
            canary = profile.private_facts[0].canary
            return DecisionOutcome(
                ActionIntent(
                    id=f"A-{observation.round_no:03d}-{profile.id}",
                    actor_id=profile.id,
                    round_no=observation.round_no,
                    action_type=ActionType.WAIT,
                    intended_effects=[f"记录 {canary}"],
                )
            )

    monkeypatch.setattr(
        "astral_agents.simulation.engine.provider_for",
        lambda policy, model: CanaryProvider(),
    )
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(scenario_id=bundle.scenario.id, seed=6)
    )

    engine.step(run_id)
    sanitized = build_export_payload(repository, run_id)
    full = build_export_payload(repository, run_id, include_private=True)

    assert repository.get_state(run_id).status == RunStatus.BLOCKED
    assert "-CANARY-" not in json.dumps(sanitized, ensure_ascii=False)
    assert all(
        action["redacted_due_to"] == "CANARY_LEAK"
        for action in sanitized["rounds"][0]["actions"]
    )
    assert "-CANARY-" in json.dumps(full, ensure_ascii=False)


def test_cli_validate_and_one_round_run(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.output
    assert "配置有效" in result.output

    database = tmp_path / "cli.sqlite"
    result = runner.invoke(
        app,
        [
            "run",
            "--database",
            str(database),
            "--seed",
            "12",
            "--rounds",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "运行完成" in result.output
    assert database.exists()
