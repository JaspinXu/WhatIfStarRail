# Astral Narrative Agents

An LLM-driven multi-agent narrative simulation research prototype based on publicly released *Honkai: Star Rail* character settings.

The project models multiple character agents with isolated memories, goals, beliefs, private information, and evolving relationships. Agents interact in repeated rounds inside an original closed scenario. A simulation engine filters observations, adjudicates actions, applies deterministic world-state updates, checks continuity and information boundaries, and turns confirmed events into narrative episodes.

## Research Questions

- Can character agents remain behaviorally consistent across long simulations?
- Can private memory and evidence-based knowledge tracking reduce information leakage?
- Which memory strategy best balances recall, consistency, latency, and cost?
- Can event-sourced simulation produce more coherent narratives than unconstrained group chat?

## Planned MVP

- 4–6 configurable character agents over 20–30 rounds
- Separate canon facts, scenario truth, and character beliefs
- Private episodic, semantic, relationship, and goal memories
- Permission-filtered observations and evidence-linked decisions
- Canonical event log and deterministic state reducer
- Continuity, leakage, memory, coherence, cost, and latency evaluation
- Reproducible CLI experiments and a Streamlit trace viewer

## Recommended Stack

Python, Pydantic, LangGraph, SQLite/FTS5, FastAPI, Streamlit, and Arize Phoenix.

See the [Chinese technical roadmap](docs/implementation_plan.zh-CN.md) for the complete architecture, data models, round workflow, implementation phases, evaluation plan, risks, and acceptance criteria.

## Disclaimer

This is an unofficial, non-commercial research and fan prototype. It is not affiliated with or endorsed by HoYoverse. *Honkai: Star Rail* and its characters and setting belong to their respective rights holders. Generated scenarios are not official story content.

The project should use only publicly released, verifiable setting information and must not redistribute game scripts, voice assets, character models, CG, leaked material, or other official assets.

## Status

Planning and scaffolding.
