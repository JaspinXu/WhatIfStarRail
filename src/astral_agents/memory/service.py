from __future__ import annotations

import re
from collections import defaultdict

from astral_agents.domain.models import (
    Belief,
    CanonicalEvent,
    CharacterProfile,
    Memory,
    MemoryKind,
    ObservationPacket,
    RetrievalHit,
    ScenarioBundle,
    Visibility,
)
from astral_agents.storage.repository import SQLiteRepository


class MemoryService:
    def __init__(self, repository: SQLiteRepository) -> None:
        self.repository = repository

    def form_memories(
        self,
        run_id: str,
        events: list[CanonicalEvent],
        bundle: ScenarioBundle,
    ) -> tuple[list[Memory], list[Belief]]:
        memories: list[Memory] = []
        beliefs: list[Belief] = []
        all_character_ids = set(bundle.character_map)

        for event in events:
            recipients = set(event.observers) | set(event.participants)
            if "public" in event.tags:
                recipients |= all_character_ids
            recipients |= set(event.private_payloads)
            for owner_id in sorted(recipients):
                if owner_id not in all_character_ids:
                    continue
                parts: list[str] = []
                if event.public_summary:
                    parts.append(event.public_summary)
                if owner_id in event.private_payloads:
                    parts.append(event.private_payloads[owner_id])
                if not parts:
                    continue
                visibility = (
                    Visibility.PRIVATE
                    if owner_id in event.private_payloads
                    else Visibility.PUBLIC
                    if "public" in event.tags
                    else Visibility.SHARED
                )
                memory_id = f"M-{owner_id}-{event.id}"
                memories.append(
                    Memory(
                        id=memory_id,
                        owner_id=owner_id,
                        kind=MemoryKind.EPISODIC,
                        content=" ".join(parts),
                        source_event_ids=[event.id],
                        salience=_event_salience(event),
                        emotional_valence=_event_valence(event),
                        visibility=visibility,
                        created_round=event.round_no,
                        tags=sorted(
                            set(event.tags)
                            | set(event.participants)
                            | {event.event_type}
                        ),
                    )
                )

                for clue_id in set(event.tags) & set(bundle.scenario.clue_map):
                    beliefs.append(
                        Belief(
                            id=f"B-{owner_id}-{clue_id}",
                            owner_id=owner_id,
                            proposition=bundle.scenario.clue_map[clue_id].public_summary,
                            confidence=0.92 if owner_id in event.private_payloads else 0.78,
                            stance="believes",
                            source_event_ids=[event.id],
                            last_updated_round=event.round_no,
                        )
                    )
        return memories, beliefs

    def initial_private_memories(
        self,
        opening_events: list[CanonicalEvent],
        bundle: ScenarioBundle,
    ) -> list[Memory]:
        """Seed each canary only into its owner's private memory collection."""
        private_event_by_owner = {
            owner_id: event.id
            for event in opening_events
            for owner_id in event.private_payloads
        }
        memories: list[Memory] = []
        for character in bundle.characters:
            source_id = private_event_by_owner.get(character.id)
            if source_id is None:
                continue
            for fact in character.private_facts:
                content = fact.content
                if fact.canary:
                    content += (
                        f" 内部边界审计标记：{fact.canary}。"
                        "该标记不是场景事实，禁止在行动或对话中复述。"
                    )
                memories.append(
                    Memory(
                        id=f"M-{character.id}-private-{fact.id}",
                        owner_id=character.id,
                        kind=MemoryKind.SEMANTIC,
                        content=content,
                        source_event_ids=[source_id],
                        salience=0.95,
                        emotional_valence=0,
                        visibility=Visibility.PRIVATE,
                        created_round=0,
                        tags=sorted(set(fact.tags) | {"private_fact", "canary_guard"}),
                    )
                )
        return memories

    def retrieve(
        self,
        run_id: str,
        profile: CharacterProfile,
        observation: ObservationPacket,
        strategy: str,
        *,
        limit: int = 5,
    ) -> tuple[list[Memory], list[RetrievalHit]]:
        if strategy == "none":
            return [], []
        candidates = self.repository.get_memories(run_id, profile.id)
        if not candidates:
            return [], []
        if strategy == "recent_only":
            selected = candidates[:limit]
            return selected, [
                RetrievalHit(
                    memory_id=memory.id,
                    score=round(1 - rank * 0.05, 4),
                    relevance=0,
                    goal_match=0,
                    salience=memory.salience,
                    recency=max(
                        0,
                        1 - (observation.round_no - memory.created_round) / 20,
                    ),
                    relationship_match=0,
                )
                for rank, memory in enumerate(selected)
            ]

        query = " ".join(
            [
                observation.current_location,
                *observation.open_threads,
                *observation.known_clue_ids,
                *(goal.description for goal in observation.active_goals),
            ]
        )
        fts_ids = self.repository.search_memory_ids(
            run_id, profile.id, query, limit=max(20, limit * 3)
        )
        if fts_ids:
            by_id = {memory.id: memory for memory in candidates}
            recalled = [by_id[memory_id] for memory_id in fts_ids if memory_id in by_id]
            recent = [memory for memory in candidates[:limit] if memory.id not in fts_ids]
            candidates = [*recalled, *recent]
        query_terms = _terms(query)
        goal_terms = _terms(" ".join(goal.description for goal in observation.active_goals))
        visible_people = set(observation.visible_characters)
        scored: list[tuple[float, Memory, RetrievalHit]] = []
        for memory in candidates:
            memory_terms = _terms(f"{memory.content} {' '.join(memory.tags)}")
            relevance = _overlap(query_terms, memory_terms)
            goal_match = _overlap(goal_terms, memory_terms)
            recency = 1 / (1 + max(0, observation.round_no - memory.created_round) / 5)
            relationship = 1.0 if visible_people & set(memory.tags) else 0.0
            score = (
                0.35 * relevance
                + 0.25 * goal_match
                + 0.20 * memory.salience
                + 0.10 * recency
                + 0.10 * relationship
            )
            hit = RetrievalHit(
                memory_id=memory.id,
                score=round(score, 4),
                relevance=round(relevance, 4),
                goal_match=round(goal_match, 4),
                salience=memory.salience,
                recency=round(recency, 4),
                relationship_match=relationship,
            )
            scored.append((score, memory, hit))
        scored.sort(key=lambda item: (-item[0], -item[1].created_round, item[1].id))
        selected = scored[:limit]
        return [item[1] for item in selected], [item[2] for item in selected]


def _terms(text: str) -> set[str]:
    ascii_words = {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9_]{2,}", text)
        if word
    }
    chinese_chunks = set(re.findall(r"[\u4e00-\u9fff]{2,6}", text))
    return ascii_words | chinese_chunks


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    direct = len(left & right)
    fuzzy = sum(
        1
        for item in left - right
        if any(item in candidate or candidate in item for candidate in right)
    )
    return min(1.0, (direct + 0.5 * fuzzy) / max(1, len(left)))


def _event_salience(event: CanonicalEvent) -> float:
    weights = defaultdict(
        lambda: 0.48,
        {
            "clue_discovered": 0.88,
            "clue_shared": 0.84,
            "resolution": 1.0,
            "scenario_opened": 0.75,
            "action_rejected": 0.72,
        },
    )
    return weights[event.event_type]


def _event_valence(event: CanonicalEvent) -> float:
    if event.event_type == "resolution":
        return 0.85
    if event.event_type in {"system_decay", "action_rejected"}:
        return -0.35
    return 0.05
