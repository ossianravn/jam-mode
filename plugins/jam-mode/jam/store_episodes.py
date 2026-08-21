from __future__ import annotations

import sqlite3
from typing import Any

from .handoff import normalize_handoff
from .lifecycle import RUNNABLE_CAMPAIGN_STATUSES, validate_campaign_transition
from .store_core import (
    EPISODE_JSON_FIELDS,
    CampaignNotFound,
    CampaignNotRunnable,
    StoreError,
)
from .util import json_dumps, new_id, utc_now


class EpisodeStoreMixin:
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
                "SELECT status FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if campaign is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            if campaign["status"] not in RUNNABLE_CAMPAIGN_STATUSES:
                raise CampaignNotRunnable(
                    f"Campaign {campaign_id} is not runnable in state "
                    f"{campaign['status']!r}."
                )
            validate_campaign_transition(campaign["status"], "running")
            active = conn.execute(
                "SELECT id, campaign_id FROM episodes "
                "WHERE ended_at IS NULL AND status IN ('queued', 'running') "
                "LIMIT 1"
            ).fetchone()
            if active is not None:
                raise StoreError(
                    "Another JAM episode is already active: "
                    f"{active['campaign_id']} ({active['id']}). "
                    "JAM 0.3 supports one top-level episode at a time."
                )
            number = int(
                conn.execute(
                    "SELECT COALESCE(MAX(number), 0) + 1 FROM episodes "
                    "WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchone()[0]
            )
            try:
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
            except sqlite3.IntegrityError as exc:
                raise StoreError(
                    "Another JAM episode became active before this episode could start."
                ) from exc
            conn.execute(
                """
                UPDATE campaigns
                SET status = 'running', started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, campaign_id),
            )
        return self.get_episode(episode_id)

    def update_episode(self, episode_id: str, **changes: Any) -> dict[str, Any]:
        if not changes:
            return self.get_episode(episode_id)
        allowed = {
            "objective",
            "task_profile_hint",
            "strategy_hint",
            "thread_id",
            "turn_id",
            "prompt_path",
            "events_path",
            "final_path",
            "handoff_path",
            "routing_snapshot",
            "agent_activity",
            "model_events",
            "token_usage",
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
        handoff = (
            normalize_handoff(handoff, preserve_internal=True)
            if handoff is not None
            else None
        )
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
                UPDATE campaigns SET updated_at = ?,
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

    def active_episode(self, campaign_id: str | None = None) -> dict[str, Any] | None:
        query = (
            "SELECT * FROM episodes WHERE ended_at IS NULL "
            "AND status IN ('queued', 'running')"
        )
        parameters: tuple[Any, ...] = ()
        if campaign_id is not None:
            query += " AND campaign_id = ?"
            parameters = (campaign_id,)
        query += " ORDER BY started_at DESC LIMIT 1"
        with self.connection() as conn:
            row = conn.execute(query, parameters).fetchone()
        return self._episode_from_row(row)
