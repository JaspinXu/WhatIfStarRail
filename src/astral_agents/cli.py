from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from astral_agents.config import DEFAULT_SCENARIO_DIR, load_scenario
from astral_agents.domain.models import RunConfig
from astral_agents.evaluation.metrics import evaluate_run
from astral_agents.exporter import write_demo_archive
from astral_agents.simulation.engine import SimulationEngine
from astral_agents.simulation.observation import build_observation
from astral_agents.storage.repository import SQLiteRepository

app = typer.Typer(
    name="astral",
    help="事件溯源的多智能体叙事模拟原型。",
    no_args_is_help=True,
)
console = Console()

ScenarioOption = Annotated[
    Path,
    typer.Option("--scenario", "-s", help="场景配置目录。"),
]
DatabaseOption = Annotated[
    Path,
    typer.Option("--database", "-d", help="SQLite 运行数据库。"),
]


@app.command()
def validate(
    scenario: ScenarioOption = DEFAULT_SCENARIO_DIR,
) -> None:
    """校验场景 schema 与所有交叉引用。"""
    bundle = load_scenario(scenario)
    console.print(
        Panel.fit(
            f"[bold green]配置有效[/bold green]\n"
            f"场景：{bundle.scenario.title} · v{bundle.scenario.version}\n"
            f"角色：{len(bundle.characters)}｜地点：{len(bundle.scenario.locations)}｜"
            f"线索：{len(bundle.scenario.clues)}\n"
            f"摘要：{bundle.config_digest}",
            title="Astral validation",
        )
    )


@app.command("run")
def run_command(
    scenario: ScenarioOption = DEFAULT_SCENARIO_DIR,
    database: DatabaseOption = Path("runs/astral.sqlite"),
    seed: Annotated[int, typer.Option("--seed", help="可复现随机种子。")] = 42,
    policy: Annotated[
        str,
        typer.Option("--policy", help="heuristic、scripted 或 llm。"),
    ] = "heuristic",
    rounds: Annotated[
        Optional[int],
        typer.Option("--rounds", help="最多推进轮数；默认运行到终局。"),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", help="LLM 模式使用的 OpenAI 模型。"),
    ] = os.getenv("ASTRAL_OPENAI_MODEL", "gpt-5.6-sol"),
    memory_strategy: Annotated[
        str,
        typer.Option("--memory", help="event_retrieval、recent_only 或 none。"),
    ] = "event_retrieval",
) -> None:
    """新建并运行一次模拟。"""
    if policy not in {"heuristic", "scripted", "llm"}:
        raise typer.BadParameter("policy 必须是 heuristic、scripted 或 llm")
    if memory_strategy not in {"event_retrieval", "recent_only", "none"}:
        raise typer.BadParameter(
            "memory 必须是 event_retrieval、recent_only 或 none"
        )
    bundle = load_scenario(scenario)
    repository = SQLiteRepository(database)
    engine = SimulationEngine(bundle, repository)
    run_id = engine.create_run(
        RunConfig(
            scenario_id=bundle.scenario.id,
            seed=seed,
            policy=policy,
            model=model,
            memory_strategy=memory_strategy,
        )
    )
    records = engine.run(run_id, rounds=rounds)
    state = repository.get_state(run_id)
    console.print(
        Panel.fit(
            f"[bold cyan]{run_id}[/bold cyan]\n"
            f"已推进 {len(records)} 轮｜当前第 {state.round_no} 轮｜"
            f"状态 [bold]{state.status.value}[/bold]\n"
            f"状态摘要 {state.state_digest()}",
            title="运行完成",
        )
    )
    console.print(f"继续：astral resume {run_id}")
    console.print(f"回放：astral replay {run_id}")


@app.command()
def step(
    run_id: str,
    scenario: ScenarioOption = DEFAULT_SCENARIO_DIR,
    database: DatabaseOption = Path("runs/astral.sqlite"),
) -> None:
    """从最近保存点单步推进一轮。"""
    engine = SimulationEngine(load_scenario(scenario), SQLiteRepository(database))
    record = engine.step(run_id)
    console.print(
        f"[green]第 {record.round_no} 轮已提交[/green] · "
        f"{len(record.events)} 个事件 · {len(record.diffs)} 项状态变化 · "
        f"{record.duration_ms} ms"
    )


@app.command()
def resume(
    run_id: str,
    scenario: ScenarioOption = DEFAULT_SCENARIO_DIR,
    database: DatabaseOption = Path("runs/astral.sqlite"),
    rounds: Annotated[
        Optional[int],
        typer.Option("--rounds", help="继续轮数；默认运行到终局。"),
    ] = None,
) -> None:
    """恢复已有运行。"""
    repository = SQLiteRepository(database)
    engine = SimulationEngine(load_scenario(scenario), repository)
    records = engine.run(run_id, rounds=rounds)
    state = repository.get_state(run_id)
    console.print(
        f"[green]恢复完成[/green] · 新推进 {len(records)} 轮 · "
        f"第 {state.round_no} 轮 · {state.status.value}"
    )


