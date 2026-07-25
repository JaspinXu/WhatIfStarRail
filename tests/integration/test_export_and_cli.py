import io
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from astral_agents.cli import app
from astral_agents.domain.models import RunConfig
from astral_agents.exporter import build_demo_archive
from astral_agents.simulation.engine import SimulationEngine

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
