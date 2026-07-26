# Prototype Experiment Report

## Baseline

- Scenario: `sealed_transport` / 静默航线
- Configuration: offline heuristic policy, event retrieval memory
- Seed: `42`
- Expected terminal round: `10`
- Expected terminal state: `succeeded`
- Expected episodes: `4`

## Automated acceptance result

The integration suite verifies the following baseline properties:

| Property | Expected |
|---|---|
| Schema and cross-reference validation | Pass |
| Completed rounds | 10 |
| Terminal status | Succeeded |
| Open scenario threads | 0 |
| Narrative episodes | 4 |
| Critical findings | 0 |
| Leakage findings | 0 |
| Evidence ID validity | 100% |
| Narrative event coverage | 100% |
| Replay state digest + timeline hash | Exact match |
| Event table vs round-record event copies | Exact match |
| Seeded private-memory canaries | Owner-only; all action fields scanned |
| Canary-blocked sanitized export | Model-authored fields redacted |
| Pause/resume vs continuous run | Exact match |

Exact state digests are intentionally computed at runtime because they should change when an authorized schema, scenario or reducer revision changes. Regression tests compare equivalent runs created from the same revision rather than pinning a stale digest across intentional migrations.

## What this prototype establishes

The prototype demonstrates that:

1. owner-filtered observations can be enforced before decision generation;
2. private memory can retain source event IDs and affect later action evidence;
3. simultaneous intents can be normalized into canonical events;
4. a white-listed reducer can keep world state valid and replayable;
5. narrative chapters can remain a read-only view of confirmed events;
6. a usable research trace viewer does not require the LLM provider to be online.

## What it does not yet establish

- Human-rated long-horizon character fidelity across many scenarios
- Statistical comparison across model providers and memory strategies
- Semantic leakage detection beyond explicit canaries and evidence permissions
- Production concurrency, migrations or remote deployment
- Literary quality of model-written long-form chapters
- Authorization required for any commercial or public fan product

Those are follow-up research items, not hidden claims of the prototype.
