from __future__ import annotations

import sqlite3
from typing import Any, NoReturn

from .lifecycle import validate_campaign_status, validate_campaign_transition
from .store_core import (
    CAMPAIGN_JSON_FIELDS,
    CampaignNotFound,
    StoreError,
)
from .util import json_dumps, utc_now


CAMPAIGN_UPDATE_FIELDS = frozenset(
    {
        "name",
        "objective",
        "task_profile",
        "workspace",
        "authorized_scope",
        "success_criteria",
        "started_at",
        "completed_at",
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
        "controller_pid",
        "lease_token",
        "lease_expires_at",
        "user_guidance",
        "last_error",
    }
)


class CampaignUpdateStoreMixin:
    def update_campaign(self, campaign_id: str, **changes: Any) -> dict[str, Any]:
        if "operating_boundaries" in changes:
            if "authorized_scope" in changes:
                raise StoreError(
                    "Provide operating_boundaries or authorized_scope, not both."
                )
            changes["authorized_scope"] = changes.pop("operating_boundaries")
        if not changes:
            return self.get_campaign(campaign_id)
        self._validate_update_fields(changes)
        return self._update_campaign_fields(campaign_id, changes)

    def transition_campaign(
        self, campaign_id: str, status: str, **changes: Any
    ) -> dict[str, Any]:
        if "status" in changes:
            raise StoreError("Provide the campaign status only once.")
        self._validate_update_fields(changes)
        try:
            changes["status"] = validate_campaign_status(status)
        except ValueError as exc:
            raise StoreError(str(exc)) from exc
        return self._update_campaign_fields(
            campaign_id, changes, validate_transition=True
        )

    @staticmethod
    def _validate_update_fields(changes: dict[str, Any]) -> None:
        invalid = set(changes) - CAMPAIGN_UPDATE_FIELDS
        if invalid:
            raise StoreError(f"Unsupported campaign fields: {sorted(invalid)}")

    def _update_campaign_fields(
        self,
        campaign_id: str,
        changes: dict[str, Any],
        *,
        validate_transition: bool = False,
    ) -> dict[str, Any]:
        encoded = self._encode_campaign_changes(changes)
        encoded["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = :{key}" for key in encoded)
        encoded["campaign_id"] = campaign_id
        try:
            with self.connection(immediate=True) as conn:
                if validate_transition:
                    current = conn.execute(
                        "SELECT status FROM campaigns WHERE id = ?", (campaign_id,)
                    ).fetchone()
                    if current is None:
                        raise CampaignNotFound(f"Campaign not found: {campaign_id}")
                    try:
                        encoded["status"] = validate_campaign_transition(
                            current["status"], encoded["status"]
                        )
                    except ValueError as exc:
                        raise StoreError(str(exc)) from exc
                cursor = conn.execute(
                    f"UPDATE campaigns SET {assignments} WHERE id = :campaign_id",
                    encoded,
                )
                if cursor.rowcount == 0:
                    raise CampaignNotFound(f"Campaign not found: {campaign_id}")
        except sqlite3.IntegrityError as exc:
            self._raise_live_campaign_conflict(exc, exclude_id=campaign_id)
        return self.get_campaign(campaign_id)

    @staticmethod
    def _encode_campaign_changes(changes: dict[str, Any]) -> dict[str, Any]:
        encoded: dict[str, Any] = {}
        for key, value in changes.items():
            if key in CAMPAIGN_JSON_FIELDS:
                encoded[key] = json_dumps(value)
            elif key in {
                "allow_network",
                "allow_child_ultra",
                "allow_parent_ultra",
            }:
                encoded[key] = int(bool(value))
            else:
                encoded[key] = value
        return encoded

    def _raise_live_campaign_conflict(
        self, exc: sqlite3.IntegrityError, *, exclude_id: str | None = None
    ) -> NoReturn:
        live = self.live_campaign(exclude_id=exclude_id)
        if live is not None:
            raise StoreError(
                "JAM permits one live campaign at a time. Pause or stop "
                f"{live['id']} ({live['name']}) first."
            ) from exc
        raise StoreError(f"Campaign update violates a database constraint: {exc}") from exc

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
