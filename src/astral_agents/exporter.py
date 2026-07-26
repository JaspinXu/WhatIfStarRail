from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from astral_agents.evaluation.metrics import evaluate_run
from astral_agents.storage.repository import SQLiteRepository

DISCLAIMER = (
    "本项目为非官方、非商业的研究与同人原型，与 HoYoverse 无隶属或授权关系。"
    "《崩坏：星穹铁道》及其角色和世界观相关权利归相应权利人所有；"
    "系统生成的原创事件和章节不属于官方剧情。"
)


def build_export_payload(
    repository: SQLiteRepository,
    run_id: str,
    *,
    include_private: bool = False,
) -> dict[str, Any]:
    manifest = repository.get_manifest(run_id)
    state = repository.get_state(run_id)
    events = repository.get_events(run_id)
    rounds = repository.get_rounds(run_id)
    episodes = repository.get_episodes(run_id)
    findings = repository.get_findings(run_id)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "disclaimer": DISCLAIMER,
        "privacy": "full_research_trace" if include_private else "sanitized_demo",
        "manifest": manifest.model_dump(mode="json"),
        "final_state": (
            state.model_dump(mode="json") if include_private else _public_state(state)
        ),
        "events": [
            (
                event.model_dump(mode="json")
                if include_private
                else {
                    **event.model_dump(mode="json", exclude={"private_payloads"}),
                    "private_payloads": {},
                }
            )
            for event in events
        ],
        "rounds": [
            (
                record.model_dump(mode="json")
                if include_private
                else {
                    "round_no": record.round_no,
                    "actions": [
                        _sanitized_action(
                            action,
                            canary_leak=any(
                                finding.code == "CANARY_LEAK"
                                and finding.actor_id == action.actor_id
                                for finding in record.findings
                            ),
                        )
                        for action in record.actions
                    ],
                    "event_ids": [event.id for event in record.events],
                    "diffs": [diff.model_dump(mode="json") for diff in record.diffs],
                    "findings": [
                        finding.model_dump(mode="json") for finding in record.findings
                    ],
                    "state_digest": record.state_after.state_digest(),
                    "episode_id": record.episode_id,
                    "duration_ms": record.duration_ms,
                }
            )
            for record in rounds
        ],
        "episodes": [episode.model_dump(mode="json") for episode in episodes],
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "metrics": evaluate_run(repository, run_id),
    }
    if include_private:
        payload["memories"] = [
            memory.model_dump(mode="json")
            for memory in repository.get_memories(run_id)
        ]
        payload["beliefs"] = [
            belief.model_dump(mode="json")
            for belief in repository.get_beliefs(run_id)
        ]
    return payload


def _sanitized_action(action: Any, *, canary_leak: bool) -> dict[str, Any]:
    if canary_leak:
        # Preserve the audit skeleton without publishing any model-authored
        # strings from an action that tripped the private-memory canary.
        return {
            "id": action.id,
            "actor_id": action.actor_id,
            "round_no": action.round_no,
            "action_type": action.action_type.value,
            "target_ids": [],
            "location_id": None,
            "public_content": None,
            "private_content": None,
            "intended_effects": [],
            "evidence_event_ids": [],
            "confidence": action.confidence,
            "redacted_due_to": "CANARY_LEAK",
        }
    return {
        **action.model_dump(
            mode="json",
            exclude={"private_content", "rationale"},
        ),
        "private_content": None,
    }


def build_demo_archive(
    repository: SQLiteRepository,
    run_id: str,
    *,
    include_private: bool = False,
) -> bytes:
    payload = build_export_payload(
        repository, run_id, include_private=include_private
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": payload["schema_version"],
                    "privacy": payload["privacy"],
                    "manifest": payload["manifest"],
                    "disclaimer": payload["disclaimer"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        archive.writestr(
            "events.jsonl",
            "\n".join(
                json.dumps(event, ensure_ascii=False, sort_keys=True)
                for event in payload["events"]
            ),
        )
        snapshots = repository.get_snapshots(run_id)
        archive.writestr(
            "world_snapshots.jsonl",
            "\n".join(
                json.dumps(
                    (
                        snapshot.model_dump(mode="json")
                        if include_private
                        else _public_state(snapshot)
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                for snapshot in snapshots
            ),
        )
        archive.writestr(
            "chapters.md",
            _chapters_markdown(payload["episodes"]),
        )
        archive.writestr("metrics.csv", _metrics_csv(payload["metrics"]))
        if include_private:
            archive.writestr(
                "private_trace.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        archive.writestr(
            "README.txt",
            "\n".join(
                [
                    "Astral Narrative Agents 演示导出",
                    "",
                    DISCLAIMER,
                    "",
                    f"隐私级别：{payload['privacy']}",
                    "events.jsonl：按顺序保存的已确认事件。",
                    "world_snapshots.jsonl：逐轮世界状态快照。",
                    "chapters.md：仅由已确认事件生成的章节视图。",
                    "metrics.csv：本次运行的自动评测指标。",
                    "",
                    "默认演示包不包含私密 payload、角色决策理由或私有记忆。",
                    "任何导出都不会保存 OPENAI_API_KEY。",
                ]
            ),
        )
    return buffer.getvalue()


def write_demo_archive(
    repository: SQLiteRepository,
    run_id: str,
    output: str | Path,
    *,
    include_private: bool = False,
) -> Path:
    path = Path(output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        build_demo_archive(
            repository,
            run_id,
            include_private=include_private,
        )
    )
    return path


def _public_state(state: Any) -> dict[str, Any]:
    return {
        "scenario_id": state.scenario_id,
        "round_no": state.round_no,
        "phase": state.phase,
        "status": state.status.value,
        "locations": state.locations,
        "resources": state.resources,
        "active_conflicts": state.active_conflicts,
        "open_threads": state.open_threads,
        "resolved_threads": state.resolved_threads,
        "shared_clue_ids": state.shared_clue_ids,
        "public_fact_ids": state.public_fact_ids,
        "state_digest": state.state_digest(),
        "timeline_hash": state.timeline_hash,
    }


def _chapters_markdown(episodes: list[dict[str, Any]]) -> str:
    lines = ["# 静默航线：叙事章节", "", f"> {DISCLAIMER}", ""]
    for episode in episodes:
        lines.extend(
            [
                f"## {episode['title']}",
                "",
                f"轮次：{episode['start_round']}–{episode['end_round']}  ",
                f"事件：{', '.join(episode['event_ids'])}",
                "",
                episode["body"],
                "",
            ]
        )
    return "\n".join(lines)


def _metrics_csv(metrics: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(metrics))
    writer.writeheader()
    writer.writerow(metrics)
    return buffer.getvalue()
