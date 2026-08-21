from __future__ import annotations

import sqlite3

from .lifecycle import (
    AFTER_CURRENT_STATUSES,
    CAMPAIGN_STATUSES,
    LIVE_CAMPAIGN_STATUSES,
    NON_LIVE_CAMPAIGN_STATUSES,
    RUNNABLE_CAMPAIGN_STATUSES,
)
from .store_migration_support import (
    ACTIVE_EPISODE_PREDICATE,
    StoreMigrationError,
)


CAMPAIGN_LIFECYCLE_VERSION = 3
CAMPAIGN_STATUS_SQL = ", ".join(
    f"'{status}'" for status in sorted(CAMPAIGN_STATUSES)
)


def _migrated_campaign_status(
    row: sqlite3.Row,
    *,
    has_active_episode: bool,
) -> str:
    status = str(row["status"] or "").strip().lower()
    enabled = bool(row["enabled"])
    pause_requested = bool(row["stop_after_current"])
    stop_requested = bool(row["termination_requested"])

    if status == "finalizing":
        if not has_active_episode:
            raise StoreMigrationError(
                f"campaign {row['id']!r} is finalizing without an active episode"
            )
        return "running"
    if status in {"stopping", "stopping_after_current"}:
        if has_active_episode:
            return (
                "stopping_after_current"
                if stop_requested
                else "pausing_after_current"
            )
        return "stopped" if stop_requested else "paused"
    if status == "pausing_after_current":
        if stop_requested:
            return "stopping_after_current" if has_active_episode else "stopped"
        return "pausing_after_current" if has_active_episode else "paused"
    if status not in CAMPAIGN_STATUSES:
        raise StoreMigrationError(
            f"campaign {row['id']!r} has unsupported status {status!r}"
        )
    if status in NON_LIVE_CAMPAIGN_STATUSES:
        if has_active_episode:
            raise StoreMigrationError(
                f"campaign {row['id']!r} has non-live status {status!r} "
                "while an episode is active"
            )
        return status
    if status in RUNNABLE_CAMPAIGN_STATUSES:
        if stop_requested:
            return "stopping_after_current" if has_active_episode else "stopped"
        if pause_requested or not enabled:
            return "pausing_after_current" if has_active_episode else "paused"
        return status
    if status in AFTER_CURRENT_STATUSES:
        return status if has_active_episode else (
            "stopped" if status == "stopping_after_current" else "paused"
        )
    raise StoreMigrationError(
        f"campaign {row['id']!r} has unsupported lifecycle state {status!r}"
    )


def migrate_campaign_lifecycle(conn: sqlite3.Connection) -> None:
    active_campaign_ids = {
        str(row["campaign_id"])
        for row in conn.execute(
            f"SELECT campaign_id FROM episodes WHERE {ACTIVE_EPISODE_PREDICATE}"
        ).fetchall()
    }
    rows = conn.execute(
        "SELECT id, status, enabled, stop_after_current, termination_requested "
        "FROM campaigns ORDER BY id"
    ).fetchall()
    migrated = [
        (
            str(row["id"]),
            _migrated_campaign_status(
                row,
                has_active_episode=str(row["id"]) in active_campaign_ids,
            ),
        )
        for row in rows
    ]
    live = [
        campaign_id
        for campaign_id, status in migrated
        if status in LIVE_CAMPAIGN_STATUSES
    ]
    if len(live) > 1:
        raise StoreMigrationError(
            "Cannot migrate campaign lifecycle because multiple campaigns are live: "
            + ", ".join(live)
        )
    for campaign_id, status in migrated:
        conn.execute(
            "UPDATE campaigns SET status = ?, enabled = 0, "
            "stop_after_current = 0, termination_requested = 0 WHERE id = ?",
            (status, campaign_id),
        )
    ensure_campaign_lifecycle_constraints(conn)
    conn.execute(f"PRAGMA user_version = {CAMPAIGN_LIFECYCLE_VERSION}")


def ensure_campaign_lifecycle_constraints(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_campaigns_single_live "
        "ON campaigns((1)) WHERE status IN ("
        "'queued', 'planning', 'running', "
        "'pausing_after_current', 'stopping_after_current')"
    )
    for suffix, operation in (
        ("insert", "INSERT"),
        ("update", "UPDATE OF status"),
    ):
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS validate_campaign_status_{suffix}
            BEFORE {operation} ON campaigns
            WHEN NEW.status NOT IN ({CAMPAIGN_STATUS_SQL})
            BEGIN
                SELECT RAISE(ABORT, 'unsupported campaign status');
            END
            """
        )
