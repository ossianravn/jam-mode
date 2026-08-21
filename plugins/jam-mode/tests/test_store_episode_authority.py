from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jam.store import Store, StoreError


def _campaign_config(workspace: Path, campaign_id: str) -> dict:
    return {
        "id": campaign_id,
        "name": campaign_id,
        "objective": "Verify episode authority.",
        "workspace": str(workspace),
        "operating_boundaries": {"resources": [str(workspace)]},
    }


class EpisodeAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.database = self.root / "jam.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_campaign_episode_fields_are_derived_and_not_writable(self) -> None:
        store = Store(self.database)
        campaign = store.create_campaign(_campaign_config(self.workspace, "derived"))
        episode = store.create_episode(
            campaign["id"], objective="First", strategy_hint="solo"
        )

        active = store.get_campaign(campaign["id"])
        self.assertEqual(active["active_episode_id"], episode["id"])
        self.assertEqual(active["episode_count"], 1)
        with store.connection() as conn:
            legacy = conn.execute(
                "SELECT active_episode_id, episode_count FROM campaigns WHERE id = ?",
                (campaign["id"],),
            ).fetchone()
        self.assertIsNone(legacy["active_episode_id"])
        self.assertEqual(legacy["episode_count"], 0)

        with self.assertRaisesRegex(StoreError, "Unsupported campaign fields"):
            store.update_campaign(campaign["id"], episode_count=99)
        with self.assertRaisesRegex(StoreError, "Unsupported episode fields"):
            store.update_episode(episode["id"], status="completed")

        store.finish_episode(
            episode["id"],
            status="completed",
            turn_status="completed",
            final_text="{}",
            handoff=None,
        )
        finished = store.get_campaign(campaign["id"])
        self.assertIsNone(finished["active_episode_id"])
        self.assertEqual(finished["episode_count"], 1)

        second = store.create_episode(
            campaign["id"], objective="Second", strategy_hint="solo"
        )
        self.assertEqual(second["number"], 2)
        recovered = store.recover_orphaned_episode(campaign["id"])
        assert recovered is not None
        self.assertEqual(recovered["status"], "error")
        self.assertIsNone(store.get_campaign(campaign["id"])["active_episode_id"])

    def test_competing_connections_create_only_one_active_episode(self) -> None:
        store = Store(self.database)
        campaign = store.create_campaign(
            _campaign_config(self.workspace, "race-campaign")
        )
        barrier = threading.Barrier(2)

        def create(campaign_id: str) -> str:
            local = Store(self.database)
            barrier.wait(timeout=5)
            try:
                return local.create_episode(
                    campaign_id,
                    objective="Concurrent",
                    strategy_hint="solo",
                )["id"]
            except StoreError as exc:
                return f"error:{exc}"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, [campaign["id"], campaign["id"]]))
        self.assertEqual(sum(not item.startswith("error:") for item in results), 1)
        self.assertEqual(sum(item.startswith("error:") for item in results), 1)

    def test_migration_reports_inconsistent_legacy_mirrors(self) -> None:
        store = Store(self.database)
        campaign = store.create_campaign(_campaign_config(self.workspace, "legacy"))
        store.create_episode(campaign["id"], objective="Active", strategy_hint="solo")
        with store.connection(immediate=True) as conn:
            conn.execute(
                "UPDATE campaigns SET active_episode_id = 'wrong', episode_count = 9 "
                "WHERE id = ?",
                (campaign["id"],),
            )
            conn.execute("PRAGMA user_version = 0")

        with self.assertRaises(StoreError) as raised:
            Store(self.database)
        message = str(raised.exception)
        self.assertIn("episode_count=9", message)
        self.assertIn("active_episode_id='wrong'", message)

    def test_migration_reports_multiple_active_legacy_rows(self) -> None:
        store = Store(self.database)
        first = store.create_campaign(_campaign_config(self.workspace, "legacy-one"))
        store.transition_campaign(first["id"], "paused")
        second = store.create_campaign(_campaign_config(self.workspace, "legacy-two"))
        store.transition_campaign(second["id"], "paused")
        store.transition_campaign(first["id"], "queued")
        first_episode = store.create_episode(
            first["id"], objective="First", strategy_hint="solo"
        )
        with store.connection(immediate=True) as conn:
            conn.execute("DROP INDEX idx_episodes_single_active")
            conn.execute("DROP INDEX idx_campaigns_single_live")
            conn.execute(
                "INSERT INTO episodes "
                "(id, campaign_id, number, objective, status, started_at) "
                "VALUES ('episode-two', ?, 1, 'Second', 'running', 'now')",
                (second["id"],),
            )
            conn.execute(
                "UPDATE campaigns SET active_episode_id = ?, episode_count = 1 "
                "WHERE id = ?",
                (first_episode["id"], first["id"]),
            )
            conn.execute(
                "UPDATE campaigns SET active_episode_id = 'episode-two', "
                "episode_count = 1, status = 'running' WHERE id = ?",
                (second["id"],),
            )
            conn.execute("PRAGMA user_version = 0")

        with self.assertRaisesRegex(StoreError, "multiple active episode rows"):
            Store(self.database)


if __name__ == "__main__":
    unittest.main()
