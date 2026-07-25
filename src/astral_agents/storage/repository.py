from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from astral_agents.domain.models import (
    Belief,
    CanonicalEvent,
    Memory,
    NarrativeEpisode,
    RoundRecord,
    RunManifest,
    RunStatus,
    ValidationFinding,
    WorldState,
)


class RunNotFoundError(KeyError):
    """Raised when a run id does not exist in the selected database."""


class SQLiteRepository:
    def __init__(self, path: str | Path = "runs/astral.sqlite") -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_enabled = False
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL,
            seed INTEGER NOT NULL,
            policy TEXT NOT NULL,
            model TEXT NOT NULL,
            memory_strategy TEXT NOT NULL,
            status TEXT NOT NULL,
            current_round INTEGER NOT NULL,
            manifest_json TEXT NOT NULL,
            state_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rounds (
            run_id TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            record_json TEXT NOT NULL,
            state_digest TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            PRIMARY KEY (run_id, round_no),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS actions (
            run_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_json TEXT NOT NULL,
            PRIMARY KEY (run_id, action_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS events (
            run_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            public_summary TEXT,
            event_json TEXT NOT NULL,
            PRIMARY KEY (run_id, event_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS world_snapshots (
            run_id TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            state_digest TEXT NOT NULL,
            PRIMARY KEY (run_id, round_no),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memories (
            run_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            created_round INTEGER NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            tags_text TEXT NOT NULL,
            memory_json TEXT NOT NULL,
            PRIMARY KEY (run_id, memory_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS beliefs (
            run_id TEXT NOT NULL,
            belief_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            last_updated_round INTEGER NOT NULL,
            belief_json TEXT NOT NULL,
            PRIMARY KEY (run_id, belief_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS narrative_episodes (
            run_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            start_round INTEGER NOT NULL,
            end_round INTEGER NOT NULL,
            episode_json TEXT NOT NULL,
            PRIMARY KEY (run_id, episode_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS validation_findings (
            run_id TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            finding_index INTEGER NOT NULL,
            severity TEXT NOT NULL,
            finding_json TEXT NOT NULL,
            PRIMARY KEY (run_id, round_no, finding_index),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS retrieval_hits (
            run_id TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            owner_id TEXT NOT NULL,
            rank_no INTEGER NOT NULL,
            hit_json TEXT NOT NULL,
            PRIMARY KEY (run_id, round_no, owner_id, rank_no),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS model_calls (
            run_id TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            call_index INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            PRIMARY KEY (run_id, round_no, actor_id, call_index),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_events_run_round
            ON events(run_id, round_no);
        CREATE INDEX IF NOT EXISTS idx_memories_owner
            ON memories(run_id, owner_id, created_round);
        """
        with closing(self._connect()) as connection:
            connection.executescript(schema)
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        run_id UNINDEXED,
                        memory_id UNINDEXED,
                        owner_id UNINDEXED,
                        content,
                        tags
                    )
                    """
                )
                self.fts_enabled = True
            except sqlite3.OperationalError:
                self.fts_enabled = False
            connection.execute("PRAGMA user_version = 1")

    @staticmethod
    def _dump(model: Any) -> str:
        if hasattr(model, "model_dump"):
            payload = model.model_dump(mode="json")
        else:
            payload = model
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def create_run(
        self,
        manifest: RunManifest,
        state: WorldState,
        opening_events: list[CanonicalEvent],
        memories: list[Memory],
        beliefs: list[Belief],
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, scenario_id, seed, policy, model, memory_strategy,
                    status, current_round, manifest_json, state_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    manifest.scenario_id,
                    manifest.seed,
                    manifest.policy,
                    manifest.model,
                    manifest.memory_strategy,
                    state.status.value,
                    state.round_no,
                    self._dump(manifest),
                    self._dump(state),
                    manifest.created_at,
                ),
            )
            self._insert_events(connection, manifest.run_id, opening_events)
            self._insert_memories(connection, manifest.run_id, memories)
            self._upsert_beliefs(connection, manifest.run_id, beliefs)
            connection.execute(
                """
                INSERT INTO world_snapshots(run_id, round_no, state_json, state_digest)
                VALUES (?, ?, ?, ?)
                """,
                (manifest.run_id, 0, self._dump(state), state.state_digest()),
            )

    def commit_round(
        self,
        record: RoundRecord,
        memories: list[Memory],
        beliefs: list[Belief],
        episode: NarrativeEpisode | None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO rounds(run_id, round_no, record_json, state_digest, duration_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.round_no,
                    self._dump(record),
                    record.state_after.state_digest(),
                    record.duration_ms,
                ),
            )
            for action in record.actions:
                connection.execute(
                    """
                    INSERT INTO actions(
                        run_id, action_id, round_no, actor_id, action_type, action_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        action.id,
                        action.round_no,
                        action.actor_id,
                        action.action_type.value,
                        self._dump(action),
                    ),
                )
            self._insert_events(connection, record.run_id, record.events)
            self._insert_memories(connection, record.run_id, memories)
            self._upsert_beliefs(connection, record.run_id, beliefs)
            for index, finding in enumerate(record.findings):
                connection.execute(
                    """
                    INSERT INTO validation_findings(
                        run_id, round_no, finding_index, severity, finding_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        record.round_no,
                        index,
                        finding.severity.value,
                        self._dump(finding),
                    ),
                )
            for owner_id, hits in record.retrievals.items():
                for rank, hit in enumerate(hits, start=1):
                    connection.execute(
                        """
                        INSERT INTO retrieval_hits(
                            run_id, round_no, owner_id, rank_no, hit_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            record.run_id,
                            record.round_no,
                            owner_id,
                            rank,
                            self._dump(hit),
                        ),
                    )
            actor_call_counts: dict[str, int] = {}
            for trace in record.model_calls:
                call_index = actor_call_counts.get(trace.actor_id, 0) + 1
                actor_call_counts[trace.actor_id] = call_index
                connection.execute(
                    """
                    INSERT INTO model_calls(
                        run_id, round_no, actor_id, call_index,
                        provider, model, trace_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        record.round_no,
                        trace.actor_id,
                        call_index,
                        trace.provider,
                        trace.model,
                        self._dump(trace),
                    ),
                )
            if episode:
                connection.execute(
                    """
                    INSERT INTO narrative_episodes(
                        run_id, episode_id, start_round, end_round, episode_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        episode.id,
                        episode.start_round,
                        episode.end_round,
                        self._dump(episode),
                    ),
                )
            connection.execute(
                """
                INSERT INTO world_snapshots(run_id, round_no, state_json, state_digest)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.round_no,
                    self._dump(record.state_after),
                    record.state_after.state_digest(),
                ),
            )
            result = connection.execute(
                """
                UPDATE runs
                SET status = ?, current_round = ?, state_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = ?
                """,
                (
                    record.state_after.status.value,
                    record.round_no,
                    self._dump(record.state_after),
                    record.run_id,
                ),
            )
            if result.rowcount != 1:
                raise RunNotFoundError(record.run_id)

    def _insert_events(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        events: list[CanonicalEvent],
    ) -> None:
        for event in events:
            connection.execute(
                """
                INSERT INTO events(
                    run_id, event_id, round_no, event_type, public_summary, event_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    event.id,
                    event.round_no,
                    event.event_type,
                    event.public_summary,
                    self._dump(event),
                ),
            )

    def _insert_memories(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        memories: list[Memory],
    ) -> None:
        for memory in memories:
            tags_text = " ".join(memory.tags)
            connection.execute(
                """
                INSERT INTO memories(
                    run_id, memory_id, owner_id, created_round, kind,
                    content, tags_text, memory_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    memory.id,
                    memory.owner_id,
                    memory.created_round,
                    memory.kind.value,
                    memory.content,
                    tags_text,
                    self._dump(memory),
                ),
            )
            if self.fts_enabled:
                connection.execute(
                    """
                    INSERT INTO memories_fts(
                        run_id, memory_id, owner_id, content, tags
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (run_id, memory.id, memory.owner_id, memory.content, tags_text),
                )

    def _upsert_beliefs(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        beliefs: list[Belief],
    ) -> None:
        for belief in beliefs:
            connection.execute(
                """
                INSERT INTO beliefs(
                    run_id, belief_id, owner_id, last_updated_round, belief_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, belief_id) DO UPDATE SET
                    last_updated_round = excluded.last_updated_round,
                    belief_json = excluded.belief_json
                """,
                (
                    run_id,
                    belief.id,
                    belief.owner_id,
                    belief.last_updated_round,
                    self._dump(belief),
                ),
            )

    def get_manifest(self, run_id: str) -> RunManifest:
        row = self._one("SELECT manifest_json FROM runs WHERE run_id = ?", (run_id,))
        return RunManifest.model_validate_json(row["manifest_json"])

    def get_state(self, run_id: str) -> WorldState:
        row = self._one("SELECT state_json FROM runs WHERE run_id = ?", (run_id,))
        return WorldState.model_validate_json(row["state_json"])

    def get_state_at_round(self, run_id: str, round_no: int) -> WorldState:
        row = self._one(
            """
            SELECT state_json FROM world_snapshots
            WHERE run_id = ? AND round_no = ?
            """,
            (run_id, round_no),
        )
        return WorldState.model_validate_json(row["state_json"])

    def get_events(
        self,
        run_id: str,
        *,
        start_round: int = 0,
        end_round: int | None = None,
    ) -> list[CanonicalEvent]:
        sql = "SELECT event_json FROM events WHERE run_id = ? AND round_no >= ?"
        params: list[Any] = [run_id, start_round]
        if end_round is not None:
            sql += " AND round_no <= ?"
            params.append(end_round)
        sql += " ORDER BY round_no, event_id"
        return [
            CanonicalEvent.model_validate_json(row["event_json"])
            for row in self._all(sql, tuple(params))
        ]

    def get_rounds(self, run_id: str) -> list[RoundRecord]:
        return [
            RoundRecord.model_validate_json(row["record_json"])
            for row in self._all(
                "SELECT record_json FROM rounds WHERE run_id = ? ORDER BY round_no",
                (run_id,),
            )
        ]

    def get_round(self, run_id: str, round_no: int) -> RoundRecord:
        row = self._one(
            "SELECT record_json FROM rounds WHERE run_id = ? AND round_no = ?",
            (run_id, round_no),
        )
        return RoundRecord.model_validate_json(row["record_json"])

    def get_snapshots(self, run_id: str) -> list[WorldState]:
        return [
            WorldState.model_validate_json(row["state_json"])
            for row in self._all(
                """
                SELECT state_json FROM world_snapshots
                WHERE run_id = ? ORDER BY round_no
                """,
                (run_id,),
            )
        ]

    def get_memories(self, run_id: str, owner_id: str | None = None) -> list[Memory]:
        sql = "SELECT memory_json FROM memories WHERE run_id = ?"
        params: tuple[Any, ...] = (run_id,)
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params = (run_id, owner_id)
        sql += " ORDER BY created_round DESC, memory_id"
        return [
            Memory.model_validate_json(row["memory_json"])
            for row in self._all(sql, params)
        ]

    def search_memory_ids(
        self,
        run_id: str,
        owner_id: str,
        query: str,
        *,
        limit: int = 20,
    ) -> list[str]:
        """Return owner-scoped FTS candidates; an empty list is a safe fallback."""
        if not self.fts_enabled:
            return []
        tokens = list(
            dict.fromkeys(
                token.lower()
                for token in re.findall(r"[A-Za-z0-9_]{2,}", query)
            )
        )[:12]
        if not tokens:
            return []
        match_query = " OR ".join(f'"{token}"' for token in tokens)
        try:
            rows = self._all(
                """
                SELECT memory_id
                FROM memories_fts
                WHERE memories_fts MATCH ? AND run_id = ? AND owner_id = ?
                ORDER BY bm25(memories_fts)
                LIMIT ?
                """,
                (match_query, run_id, owner_id, limit),
            )
        except sqlite3.OperationalError:
            return []
        return [str(row["memory_id"]) for row in rows]

    def get_beliefs(self, run_id: str, owner_id: str | None = None) -> list[Belief]:
        sql = "SELECT belief_json FROM beliefs WHERE run_id = ?"
        params: tuple[Any, ...] = (run_id,)
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params = (run_id, owner_id)
        sql += " ORDER BY owner_id, belief_id"
        return [
            Belief.model_validate_json(row["belief_json"])
            for row in self._all(sql, params)
        ]

    def get_episodes(self, run_id: str) -> list[NarrativeEpisode]:
        return [
            NarrativeEpisode.model_validate_json(row["episode_json"])
            for row in self._all(
                """
                SELECT episode_json FROM narrative_episodes
                WHERE run_id = ? ORDER BY start_round
                """,
                (run_id,),
            )
        ]

    def get_findings(self, run_id: str) -> list[ValidationFinding]:
        return [
            ValidationFinding.model_validate_json(row["finding_json"])
            for row in self._all(
                """
                SELECT finding_json FROM validation_findings
                WHERE run_id = ? ORDER BY round_no, finding_index
                """,
                (run_id,),
            )
        ]

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._all(
            """
            SELECT run_id, scenario_id, seed, policy, model, memory_strategy,
                   status, current_round, created_at, updated_at
            FROM runs ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def _one(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Row:
        with closing(self._connect()) as connection:
            row = connection.execute(sql, params).fetchone()
        if row is None:
            raise RunNotFoundError(params[0] if params else "unknown")
        return row

    def _all(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            return list(connection.execute(sql, params).fetchall())

    def update_status(self, run_id: str, status: RunStatus) -> None:
        with self.transaction() as connection:
            result = connection.execute(
                "UPDATE runs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
                (status.value, run_id),
            )
            if result.rowcount != 1:
                raise RunNotFoundError(run_id)
            row = connection.execute(
                "SELECT state_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            state = WorldState.model_validate_json(row["state_json"])
            state.status = status
            connection.execute(
                "UPDATE runs SET state_json = ? WHERE run_id = ?",
                (self._dump(state), run_id),
            )