@app.command()
def replay(
    run_id: str,
    scenario: ScenarioOption = DEFAULT_SCENARIO_DIR,
    database: DatabaseOption = Path("runs/astral.sqlite"),
) -> None:
    """从轮 0 快照重放已确认事件并校验摘要。"""
    engine = SimulationEngine(load_scenario(scenario), SQLiteRepository(database))
    result = engine.replay(run_id)
    color = "green" if result.matched else "red"
    console.print(
        Panel.fit(
            f"[{color}]{'回放一致' if result.matched else '回放不一致'}[/{color}]\n"
            f"轮数：{result.rounds_replayed}\n"
            f"保存摘要：{result.expected_digest}\n"
            f"回放摘要：{result.actual_digest}\n"
            f"保存时间线：{result.expected_timeline_hash}\n"
            f"回放时间线：{result.actual_timeline_hash}\n"
            f"事件双写一致：{'是' if result.event_sources_consistent else '否'}",
            title="Deterministic replay",
        )
    )
    if not result.matched:
        raise typer.Exit(code=2)


@app.command()
def inspect(
    run_id: str,
    character: Annotated[
        Optional[str],
        typer.Option("--character", "-c", help="仅查看该角色有权限读取的视角。"),
    ] = None,
    round_no: Annotated[
        Optional[int],
        typer.Option("--round", "-r", help="查看指定轮次；默认当前轮。"),
    ] = None,
    scenario: ScenarioOption = DEFAULT_SCENARIO_DIR,
    database: DatabaseOption = Path("runs/astral.sqlite"),
) -> None:
    """检查公开世界状态，或安全查看一个角色的独立视角。"""
    bundle = load_scenario(scenario)
    repository = SQLiteRepository(database)
    latest = repository.get_state(run_id)
    selected_round = latest.round_no if round_no is None else round_no
    state = repository.get_state_at_round(run_id, selected_round)
    if character:
        if character not in bundle.character_map:
            raise typer.BadParameter(f"未知角色：{character}")
        decision_state = (
            repository.get_round(run_id, selected_round).state_before
            if selected_round
            else state
        )
        events = repository.get_events(
            run_id, end_round=decision_state.round_no
        )
        observation = build_observation(
            character, decision_state, events, bundle
        )
        memories = [
            memory
            for memory in repository.get_memories(run_id, character)
            if memory.created_round <= decision_state.round_no
        ]
        perspective_label = (
            f"第 {selected_round} 轮行动前"
            if selected_round
            else "轮 0 初始简报后"
        )
        console.print(
            Panel(
                json.dumps(
                    {
                        "observation": observation.model_dump(mode="json"),
                        "memories": [
                            memory.model_dump(mode="json") for memory in memories[:8]
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                title=(
                    f"{bundle.character_map[character].display_name} · "
                    f"{perspective_label}视角"
                ),
            )
        )
        return
    table = Table(title=f"第 {selected_round} 轮公开状态")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("阶段", state.phase)
    table.add_row("状态", state.status.value)
    table.add_row("资源", json.dumps(state.resources, ensure_ascii=False))
    table.add_row("开放悬念", ", ".join(state.open_threads) or "无")
    table.add_row("状态摘要", state.state_digest())
    console.print(table)


@app.command("export")
def export_command(
    run_id: str,
    database: DatabaseOption = Path("runs/astral.sqlite"),
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="输出 ZIP 路径。"),
    ] = None,
    include_private: Annotated[
        bool,
        typer.Option(
            "--include-private",
            help="导出完整研究 trace（会包含私密记忆与决策理由）。",
        ),
    ] = False,
) -> None:
    """导出默认脱敏的演示包。"""
    target = output or Path("exports") / f"{run_id}.zip"
    path = write_demo_archive(
        SQLiteRepository(database),
        run_id,
        target,
        include_private=include_private,
    )
    privacy = "完整研究 trace" if include_private else "脱敏演示包"
    console.print(f"[green]已导出 {privacy}[/green]：{path}")


@app.command()
def metrics(
    run_id: str,
    database: DatabaseOption = Path("runs/astral.sqlite"),
) -> None:
    """输出运行评测指标。"""
    result = evaluate_run(SQLiteRepository(database), run_id)
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command()
def ui(
    database: DatabaseOption = Path("runs/astral.sqlite"),
) -> None:
    """启动 Streamlit 叙事观测台。"""
    app_path = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"
    env = os.environ.copy()
    env["ASTRAL_DATABASE"] = str(database.resolve())
    raise typer.Exit(
        subprocess.call(
            [sys.executable, "-m", "streamlit", "run", str(app_path)],
            env=env,
        )
    )


if __name__ == "__main__":
    app()
