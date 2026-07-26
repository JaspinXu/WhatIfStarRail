from __future__ import annotations

from typing import Any

from astral_agents.domain.models import (
    CanonicalEvent,
    NarrativeEpisode,
    RoundRecord,
    ValidationFinding,
    WorldState,
)
from astral_agents.storage.repository import SQLiteRepository


def evaluate_run(repository: SQLiteRepository, run_id: str) -> dict[str, Any]:
    rounds = repository.get_rounds(run_id)
    events = repository.get_events(run_id)
    episodes = repository.get_episodes(run_id)
    findings = repository.get_findings(run_id)
    state = repository.get_state(run_id)
    return evaluate_trace(run_id, state, rounds, events, episodes, findings)


def evaluate_trace(
    run_id: str,
    state: WorldState,
    rounds: list[RoundRecord],
    events: list[CanonicalEvent],
    episodes: list[NarrativeEpisode],
    findings: list[ValidationFinding],
) -> dict[str, Any]:
    """Evaluate an already-loaded trace without repeating repository queries."""
    actions = [action for record in rounds for action in record.actions]
    model_calls = [trace for record in rounds for trace in record.model_calls]
    durations = sorted(record.duration_ms for record in rounds)
    evidence_actions = [action for action in actions if action.evidence_event_ids]
    cited_ids = {
        event_id for action in actions for event_id in action.evidence_event_ids
    }
    existing_ids = {event.id for event in events}
    covered_ids = {event_id for episode in episodes for event_id in episode.event_ids}
    narrative_candidates = {
        event.id
        for event in events
        if event.round_no > 0
        and event.public_summary
        and event.event_type not in {"character_waited", "system_decay"}
    }
    return {
        "run_id": run_id,
        "rounds": len(rounds),
        "actions": len(actions),
        "events": len(events),
        "episodes": len(episodes),
        "model_calls": len(model_calls),
        "input_tokens": sum(trace.input_tokens for trace in model_calls),
        "output_tokens": sum(trace.output_tokens for trace in model_calls),
        "round_latency_p50_ms": _percentile(durations, 0.50),
        "round_latency_p95_ms": _percentile(durations, 0.95),
        "critical_findings": sum(
            1 for finding in findings if finding.severity.value == "critical"
        ),
        "leakage_findings": sum(
            1 for finding in findings if finding.code in {"CANARY_LEAK", "INVISIBLE_EVIDENCE"}
        ),
        "evidence_citation_rate": round(
            len(evidence_actions) / len(actions), 4
        )
        if actions
        else 0,
        "evidence_validity_rate": round(
            len(cited_ids & existing_ids) / len(cited_ids), 4
        )
        if cited_ids
        else 1.0,
        "narrative_event_coverage": round(
            len(covered_ids & narrative_candidates) / len(narrative_candidates), 4
        )
        if narrative_candidates
        else 1.0,
        "final_state_digest": state.state_digest(),
        "timeline_hash": state.timeline_hash,
    }


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    index = round((len(values) - 1) * percentile)
    return values[index]
