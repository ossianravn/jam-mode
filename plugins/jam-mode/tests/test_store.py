from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from jam.store import Store, StoreError


def campaign_config(workspace: Path, *, campaign_id: str, name: str) -> dict:
    return {
        "id": campaign_id,
        "name": name,
        "objective": "Implement and verify a bounded change.",
        "task_profile": "adaptive",
        "workspace": str(workspace),
        "operating_boundaries": {
            "resources": ["local repository"],
            "excluded_actions": ["production deployment"],
        },
        "success_criteria": "The requested deliverable is validated.",
        "sandbox": "workspace-write",
        "allow_network": False,
        "max_episodes": 5,
        "max_elapsed_minutes": 60,
        "continuation_threshold": 0.55,
        "max_low_progress": 2,
        "max_subagents": 2,
        "memory_paths": [],
        "tags": ["test"],
    }


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.store = Store(self.root / "jam.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_campaign_and_episode_lifecycle(self) -> None:
        first = self.store.create_campaign(
            campaign_config(self.workspace, campaign_id="campaign-one", name="One")
        )
        with self.assertRaisesRegex(StoreError, "one live campaign"):
            self.store.create_campaign(
                campaign_config(self.workspace, campaign_id="campaign-two", name="Two")
            )
        self.assertEqual(first["episode_count"], 0)
        self.assertEqual(first["task_profile"], "adaptive")
        self.assertEqual(
            first["operating_boundaries"]["resources"], ["local repository"]
        )
        self.assertEqual(self.store.get_campaign("One")["id"], "campaign-one")

        episode = self.store.create_episode(
            first["id"],
            objective="Implement the relevant change.",
            strategy_hint="builder_reviewer",
            task_profile_hint="engineering",
        )
        self.assertEqual(episode["number"], 1)
        self.assertEqual(episode["task_profile_hint"], "engineering")
        self.assertEqual(
            self.store.get_campaign(first["id"])["active_episode_id"], episode["id"]
        )

        with self.assertRaises(StoreError):
            self.store.create_episode(
                first["id"], objective="Duplicate", strategy_hint="solo"
            )
        self.store.update_episode(episode["id"], thread_id="thr-1")
        finished = self.store.finish_episode(
            episode["id"],
            status="completed",
            turn_status="completed",
            final_text="{}",
            handoff={
                "progress_score": 0.7,
                "task_profile": "engineering",
                "strategy_used": "builder_reviewer",
                "next_options": [
                    {
                        "objective": "Review the documentation",
                        "task_profile": "review",
                        "strategy": "execute_validate",
                        "expected_value": 0.9,
                    }
                ],
                "recommended_next_option": 0,
            },
        )
        self.assertEqual(finished["task_profile_used"], "engineering")
        self.assertEqual(finished["strategy_used"], "builder_reviewer")
        self.assertEqual(finished["expected_next_value"], 0.9)
        refreshed = self.store.get_campaign(first["id"])
        self.assertIsNone(refreshed["active_episode_id"])
        self.assertEqual(refreshed["last_thread_id"], "thr-1")

        self.store.transition_campaign(first["id"], "paused")
        second = self.store.create_campaign(
            campaign_config(self.workspace, campaign_id="campaign-two", name="Two")
        )
        second_episode = self.store.create_episode(
            second["id"], objective="Now allowed", strategy_hint="solo"
        )
        self.assertEqual(second_episode["number"], 1)

    def test_guidance_memory_boundaries_and_lease(self) -> None:
        campaign = self.store.create_campaign(
            campaign_config(self.workspace, campaign_id="lease-campaign", name="Lease")
        )
        updated = self.store.append_guidance(campaign["id"], "Prioritize integration validation.")
        self.assertIn("Prioritize integration validation", updated["user_guidance"])
        updated = self.store.add_memory_path(campaign["id"], str(self.root / "notes"))
        self.assertIn(str(self.root / "notes"), updated["memory_paths"])
        updated = self.store.update_campaign(
            campaign["id"],
            operating_boundaries={"resources": ["workspace"], "excluded_actions": ["publish"]},
        )
        self.assertEqual(updated["authorized_scope"], updated["operating_boundaries"])

        self.assertTrue(self.store.acquire_lease(campaign["id"], "token-a", ttl_seconds=60))
        self.assertFalse(self.store.acquire_lease(campaign["id"], "token-b", ttl_seconds=60))
        self.assertTrue(self.store.refresh_lease(campaign["id"], "token-a", ttl_seconds=60))
        self.store.release_lease(campaign["id"], "token-a")
        self.assertTrue(self.store.acquire_lease(campaign["id"], "token-b", ttl_seconds=60))

    def test_episode_creation_rechecks_campaign_state_atomically(self) -> None:
        campaign = self.store.create_campaign(
            campaign_config(self.workspace, campaign_id="race-campaign", name="Race")
        )
        for status in ("paused", "stopped", "stopped_budget"):
            with self.subTest(status=status):
                self.store.transition_campaign(campaign["id"], status)
                with self.assertRaisesRegex(StoreError, "not runnable"):
                    self.store.create_episode(
                        campaign["id"], objective="Should not start", strategy_hint="solo"
                    )
                self.assertEqual(self.store.list_episodes(campaign["id"]), [])
                self.store.transition_campaign(campaign["id"], "queued")

    def test_default_resolution_prioritizes_stopping_campaign(self) -> None:
        paused = self.store.create_campaign(
            campaign_config(self.workspace, campaign_id="paused", name="Paused")
        )
        self.store.transition_campaign(paused["id"], "paused")
        stopping = self.store.create_campaign(
            campaign_config(self.workspace, campaign_id="stopping", name="Stopping")
        )
        self.store.create_episode(
            stopping["id"], objective="Active", strategy_hint="solo"
        )
        self.store.transition_campaign(stopping["id"], "stopping_after_current")

        self.assertEqual(self.store.resolve_campaign_id(), stopping["id"])
        self.assertEqual(self.store.resolve_campaign_id("active"), stopping["id"])

    def test_in_place_upgrade_from_0_1_adds_profile_columns(self) -> None:
        db = self.root / "legacy.db"
        with closing(sqlite3.connect(db)) as conn:
            conn.executescript(
                """
                CREATE TABLE campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    objective TEXT NOT NULL,
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
                CREATE TABLE episodes (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    objective TEXT NOT NULL,
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
                    turn_status TEXT,
                    progress_score REAL,
                    expected_next_value REAL,
                    error TEXT,
                    UNIQUE(campaign_id, number)
                );
                INSERT INTO campaigns (
                    id, name, objective, workspace, authorized_scope,
                    created_at, updated_at
                ) VALUES (
                    'legacy', 'Legacy', 'Legacy objective', '/tmp',
                    '{"targets":["local"]}',
                    '2026-07-30T00:00:00+00:00',
                    '2026-07-30T00:00:00+00:00'
                );
                """
            )

        upgraded = Store(db)
        campaign = upgraded.get_campaign("legacy")
        self.assertEqual(campaign["task_profile"], "adaptive")
        self.assertEqual(campaign["operating_boundaries"], {"targets": ["local"]})
        with upgraded.connection() as conn:
            campaign_columns = {row[1] for row in conn.execute("PRAGMA table_info(campaigns)")}
            episode_columns = {row[1] for row in conn.execute("PRAGMA table_info(episodes)")}
        self.assertIn("task_profile", campaign_columns)
        self.assertIn("task_profile_hint", episode_columns)
        self.assertIn("task_profile_used", episode_columns)
        self.assertIn("model_policy", campaign_columns)
        self.assertIn("allow_parent_ultra", campaign_columns)
        self.assertIn("resolved_routing", campaign_columns)
        self.assertIn("routing_snapshot", episode_columns)
        self.assertIn("agent_activity", episode_columns)


if __name__ == "__main__":
    unittest.main()
