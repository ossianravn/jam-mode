from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .paths import database_path
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


class StoreError(RuntimeError):
    pass


class CampaignNotFound(StoreError):
    pass


class Store:
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
                    status TEXT NOT NULL DEFAULT 'queued',
                    enabled INTEGER NOT NULL DEFAULT 1,
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

    @staticmethod
    def _campaign_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        object_fields = {"authorized_scope", "requested_routing", "resolved_routing"}
        for key in CAMPAIGN_JSON_FIELDS:
            data[key] = json_loads_or(data.get(key), {} if key in object_fields else [])
        for key in (
            "enabled",
            "stop_after_current",
            "termination_requested",
            "allow_network",
            "allow_child_ultra",
            "allow_parent_ultra",
        ):
            data[key] = bool(data.get(key))
        data["task_profile"] = str(data.get("task_profile") or "adaptive")
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

    def create_campaign(self, config: dict[str, Any]) -> dict[str, Any]:
        name = str(config.get("name") or "JAM campaign").strip()
        campaign_id = str(config.get("id") or new_campaign_id(name))
        now = utc_now()
        fields = {
            "id": campaign_id,
            "name": name,
            "objective": str(config["objective"]).strip(),
            "task_profile": str(config.get("task_profile") or "adaptive"),
            "workspace": str(config["workspace"]),
            "authorized_scope": json_dumps(
                config.get("operating_boundaries")
                or config.get("authorized_scope")
                or {}
            ),
            "success_criteria": str(config.get("success_criteria") or "").strip(),
            "status": "queued",
            "enabled": 1,
            "stop_after_current": 0,
            "termination_requested": 0,
            "created_at": now,
            "updated_at": now,
            "model": config.get("model") or None,
            "effort": config.get("effort") or None,
            "model_policy": str(config.get("model_policy") or "inherit"),
            "model_validation": str(config.get("model_validation") or "fallback"),
            "allow_child_ultra": int(bool(config.get("allow_child_ultra", False))),
            "allow_parent_ultra": int(bool(config.get("allow_parent_ultra", False))),
            "requested_routing": json_dumps(config.get("requested_routing") or {}),
            "resolved_routing": json_dumps(config.get("resolved_routing") or {}),
            "model_catalog_snapshot": json_dumps(config.get("model_catalog_snapshot") or []),
            "routing_warnings": json_dumps(config.get("routing_warnings") or []),
            "sandbox": str(config.get("sandbox") or "read-only"),
            "allow_network": int(bool(config.get("allow_network", False))),
            "max_episodes": int(config.get("max_episodes", 20)),
            "max_elapsed_minutes": int(config.get("max_elapsed_minutes", 480)),
            "continuation_threshold": float(config.get("continuation_threshold", 0.55)),
            "max_low_progress": int(config.get("max_low_progress", 2)),
            "max_subagents": int(config.get("max_subagents", 2)),
            "memory_paths": json_dumps(config.get("memory_paths") or []),
            "tags": json_dumps(config.get("tags") or []),
            "user_guidance": str(config.get("user_guidance") or ""),
        }
        columns = ", ".join(fields)
        placeholders = ", ".join(f":{key}" for key in fields)
        try:
            with self.connection(immediate=True) as conn:
                conn.execute(
                    f"INSERT INTO campaigns ({columns}) VALUES ({placeholders})", fields
                )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"Campaign id already exists: {campaign_id}") from exc
        return self.get_campaign(campaign_id)

    def resolve_campaign_id(self, identifier: str | None = None) -> str:
        with self.connection() as conn:
            if identifier and identifier not in {"active", "latest"}:
                exact = conn.execute(
                    "SELECT id FROM campaigns WHERE id = ?", (identifier,)
                ).fetchone()
                if exact:
                    return str(exact["id"])
                rows = conn.execute(
                    "SELECT id FROM campaigns WHERE name = ? ORDER BY updated_at DESC LIMIT 2",
                    (identifier,),
                ).fetchall()
                if len(rows) == 1:
                    return str(rows[0]["id"])
                if len(rows) > 1:
                    raise StoreError(
                        f"More than one campaign is named {identifier!r}; use its id."
                    )
                raise CampaignNotFound(f"Campaign not found: {identifier}")

            active = conn.execute(
                """
                SELECT id FROM campaigns
                WHERE status IN ('queued', 'planning', 'running', 'finalizing',
                                 'paused', 'needs_input', 'error')
                ORDER BY
                    CASE WHEN status IN ('running', 'planning', 'queued') THEN 0 ELSE 1 END,
                    updated_at DESC
                LIMIT 1
                """
            ).fetchone()
            if active:
                return str(active["id"])
            latest = conn.execute(
                "SELECT id FROM campaigns ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if latest:
                return str(latest["id"])
        raise CampaignNotFound("No JAM campaigns exist yet.")

    def get_campaign(self, identifier: str | None = None) -> dict[str, Any]:
        campaign_id = self.resolve_campaign_id(identifier) if identifier is not None else self.resolve_campaign_id("active")
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        campaign = self._campaign_from_row(row)
        if campaign is None:
            raise CampaignNotFound(f"Campaign not found: {campaign_id}")
        return campaign

    def list_campaigns(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM campaigns ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._campaign_from_row(row) for row in rows if row is not None]

    def update_campaign(self, campaign_id: str, **changes: Any) -> dict[str, Any]:
        if "operating_boundaries" in changes:
            if "authorized_scope" in changes:
                raise StoreError(
                    "Provide operating_boundaries or authorized_scope, not both."
                )
            changes["authorized_scope"] = changes.pop("operating_boundaries")
        if not changes:
            return self.get_campaign(campaign_id)
        allowed = {
            "name",
            "objective",
            "task_profile",
            "workspace",
            "authorized_scope",
            "success_criteria",
            "status",
            "enabled",
            "stop_after_current",
            "termination_requested",
            "started_at",
            "completed_at",
            "active_episode_id",
            "last_thread_id",
            "model",
            "effort",
            "model_policy",
            "model_validation",
            "allow_child_ultra",
            "allow_parent_ultra",
            "requested_routing",
            "resolved_routing",
            "model_catalog_snapshot",
            "routing_warnings",
            "sandbox",
            "allow_network",
            "max_episodes",
            "max_elapsed_minutes",
            "continuation_threshold",
            "max_low_progress",
            "low_progress_count",
            "max_subagents",
            "memory_paths",
            "tags",
            "episode_count",
            "controller_pid",
            "lease_token",
            "lease_expires_at",
            "user_guidance",
            "last_error",
        }
        invalid = set(changes) - allowed
        if invalid:
            raise StoreError(f"Unsupported campaign fields: {sorted(invalid)}")
        encoded: dict[str, Any] = {}
        for key, value in changes.items():
            if key in CAMPAIGN_JSON_FIELDS:
                encoded[key] = json_dumps(value)
            elif key in {
                "enabled",
                "stop_after_current",
                "termination_requested",
                "allow_network",
                "allow_child_ultra",
                "allow_parent_ultra",
            }:
                encoded[key] = int(bool(value))
            else:
                encoded[key] = value
        encoded["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = :{key}" for key in encoded)
        encoded["campaign_id"] = campaign_id
        with self.connection(immediate=True) as conn:
            cursor = conn.execute(
                f"UPDATE campaigns SET {assignments} WHERE id = :campaign_id", encoded
            )
            if cursor.rowcount == 0:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
        return self.get_campaign(campaign_id)

    def append_guidance(self, campaign_id: str, guidance: str) -> dict[str, Any]:
        guidance = guidance.strip()
        if not guidance:
            return self.get_campaign(campaign_id)
        campaign = self.get_campaign(campaign_id)
        existing = str(campaign.get("user_guidance") or "").strip()
        combined = f"{existing}\n\n[{utc_now()}]\n{guidance}".strip()
        return self.update_campaign(campaign_id, user_guidance=combined)

    def add_memory_path(self, campaign_id: str, path: str) -> dict[str, Any]:
        campaign = self.get_campaign(campaign_id)
        paths = [str(item) for item in campaign.get("memory_paths", [])]
        if path not in paths:
            paths.append(path)
        return self.update_campaign(campaign_id, memory_paths=paths)

    def create_episode(
        self,
        campaign_id: str,
        *,
        objective: str,
        strategy_hint: str | None,
        task_profile_hint: str | None = None,
        routing_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        episode_id = new_id("episode")
        now = utc_now()
        with self.connection(immediate=True) as conn:
            campaign = conn.execute(
                "SELECT episode_count, active_episode_id FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if campaign is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            if campaign["active_episode_id"]:
                raise StoreError(
                    f"Campaign {campaign_id} already has active episode "
                    f"{campaign['active_episode_id']}"
                )
            other = conn.execute(
                "SELECT id, active_episode_id FROM campaigns "
                "WHERE id <> ? AND active_episode_id IS NOT NULL LIMIT 1",
                (campaign_id,),
            ).fetchone()
            if other is not None:
                raise StoreError(
                    "Another JAM episode is already active: "
                    f"{other['id']} ({other['active_episode_id']}). "
                    "JAM 0.3 supports one top-level episode at a time."
                )
            number = int(campaign["episode_count"]) + 1
            conn.execute(
                """
                INSERT INTO episodes (
                    id, campaign_id, number, objective, task_profile_hint,
                    strategy_hint, routing_snapshot, status, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    episode_id,
                    campaign_id,
                    number,
                    objective,
                    task_profile_hint,
                    strategy_hint,
                    json_dumps(routing_snapshot) if routing_snapshot is not None else None,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE campaigns
                SET active_episode_id = ?, episode_count = ?, status = 'running',
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (episode_id, number, now, now, campaign_id),
            )
        return self.get_episode(episode_id)

    def update_episode(self, episode_id: str, **changes: Any) -> dict[str, Any]:
        if not changes:
            return self.get_episode(episode_id)
        allowed = {
            "objective",
            "task_profile_hint",
            "task_profile_used",
            "strategy_hint",
            "strategy_used",
            "status",
            "thread_id",
            "turn_id",
            "started_at",
            "ended_at",
            "prompt_path",
            "events_path",
            "final_path",
            "handoff_path",
            "final_text",
            "handoff",
            "routing_snapshot",
            "agent_activity",
            "model_events",
            "token_usage",
            "turn_status",
            "progress_score",
            "expected_next_value",
            "error",
        }
        invalid = set(changes) - allowed
        if invalid:
            raise StoreError(f"Unsupported episode fields: {sorted(invalid)}")
        encoded = {
            key: json_dumps(value) if key in EPISODE_JSON_FIELDS else value
            for key, value in changes.items()
        }
        assignments = ", ".join(f"{key} = :{key}" for key in encoded)
        encoded["episode_id"] = episode_id
        with self.connection(immediate=True) as conn:
            cursor = conn.execute(
                f"UPDATE episodes SET {assignments} WHERE id = :episode_id", encoded
            )
            if cursor.rowcount == 0:
                raise StoreError(f"Episode not found: {episode_id}")
        return self.get_episode(episode_id)

    def finish_episode(
        self,
        episode_id: str,
        *,
        status: str,
        turn_status: str,
        final_text: str,
        handoff: dict[str, Any] | None,
        error: str | None = None,
    ) -> dict[str, Any]:
        episode = self.get_episode(episode_id)
        progress_score = None
        expected_next_value = None
        strategy_used = None
        task_profile_used = None
        if handoff:
            try:
                progress_score = float(handoff.get("progress_score"))
            except (TypeError, ValueError):
                progress_score = None
            strategy_used = handoff.get("strategy_used")
            task_profile_used = handoff.get("task_profile")
            options = handoff.get("next_options") or []
            index = handoff.get("recommended_next_option")
            if isinstance(index, int) and 0 <= index < len(options):
                try:
                    expected_next_value = float(options[index].get("expected_value"))
                except (TypeError, ValueError, AttributeError):
                    expected_next_value = None
        now = utc_now()
        with self.connection(immediate=True) as conn:
            conn.execute(
                """
                UPDATE episodes SET
                    status = ?, turn_status = ?, final_text = ?, handoff = ?,
                    task_profile_used = ?, strategy_used = ?, progress_score = ?,
                    expected_next_value = ?, error = ?, ended_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    turn_status,
                    final_text,
                    json_dumps(handoff) if handoff is not None else None,
                    task_profile_used,
                    strategy_used,
                    progress_score,
                    expected_next_value,
                    error,
                    now,
                    episode_id,
                ),
            )
            conn.execute(
                """
                UPDATE campaigns SET active_episode_id = NULL, updated_at = ?,
                    last_thread_id = COALESCE((SELECT thread_id FROM episodes WHERE id = ?), last_thread_id),
                    last_error = ?
                WHERE id = ?
                """,
                (now, episode_id, error, episode["campaign_id"]),
            )
        return self.get_episode(episode_id)

    def get_episode(self, episode_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone()
        episode = self._episode_from_row(row)
        if episode is None:
            raise StoreError(f"Episode not found: {episode_id}")
        return episode

    def list_episodes(self, campaign_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM episodes WHERE campaign_id = ?
                ORDER BY number DESC LIMIT ?
                """,
                (campaign_id, limit),
            ).fetchall()
        return [self._episode_from_row(row) for row in rows if row is not None]

    def last_episode(self, campaign_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM episodes WHERE campaign_id = ?
                ORDER BY number DESC LIMIT 1
                """,
                (campaign_id,),
            ).fetchone()
        return self._episode_from_row(row)

    def acquire_lease(self, campaign_id: str, token: str, *, ttl_seconds: int = 180) -> bool:
        now = epoch_now()
        expires = now + ttl_seconds
        with self.connection(immediate=True) as conn:
            row = conn.execute(
                "SELECT lease_token, lease_expires_at FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            current_token = row["lease_token"]
            current_expiry = row["lease_expires_at"]
            available = (
                current_token is None
                or current_token == token
                or current_expiry is None
                or float(current_expiry) < now
            )
            if not available:
                return False
            conn.execute(
                """
                UPDATE campaigns
                SET lease_token = ?, lease_expires_at = ?, controller_pid = ?, updated_at = ?
                WHERE id = ?
                """,
                (token, expires, __import__("os").getpid(), utc_now(), campaign_id),
            )
        return True

    def refresh_lease(self, campaign_id: str, token: str, *, ttl_seconds: int = 180) -> bool:
        expires = epoch_now() + ttl_seconds
        with self.connection(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE campaigns SET lease_expires_at = ?, controller_pid = ?, updated_at = ?
                WHERE id = ? AND lease_token = ?
                """,
                (expires, __import__("os").getpid(), utc_now(), campaign_id, token),
            )
        return cursor.rowcount > 0

    def release_lease(self, campaign_id: str, token: str) -> None:
        with self.connection(immediate=True) as conn:
            conn.execute(
                """
                UPDATE campaigns SET lease_token = NULL, lease_expires_at = NULL,
                    controller_pid = NULL, updated_at = ?
                WHERE id = ? AND lease_token = ?
                """,
                (utc_now(), campaign_id, token),
            )

    def recover_orphaned_episode(self, campaign_id: str) -> dict[str, Any] | None:
        campaign = self.get_campaign(campaign_id)
        episode_id = campaign.get("active_episode_id")
        if not episode_id:
            return None
        episode = self.get_episode(str(episode_id))
        now = utc_now()
        message = "Previous controller stopped before the episode completed."
        with self.connection(immediate=True) as conn:
            conn.execute(
                """
                UPDATE episodes SET status = 'error', turn_status = 'interrupted',
                    error = ?, ended_at = ? WHERE id = ?
                """,
                (message, now, episode_id),
            )
            conn.execute(
                """
                UPDATE campaigns SET active_episode_id = NULL, status = 'error',
                    last_error = ?, updated_at = ? WHERE id = ?
                """,
                (message, now, campaign_id),
            )
        return self.get_episode(str(episode_id))
