from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jam.store import Store, StoreError


def _config(workspace: Path, campaign_id: str) -> dict:
    return {
        "id": campaign_id,
        "name": campaign_id,
        "objective": "Verify the campaign lifecycle invariant.",
        "workspace": str(workspace),
        "operating_boundaries": {"resources": [str(workspace)]},
    }


class CampaignLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.database = self.root / "jam.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_status_is_authoritative_and_legacy_flags_are_derived(self) -> None:
        store = Store(self.database)
        campaign = store.create_campaign(_config(self.workspace, "lifecycle"))
        self.assertEqual(
            (campaign["enabled"], campaign["stop_after_current"],
             campaign["termination_requested"]),
            (True, False, False),
        )
        with store.connection() as conn:
            raw = conn.execute(
                "SELECT enabled, stop_after_current, termination_requested "
                "FROM campaigns WHERE id = ?",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(tuple(raw), (0, 0, 0))

        episode = store.create_episode(
            campaign["id"], objective="Run", strategy_hint="solo"
        )
        pausing = store.transition_campaign(
            campaign["id"], "pausing_after_current"
        )
        self.assertEqual(
            (pausing["enabled"], pausing["stop_after_current"],
             pausing["termination_requested"]),
            (False, True, False),
        )
        stopping = store.transition_campaign(
            campaign["id"], "stopping_after_current"
        )
        self.assertEqual(
            (stopping["enabled"], stopping["stop_after_current"],
             stopping["termination_requested"]),
            (False, True, True),
        )
        store.finish_episode(
            episode["id"], status="completed", turn_status="completed",
            final_text="{}", handoff=None,
        )
        stopped = store.transition_campaign(campaign["id"], "stopped")
        self.assertEqual(
            (stopped["enabled"], stopped["stop_after_current"],
             stopped["termination_requested"]),
            (False, False, True),
        )

        with self.assertRaisesRegex(StoreError, "Unsupported campaign fields"):
            store.update_campaign(campaign["id"], status="queued")
        with self.assertRaisesRegex(StoreError, "cannot transition"):
            store.transition_campaign(campaign["id"], "completed")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "unsupported campaign status"):
            with store.connection(immediate=True) as conn:
                conn.execute(
                    "UPDATE campaigns SET status = 'stopping' WHERE id = ?",
                    (campaign["id"],),
                )

    def test_competing_connections_create_only_one_live_campaign(self) -> None:
        Store(self.database)
        barrier = threading.Barrier(2)

        def create(campaign_id: str) -> str:
            local = Store(self.database)
            barrier.wait(timeout=5)
            try:
                return local.create_campaign(
                    _config(self.workspace, campaign_id)
                )["id"]
            except StoreError as exc:
                return f"error:{exc}"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, ("live-one", "live-two")))
        self.assertEqual(sum(not item.startswith("error:") for item in results), 1)
        self.assertEqual(sum(item.startswith("error:") for item in results), 1)
        self.assertEqual(len(Store(self.database).list_campaigns()), 1)

    def test_migration_converts_legacy_stop_intent_and_rejects_bad_finalizing(self) -> None:
        store = Store(self.database)
        campaign = store.create_campaign(_config(self.workspace, "legacy-stop"))
        store.create_episode(campaign["id"], objective="Run", strategy_hint="solo")
        with store.connection(immediate=True) as conn:
            conn.execute(
                "UPDATE campaigns SET termination_requested = 1 WHERE id = ?",
                (campaign["id"],),
            )
            conn.execute("PRAGMA user_version = 2")

        migrated = Store(self.database).get_campaign(campaign["id"])
        self.assertEqual(migrated["status"], "stopping_after_current")
        self.assertTrue(migrated["termination_requested"])
        with Store(self.database).connection() as conn:
            raw = conn.execute(
                "SELECT enabled, stop_after_current, termination_requested "
                "FROM campaigns WHERE id = ?",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(tuple(raw), (0, 0, 0))

        bad_database = self.root / "bad-finalizing.db"
        bad = Store(bad_database)
        invalid = bad.create_campaign(_config(self.workspace, "bad-finalizing"))
        with bad.connection(immediate=True) as conn:
            conn.execute("DROP TRIGGER validate_campaign_status_update")
            conn.execute("PRAGMA ignore_check_constraints = ON")
            conn.execute(
                "UPDATE campaigns SET status = 'finalizing' WHERE id = ?",
                (invalid["id"],),
            )
            conn.execute("PRAGMA user_version = 2")
        with self.assertRaisesRegex(StoreError, "finalizing without an active episode"):
            Store(bad_database)

    def test_migration_rejects_multiple_legacy_live_campaigns(self) -> None:
        store = Store(self.database)
        first = store.create_campaign(_config(self.workspace, "legacy-live-one"))
        store.transition_campaign(first["id"], "paused")
        second = store.create_campaign(_config(self.workspace, "legacy-live-two"))
        store.transition_campaign(second["id"], "paused")
        with store.connection(immediate=True) as conn:
            conn.execute("DROP INDEX idx_campaigns_single_live")
            conn.execute(
                "UPDATE campaigns SET status = 'queued', enabled = 1 "
                "WHERE id IN (?, ?)",
                (first["id"], second["id"]),
            )
            conn.execute("PRAGMA user_version = 2")

        with self.assertRaisesRegex(StoreError, "multiple campaigns are live"):
            Store(self.database)


if __name__ == "__main__":
    unittest.main()
