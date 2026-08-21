from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .lifecycle import legacy_campaign_flags
from .paths import database_path
from .store_migration_support import StoreMigrationError
from .store_migrations import migrate_store
from .util import epoch_now, json_dumps, json_loads_or, new_campaign_id, new_id, utc_now


CAMPAIGN_JSON_FIELDS = {
    "authorized_scope",
    "memory_paths",
    "tags",
    "requested_routing",
    "resolved_routing",
    "model_catalog_snapshot",
    "routing_warnings",
}
EPISODE_JSON_FIELDS = {
    "handoff",
    "routing_snapshot",
    "agent_activity",
    "model_events",
    "token_usage",
}

CAMPAIGN_WITH_EPISODE_STATE = """
SELECT
    c.*,
    (SELECT COUNT(*) FROM episodes AS counted WHERE counted.campaign_id = c.id)
        AS derived_episode_count,
    (
        SELECT active.id
        FROM episodes AS active
        WHERE active.campaign_id = c.id
          AND active.ended_at IS NULL
          AND active.status IN ('queued', 'running')
        ORDER BY active.number DESC
        LIMIT 1
    ) AS derived_active_episode_id
FROM campaigns AS c
"""


class StoreError(RuntimeError):
    pass


class CampaignNotFound(StoreError):
    pass


class CampaignNotRunnable(StoreError):
    pass


class StoreCore:
    """Small SQLite-backed campaign store shared by Desktop, CLI, and workers."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or database_path()).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _initialize(self) -> None:
        with self.connection() as conn:
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:
                # Some cross-filesystem WSL mounts do not support WAL cleanly.
                conn.execute("PRAGMA journal_mode = DELETE")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    task_profile TEXT NOT NULL DEFAULT 'adaptive',
                    workspace TEXT NOT NULL,
                    authorized_scope TEXT NOT NULL,
                    success_criteria TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued' CHECK (
                        status IN (
                            'queued', 'planning', 'running',
                            'pausing_after_current', 'stopping_after_current',
                            'paused', 'stopped', 'stopped_budget', 'needs_input',
                            'completed', 'error'
                        )
                    ),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    stop_after_current INTEGER NOT NULL DEFAULT 0,
                    termination_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    active_episode_id TEXT,
                    last_thread_id TEXT,
                    model TEXT,
                    effort TEXT,
                    model_policy TEXT NOT NULL DEFAULT 'inherit',
                    model_validation TEXT NOT NULL DEFAULT 'fallback',
                    allow_child_ultra INTEGER NOT NULL DEFAULT 0,
                    allow_parent_ultra INTEGER NOT NULL DEFAULT 0,
                    requested_routing TEXT NOT NULL DEFAULT '{}',
                    resolved_routing TEXT NOT NULL DEFAULT '{}',
                    model_catalog_snapshot TEXT NOT NULL DEFAULT '[]',
                    routing_warnings TEXT NOT NULL DEFAULT '[]',
                    sandbox TEXT NOT NULL DEFAULT 'read-only',
                    allow_network INTEGER NOT NULL DEFAULT 0,
                    max_episodes INTEGER NOT NULL DEFAULT 20,
                    max_elapsed_minutes INTEGER NOT NULL DEFAULT 480,
                    continuation_threshold REAL NOT NULL DEFAULT 0.55,
                    max_low_progress INTEGER NOT NULL DEFAULT 2,
                    low_progress_count INTEGER NOT NULL DEFAULT 0,
                    max_subagents INTEGER NOT NULL DEFAULT 2,
                    memory_paths TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    episode_count INTEGER NOT NULL DEFAULT 0,
                    controller_pid INTEGER,
                    lease_token TEXT,
                    lease_expires_at REAL,
                    user_guidance TEXT NOT NULL DEFAULT '',
                    last_error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_campaigns_status
                    ON campaigns(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_campaigns_name
                    ON campaigns(name);

                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL,
                    objective TEXT NOT NULL,
                    task_profile_hint TEXT,
                    task_profile_used TEXT,
                    strategy_hint TEXT,
                    strategy_used TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    thread_id TEXT,
                    turn_id TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    prompt_path TEXT,
                    events_path TEXT,
                    final_path TEXT,
                    handoff_path TEXT,
                    final_text TEXT,
                    handoff TEXT,
                    routing_snapshot TEXT,
                    agent_activity TEXT,
                    model_events TEXT,
                    token_usage TEXT,
                    turn_status TEXT,
                    progress_score REAL,
                    expected_next_value REAL,
                    error TEXT,
                    UNIQUE(campaign_id, number)
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_campaign
                    ON episodes(campaign_id, number DESC);
                """
            )
            # In-place upgrade path for databases created by JAM 0.1.x.
            self._ensure_column(
                conn, "campaigns", "task_profile", "TEXT NOT NULL DEFAULT 'adaptive'"
            )
            self._ensure_column(conn, "episodes", "task_profile_hint", "TEXT")
            self._ensure_column(conn, "episodes", "task_profile_used", "TEXT")
            # In-place upgrade path for JAM 0.3 model-routing additions.
            self._ensure_column(
                conn, "campaigns", "model_policy", "TEXT NOT NULL DEFAULT 'inherit'"
            )
            self._ensure_column(
                conn, "campaigns", "model_validation", "TEXT NOT NULL DEFAULT 'fallback'"
            )
            self._ensure_column(
                conn, "campaigns", "allow_child_ultra", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                conn, "campaigns", "allow_parent_ultra", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                conn, "campaigns", "requested_routing", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._ensure_column(
                conn, "campaigns", "resolved_routing", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._ensure_column(
                conn, "campaigns", "model_catalog_snapshot", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(
                conn, "campaigns", "routing_warnings", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(conn, "episodes", "routing_snapshot", "TEXT")
            self._ensure_column(conn, "episodes", "agent_activity", "TEXT")
            self._ensure_column(conn, "episodes", "model_events", "TEXT")
            self._ensure_column(conn, "episodes", "token_usage", "TEXT")
            try:
                migrate_store(conn)
            except StoreMigrationError as exc:
                raise StoreError(str(exc)) from exc

    @staticmethod
    def _campaign_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        if "derived_episode_count" in data:
            data["episode_count"] = int(data.pop("derived_episode_count"))
        if "derived_active_episode_id" in data:
            data["active_episode_id"] = data.pop("derived_active_episode_id")
        object_fields = {"authorized_scope", "requested_routing", "resolved_routing"}
        for key in CAMPAIGN_JSON_FIELDS:
            data[key] = json_loads_or(data.get(key), {} if key in object_fields else [])
        for key in (
            "allow_network",
            "allow_child_ultra",
            "allow_parent_ultra",
        ):
            data[key] = bool(data.get(key))
        data["task_profile"] = str(data.get("task_profile") or "adaptive")
        data.update(legacy_campaign_flags(data.get("status")))
        data["model_policy"] = str(data.get("model_policy") or "inherit")
        data["model_validation"] = str(data.get("model_validation") or "fallback")
        # The 0.1 database column is retained for a non-destructive upgrade, but
        # the public concept is task-neutral operating boundaries.
        data["operating_boundaries"] = data.get("authorized_scope") or {}
        return data

    @staticmethod
    def _episode_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in EPISODE_JSON_FIELDS:
            default: Any = None
            if key in {"agent_activity", "model_events"}:
                default = []
            data[key] = json_loads_or(data.get(key), default)
        return data
