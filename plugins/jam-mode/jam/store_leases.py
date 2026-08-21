from __future__ import annotations

from typing import Any

from .store_core import CampaignNotFound
from .util import epoch_now, utc_now


class LeaseStoreMixin:
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
        episode = self.active_episode(campaign_id)
        if episode is None:
            return None
        episode_id = str(episode["id"])
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
                UPDATE campaigns SET status = 'error', last_error = ?,
                    updated_at = ? WHERE id = ?
                """,
                (message, now, campaign_id),
            )
        return self.get_episode(str(episode_id))
