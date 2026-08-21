from __future__ import annotations

import json
import sqlite3

from .handoff import HandoffError, normalize_handoff, parse_structured_response, public_handoff
from .handoff_fields import (
    EXPLICIT_ID_ORIGIN,
    GENERATED_ID_ORIGIN,
    STATE_ID_ORIGIN_FIELD,
)
from .store_campaign_lifecycle_migration import (
    CAMPAIGN_LIFECYCLE_VERSION,
    ensure_campaign_lifecycle_constraints,
    migrate_campaign_lifecycle,
)
from .store_migration_support import ACTIVE_EPISODE_PREDICATE, StoreMigrationError


EPISODE_AUTHORITY_VERSION = 1
STATE_PROVENANCE_VERSION = 2


def _episode_authority_issues(conn: sqlite3.Connection) -> list[str]:
    issues: list[str] = []
    active_rows = conn.execute(
        f"SELECT id, campaign_id FROM episodes WHERE {ACTIVE_EPISODE_PREDICATE} "
        "ORDER BY campaign_id, number"
    ).fetchall()
    if len(active_rows) > 1:
        rendered = ", ".join(
            f"{row['campaign_id']}:{row['id']}" for row in active_rows
        )
        issues.append(f"multiple active episode rows: {rendered}")

    active_by_campaign = {str(row["campaign_id"]): str(row["id"]) for row in active_rows}
    campaigns = conn.execute(
        "SELECT id, active_episode_id, episode_count FROM campaigns ORDER BY id"
    ).fetchall()
    for campaign in campaigns:
        campaign_id = str(campaign["id"])
        derived_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
        )
        stored_count = int(campaign["episode_count"] or 0)
        if stored_count != derived_count:
            issues.append(
                f"campaign {campaign_id!r} stores episode_count={stored_count}, "
                f"but episode rows derive {derived_count}"
            )
        stored_active = campaign["active_episode_id"]
        derived_active = active_by_campaign.get(campaign_id)
        if stored_active != derived_active:
            issues.append(
                f"campaign {campaign_id!r} stores active_episode_id={stored_active!r}, "
                f"but episode rows derive {derived_active!r}"
            )

    unfinished_terminal = conn.execute(
        "SELECT id, status FROM episodes "
        "WHERE ended_at IS NULL AND status NOT IN ('queued', 'running')"
    ).fetchall()
    for row in unfinished_terminal:
        issues.append(
            f"episode {row['id']!r} has terminal status {row['status']!r} "
            "without ended_at"
        )
    return issues


def _migrate_episode_authority(conn: sqlite3.Connection) -> None:
    issues = _episode_authority_issues(conn)
    if issues:
        details = "\n- ".join(issues)
        raise StoreMigrationError(
            "Cannot migrate episode authority until legacy state is reconciled:\n- "
            + details
        )
    conn.execute("UPDATE campaigns SET active_episode_id = NULL, episode_count = 0")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_single_active "
        "ON episodes((1)) "
        "WHERE ended_at IS NULL AND status IN ('queued', 'running')"
    )
    conn.execute(f"PRAGMA user_version = {EPISODE_AUTHORITY_VERSION}")


def _has_complete_state_provenance(handoff: dict[str, object]) -> bool:
    updates = handoff.get("state_updates")
    if not isinstance(updates, list):
        return True
    return all(
        isinstance(item, dict)
        and item.get(STATE_ID_ORIGIN_FIELD)
        in {EXPLICIT_ID_ORIGIN, GENERATED_ID_ORIGIN}
        for item in updates
    )


def _migrate_state_provenance(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, final_text, handoff FROM episodes WHERE handoff IS NOT NULL"
    ).fetchall()
    for row in rows:
        episode_id = str(row["id"])
        try:
            stored = json.loads(str(row["handoff"]))
        except (TypeError, ValueError) as exc:
            raise StoreMigrationError(
                f"Cannot migrate state-ID provenance for episode {episode_id!r}: "
                "stored handoff is not valid JSON."
            ) from exc
        if not isinstance(stored, dict):
            raise StoreMigrationError(
                f"Cannot migrate state-ID provenance for episode {episode_id!r}: "
                "stored handoff is not an object."
            )
        if _has_complete_state_provenance(stored):
            continue
        final_text = str(row["final_text"] or "")
        try:
            _, reconstructed = parse_structured_response(final_text)
        except HandoffError as exc:
            raise StoreMigrationError(
                f"Cannot migrate state-ID provenance for episode {episode_id!r}: "
                f"raw final response cannot be reparsed ({exc})."
            ) from exc
        normalized_stored = normalize_handoff(stored, preserve_internal=True)
        if public_handoff(normalized_stored) != public_handoff(reconstructed):
            raise StoreMigrationError(
                f"Cannot migrate state-ID provenance for episode {episode_id!r}: "
                "reparsed final response does not match the stored handoff."
            )
        conn.execute(
            "UPDATE episodes SET handoff = ? WHERE id = ?",
            (
                json.dumps(reconstructed, ensure_ascii=False, separators=(",", ":")),
                episode_id,
            ),
        )
    conn.execute(f"PRAGMA user_version = {STATE_PROVENANCE_VERSION}")


def migrate_store(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version < EPISODE_AUTHORITY_VERSION:
        _migrate_episode_authority(conn)
        version = EPISODE_AUTHORITY_VERSION
    if version < STATE_PROVENANCE_VERSION:
        _migrate_state_provenance(conn)
        version = STATE_PROVENANCE_VERSION
    if version < CAMPAIGN_LIFECYCLE_VERSION:
        migrate_campaign_lifecycle(conn)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_single_active "
        "ON episodes((1)) "
        "WHERE ended_at IS NULL AND status IN ('queued', 'running')"
    )
    ensure_campaign_lifecycle_constraints(conn)
