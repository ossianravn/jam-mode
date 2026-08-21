from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jam import controller
from jam.campaign_runner import _record_campaign_failure
from jam.controller import continuation_decision, next_episode_plan
from jam.store import Store


def base_campaign() -> dict:
    return {
        "status": "running",
        "low_progress_count": 0,
        "max_low_progress": 2,
        "continuation_threshold": 0.55,
        "episode_count": 1,
        "max_episodes": 20,
        "max_elapsed_minutes": 480,
        "created_at": "2099-01-01T00:00:00+00:00",
    }


def base_handoff() -> dict:
    return {
        "status": "progress",
        "summary": "Useful progress.",
        "progress_score": 0.6,
        "task_profile": "documentation",
        "profile_reason": "The current phase is documentation.",
        "strategy_used": "producer_critic",
        "strategy_reason": "A draft benefits from independent critique.",
        "completed_actions": ["Drafted the migration guide."],
        "decisions": [],
        "state_updates": [],
        "deliverables": [],
        "validation": [],
        "blockers": [],
        "risks": [],
        "artifacts": [],
        "open_items": ["Verify every example command."],
        "boundary_flags": [],
        "needs_user_input": False,
        "user_question": None,
        "completion_assessment": {
            "goal_reached": False,
            "progress_plateau": False,
            "reason": "Command verification remains.",
        },
        "next_options": [
            {
                "objective": "Verify every documented command.",
                "task_profile": "review",
                "strategy": "execute_validate",
                "expected_value": 0.8,
                "reason": "It validates the draft before closure.",
            }
        ],
        "recommended_next_option": 0,
    }


class ContinuationGateTests(unittest.TestCase):
    def test_failure_cleanup_finalizes_derived_active_episode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            workspace.mkdir()
            store = Store(root / "jam.db")
            campaign = store.create_campaign(
                {
                    "id": "failure-campaign",
                    "name": "Failure",
                    "objective": "Exercise failure cleanup.",
                    "workspace": str(workspace),
                    "operating_boundaries": {"resources": [str(workspace)]},
                }
            )
            episode = store.create_episode(
                campaign["id"], objective="Fail", strategy_hint="solo"
            )
            with patch("jam.campaign_runner._write_campaign_summary"):
                cleanup_error = _record_campaign_failure(
                    store, campaign["id"], "ValueError: boom"
                )
            self.assertIsNone(cleanup_error)
            self.assertEqual(store.get_episode(episode["id"])["status"], "error")
            failed = store.get_campaign(campaign["id"])
            self.assertIsNone(failed["active_episode_id"])
            self.assertEqual(failed["status"], "error")

    def test_turn_timeout_is_capped_by_remaining_campaign_budget(self) -> None:
        campaign = base_campaign()
        campaign["max_elapsed_minutes"] = 2
        with patch("jam.controller_decisions._elapsed_minutes", return_value=1.5):
            self.assertEqual(controller._turn_timeout_seconds(campaign), 30)

        campaign["max_elapsed_minutes"] = 600
        with patch("jam.controller_decisions._elapsed_minutes", return_value=0):
            self.assertEqual(controller._turn_timeout_seconds(campaign), 4 * 60 * 60)

    def test_user_state_precedes_continuation(self) -> None:
        campaign = base_campaign()
        campaign["status"] = "pausing_after_current"
        decision = continuation_decision(campaign, base_handoff(), turn_status="completed")
        self.assertEqual(decision[1], "paused")

        campaign = base_campaign()
        campaign["status"] = "stopping_after_current"
        decision = continuation_decision(campaign, base_handoff(), turn_status="completed")
        self.assertEqual(decision[1], "stopped")

    def test_boundary_and_input_flags_stop(self) -> None:
        handoff = base_handoff()
        handoff["boundary_flags"] = ["External publication approval is required."]
        decision = continuation_decision(base_campaign(), handoff, turn_status="completed")
        self.assertEqual(decision[1], "needs_input")
        self.assertIn("operating boundary", decision[2])

        handoff = base_handoff()
        handoff["needs_user_input"] = True
        handoff["user_question"] = "May the draft be published to the external site?"
        decision = continuation_decision(base_campaign(), handoff, turn_status="completed")
        self.assertEqual(decision[1], "needs_input")
        self.assertIn("published", decision[2])

    def test_legacy_scope_flags_still_stop(self) -> None:
        handoff = base_handoff()
        handoff.pop("boundary_flags")
        handoff["scope_flags"] = ["Production access would be required."]
        decision = continuation_decision(base_campaign(), handoff, turn_status="completed")
        self.assertEqual(decision[1], "needs_input")

    def test_complete_low_value_high_value_and_budget(self) -> None:
        handoff = base_handoff()
        handoff["status"] = "complete"
        handoff["completion_assessment"]["goal_reached"] = True
        decision = continuation_decision(base_campaign(), handoff, turn_status="completed")
        self.assertEqual(decision[1], "completed")

        handoff = base_handoff()
        handoff["next_options"][0]["expected_value"] = 0.2
        decision = continuation_decision(base_campaign(), handoff, turn_status="completed")
        self.assertEqual(decision[1], "completed")
        self.assertIn("below threshold", decision[2])

        decision = continuation_decision(base_campaign(), base_handoff(), turn_status="completed")
        self.assertTrue(decision[0])
        self.assertEqual(decision[1], "queued")

        campaign = base_campaign()
        campaign["episode_count"] = campaign["max_episodes"]
        decision = continuation_decision(campaign, base_handoff(), turn_status="completed")
        self.assertEqual(decision[1], "stopped_budget")

    def test_progress_plateau_requires_review(self) -> None:
        campaign = base_campaign()
        campaign["low_progress_count"] = 1
        handoff = base_handoff()
        handoff["progress_score"] = 0.01
        decision = continuation_decision(campaign, handoff, turn_status="completed")
        self.assertFalse(decision[0])
        self.assertEqual(decision[1], "paused")
        self.assertEqual(decision[3], 2)

    def test_next_episode_plan_uses_recommended_profile_and_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            workspace.mkdir()
            store = Store(root / "jam.db")
            campaign = store.create_campaign(
                {
                    "id": "plan-campaign",
                    "name": "Plan",
                    "objective": "Durable objective",
                    "task_profile": "adaptive",
                    "workspace": str(workspace),
                    "operating_boundaries": {"resources": ["local workspace"]},
                }
            )
            episode = store.create_episode(
                campaign["id"],
                objective="Initial",
                strategy_hint="solo",
                task_profile_hint="documentation",
            )
            store.finish_episode(
                episode["id"],
                status="completed",
                turn_status="completed",
                final_text="{}",
                handoff=base_handoff(),
            )
            objective, strategy, profile = next_episode_plan(
                store, store.get_campaign(campaign["id"])
            )
            self.assertEqual(objective, "Verify every documented command.")
            self.assertEqual(strategy, "execute_validate")
            self.assertEqual(profile, "review")


if __name__ == "__main__":
    unittest.main()
