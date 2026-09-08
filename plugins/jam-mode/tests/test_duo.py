from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jam.appserver import TurnResult
from jam.collaboration import CollaborationError, verify_contributions
from jam.contracts import STRATEGIES
from jam.controller import next_episode_plan
from jam.episode_result import read_episode_result
from jam.episode_strategy import render_strategy_instructions
from jam.handoff import normalize_handoff
from jam.prompts import HANDOFF_SCHEMA
from jam.service import start_campaign
from tests.collaboration_events import duo_events, final_event
from tests.test_controller_integration import FAKE_HANDOFF


class DuoTests(unittest.TestCase):
    def verify(self, events, strategy="duo_independent"):
        verify_contributions(events, thread_id="thr_fake_001", turn_id="turn_fake_001",
                             final_text="parent synthesis", strategy=strategy)

    def test_pair_results_must_precede_parent_synthesis(self):
        self.verify(duo_events() + [final_event()])
        for missing in ("not_started", "running", "empty_result", "other_parent", "after_final"):
            events = duo_events()
            if missing == "not_started":
                events.pop(0)
            elif missing == "running":
                events[-1]["params"]["item"]["agentsStates"]["thr_critic"]["status"] = "running"
            elif missing == "empty_result":
                events[-1]["params"]["item"]["agentsStates"]["thr_critic"]["message"] = ""
            elif missing == "other_parent":
                events[0]["params"]["item"]["senderThreadId"] = "child_parent"
            if missing == "after_final":
                events.insert(2, final_event())
            else:
                events.append(final_event())
            with self.subTest(missing=missing), self.assertRaises(CollaborationError):
                self.verify(events)

    def test_duo_requires_pair_started_before_wait_but_sequential_strategy_is_supported(self):
        events = duo_events()
        first_wait = copy.deepcopy(events[-1])
        first_wait["params"]["item"]["receiverThreadIds"] = ["thr_explorer"]
        events.insert(1, first_wait)
        events.append(final_event())
        with self.assertRaisesRegex(CollaborationError, "before waiting"):
            self.verify(events)
        self.verify(events, "builder_reviewer")

    def test_repeated_wait_for_one_child_does_not_count_twice(self):
        events = duo_events()
        events[-1]["params"]["item"]["receiverThreadIds"] = ["thr_explorer"]
        events.append(copy.deepcopy(events[-1]))
        with self.assertRaises(CollaborationError):
            self.verify(events + [final_event()])

    def test_status_only_wait_preserves_results_but_not_across_new_assignments(self):
        for message_field in ({}, {"message": None}):
            events = duo_events()
            status_check = copy.deepcopy(events[-1])
            status_check["params"]["item"]["id"] = "later-status"
            for child in status_check["params"]["item"]["agentsStates"]:
                status_check["params"]["item"]["agentsStates"][child] = {
                    "status": "completed", **message_field,
                }
            with self.subTest(message_field=message_field):
                self.verify(events + [status_check, final_event()])
                assignment = copy.deepcopy(events[0])
                assignment["params"]["item"].update(id="followup", tool="sendInput")
                with self.assertRaises(CollaborationError):
                    self.verify(events + [assignment, status_check, final_event()])

    def test_initial_and_legacy_next_round_use_duo_without_rewriting_history(self):
        store = Mock()
        store.last_episode.return_value = None
        campaign = {"id": "campaign", "objective": "Build the result", "max_subagents": 2}
        self.assertEqual(next_episode_plan(store, campaign)[1], "duo_independent")
        old = copy.deepcopy(FAKE_HANDOFF["handoff"])
        old["strategy_used"] = "solo"
        old["next_options"] = [{"objective": "Check result", "strategy": "solo", "expected_value": 0.8}]
        store.last_episode.return_value = {"handoff": old}
        self.assertEqual(next_episode_plan(store, campaign)[1], "duo_independent")
        self.assertEqual(normalize_handoff(old)["strategy_used"], "solo")
        campaign["max_subagents"] = 1
        with self.assertRaisesRegex(ValueError, "Duo requires"):
            next_episode_plan(store, campaign)

    def test_single_agent_budget_is_rejected_before_routing_or_campaign_creation(self):
        with tempfile.TemporaryDirectory() as directory, patch("jam.service._prepare_routing") as routing:
            with self.assertRaisesRegex(ValueError, "Duo requires"):
                start_campaign(objective="Investigate", workspace=directory, max_subagents=1)
            routing.assert_not_called()

    def test_prompt_and_output_contract_make_duo_default_and_remove_solo(self):
        prompt = render_strategy_instructions({"max_subagents": 2}, None)
        self.assertIn("Current strategy: duo_independent", prompt)
        self.assertIn("jam_explorer and jam_critic before waiting for either", prompt)
        self.assertIn("before synthesizing", prompt)
        self.assertNotIn("solo", STRATEGIES)
        properties = HANDOFF_SCHEMA["properties"]["handoff"]["properties"]
        self.assertNotIn("solo", properties["strategy_used"]["enum"])
        self.assertIn("closure: jam_closer → jam_reviewer", prompt)

    def test_solo_claim_is_rejected_even_with_child_activity_but_blocked_report_can_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            payload = copy.deepcopy(FAKE_HANDOFF)
            payload["handoff"]["strategy_used"] = "solo"
            final = json.dumps(payload)
            path.write_text("\n".join(json.dumps(e) for e in duo_events() + [final_event(final)]), encoding="utf-8")
            result = TurnResult("thr_fake_001", "turn_fake_001", "completed", final, str(path), "")
            report, handoff, error = read_episode_result(result)
            self.assertIn("solo", error)
            self.assertEqual(handoff["status"], "error")
            self.assertIn("Integration result", report)
            payload["handoff"]["status"] = "needs_user"
            payload["handoff"]["needs_user_input"] = True
            payload["handoff"]["completion_assessment"]["goal_reached"] = False
            result.final_text = json.dumps(payload)
            path.write_text("", encoding="utf-8")
            self.assertIsNone(read_episode_result(result)[2])


if __name__ == "__main__":
    unittest.main()
