from __future__ import annotations

import sqlite3
from typing import Any

from .lifecycle import LIVE_CAMPAIGN_STATUSES
from .store_core import (
    CAMPAIGN_WITH_EPISODE_STATE,
    CampaignNotFound,
    StoreError,
)
from .util import json_dumps, new_campaign_id, utc_now


class CampaignStoreMixin:
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
            # Retained 0.1 columns are inert; public flags derive from status.
            "enabled": 0,
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
            with self.connection() as conn:
                duplicate = conn.execute(
                    "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
                ).fetchone()
            if duplicate:
                raise StoreError(f"Campaign id already exists: {campaign_id}") from exc
            self._raise_live_campaign_conflict(exc)
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

            if identifier == "latest":
                latest = conn.execute(
                    "SELECT id FROM campaigns ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if latest:
                    return str(latest["id"])

            active = conn.execute(
                """
                SELECT id FROM campaigns
                WHERE status IN ('queued', 'planning', 'running',
                                 'pausing_after_current',
                                 'stopping_after_current', 'paused',
                                 'needs_input', 'error')
                ORDER BY
                    CASE
                        WHEN status IN ('running', 'planning', 'queued') THEN 0
                        WHEN status IN (
                            'pausing_after_current', 'stopping_after_current'
                        ) THEN 1
                        ELSE 2
                    END,
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
                CAMPAIGN_WITH_EPISODE_STATE + " WHERE c.id = ?", (campaign_id,)
            ).fetchone()
        campaign = self._campaign_from_row(row)
        if campaign is None:
            raise CampaignNotFound(f"Campaign not found: {campaign_id}")
        return campaign

    def list_campaigns(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                CAMPAIGN_WITH_EPISODE_STATE
                + " ORDER BY c.updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._campaign_from_row(row) for row in rows if row is not None]

    def live_campaign(self, *, exclude_id: str | None = None) -> dict[str, Any] | None:
        statuses = tuple(sorted(LIVE_CAMPAIGN_STATUSES))
        placeholders = ", ".join("?" for _ in statuses)
        query = CAMPAIGN_WITH_EPISODE_STATE + (
            f" WHERE c.status IN ({placeholders})"
        )
        parameters: tuple[Any, ...] = statuses
        if exclude_id is not None:
            query += " AND c.id != ?"
            parameters += (exclude_id,)
        query += " ORDER BY c.updated_at DESC LIMIT 1"
        with self.connection() as conn:
            row = conn.execute(query, parameters).fetchone()
        return self._campaign_from_row(row)
