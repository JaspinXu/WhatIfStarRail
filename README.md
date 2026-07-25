# Palace Narrative Agents

LLM-driven multi-agent narrative simulation for a historical-fantasy palace world.

The prototype will model character agents with private memories, goals, beliefs, personalities, and evolving relationships. Agents act in repeated rounds inside a shared fictional world; a simulation engine adjudicates actions, updates canonical state, checks continuity and information boundaries, and turns confirmed events into narrative episodes.

## Planned MVP

- 4–6 character agents over at least 20 rounds
- Private memory, beliefs, goals, and visibility-filtered observations
- Structured world state, canonical event log, and atomic state updates
- Leakage, consistency, memory, coherence, cost, and latency evaluation
- Reproducible CLI experiments and an optional Streamlit trace viewer

See [the Chinese implementation plan](docs/implementation_plan.zh-CN.md) for architecture, data models, milestones, evaluation, risks, and acceptance criteria.

## Status

Research prototype — planning and scaffolding.
