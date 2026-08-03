from __future__ import annotations

import json
import unittest

from jam.handoff import (
    HandoffError,
    fallback_error_handoff,
    normalize_handoff,
    parse_structured_response,
)


def valid_payload() -> dict:
    return {
        "report_markdown": "# Result\n\nThe implementation draft and validation result.",
        "handoff": {
            "status": "progress",
            "summary": "Implemented the first bounded slice.",
            "progress_score": 0.6,
            "task_profile": "engineering",
            "profile_reason": "The episode changed code and tests.",
            "strategy_used": "builder_reviewer",
            "strategy_reason": "One writer plus independent review limited write contention.",
            "completed_actions": ["Implemented the parser."],
            "decisions": [
                {
                    "decision": "Keep the public API backward compatible.",
                    "rationale": "Existing callers depend on it.",
                    "status": "accepted",
                }
            ],
            "state_updates": [
                {
                    "id": "REQ-1",
                    "kind": "acceptance_criterion",
                    "statement": "Legacy inputs remain accepted.",
                    "status": "validated",
                    "evidence_refs": ["tests/test_parser.py"],
                    "confidence": "high",
                }
            ],
            "deliverables": [
                {
                    "name": "Parser update",
                    "type": "code",
                    "location": "src/parser.py",
                    "description": "Backward-compatible parser implementation.",
                    "status": "verified",
                }
            ],
            "validation": [
                {
                    "check": "Focused parser tests",
                    "result": "passed",
                    "evidence_refs": ["pytest tests/test_parser.py"],
                }
            ],
            "blockers": [],
            "risks": [],
            "artifacts": [],
            "open_items": ["Run the wider integration suite."],
            "next_options": [
                {
                    "objective": "Run and fix the integration suite.",
                    "task_profile": "engineering",
                    "strategy": "execute_validate",
                    "expected_value": 0.8,
                    "reason": "It verifies compatibility across the project.",
                }
            ],
            "recommended_next_option": 0,
            "needs_user_input": False,
            "user_question": None,
            "completion_assessment": {
                "goal_reached": False,
                "progress_plateau": False,
                "reason": "Integration verification remains.",
            },
            "boundary_flags": [],
        },
    }


class HandoffTests(unittest.TestCase):
    def test_parses_fenced_json(self) -> None:
        text = "```json\n" + json.dumps(valid_payload()) + "\n```"
        report, handoff = parse_structured_response(text)
        self.assertIn("implementation", report)
        self.assertEqual(handoff["task_profile"], "engineering")
        self.assertEqual(handoff["recommended_next_option"], 0)
        self.assertEqual(handoff["next_options"][0]["expected_value"], 0.8)

    def test_extracts_json_embedded_in_prose(self) -> None:
        text = "Preface that should be ignored.\n" + json.dumps(valid_payload()) + "\nTrailing text."
        report, handoff = parse_structured_response(text)
        self.assertTrue(report.startswith("# Result"))
        self.assertEqual(handoff["strategy_used"], "builder_reviewer")

    def test_normalize_clamps_scores_and_discards_bad_options(self) -> None:
        handoff = normalize_handoff(
            {
                "progress_score": 2.7,
                "task_profile": "docs",
                "strategy_used": "producer-critic",
                "next_options": [
                    {"objective": "Useful", "expected_value": -1},
                    {"objective": "", "expected_value": 1},
                    "not an object",
                ],
                "recommended_next_option": 2,
                "completion_assessment": "bad",
            }
        )
        self.assertEqual(handoff["progress_score"], 1.0)
        self.assertEqual(handoff["task_profile"], "documentation")
        self.assertEqual(handoff["strategy_used"], "producer_critic")
        self.assertEqual(len(handoff["next_options"]), 1)
        self.assertEqual(handoff["next_options"][0]["expected_value"], 0.0)
        self.assertEqual(handoff["next_options"][0]["task_profile"], "documentation")
        self.assertIsNone(handoff["recommended_next_option"])
        self.assertFalse(handoff["completion_assessment"]["goal_reached"])

    def test_legacy_research_handoff_is_upgraded(self) -> None:
        upgraded = normalize_handoff(
            {
                "status": "progress",
                "summary": "Legacy result",
                "established_claims": [
                    {
                        "claim": "Two paths normalize differently.",
                        "evidence_refs": ["src/cache.py:10"],
                        "confidence": "high",
                    }
                ],
                "hypotheses": [
                    {
                        "id": "H-1",
                        "statement": "The mismatch changes cache identity.",
                        "state": "active",
                        "confidence": "medium",
                    }
                ],
                "attempts": ["Traced both paths."],
                "dead_ends": ["JWT parsing was unrelated."],
                "open_questions": ["Can it be reproduced?"],
                "scope_flags": ["Production access would be required."],
                "next_options": [
                    {
                        "objective": "Reproduce locally.",
                        "strategy": "discover_reproduce",
                        "expected_value": 0.9,
                        "reason": "Discriminating test.",
                    }
                ],
                "recommended_next_option": 0,
            }
        )
        self.assertEqual(upgraded["task_profile"], "research")
        self.assertEqual(upgraded["completed_actions"], ["Traced both paths."])
        kinds = {item["kind"] for item in upgraded["state_updates"]}
        self.assertEqual(kinds, {"claim", "hypothesis", "dead_end"})
        self.assertEqual(upgraded["open_items"], ["Can it be reproduced?"])
        self.assertEqual(
            upgraded["boundary_flags"], ["Production access would be required."]
        )
        self.assertEqual(upgraded["next_options"][0]["task_profile"], "research")

    def test_invalid_response_raises(self) -> None:
        with self.assertRaises(HandoffError):
            parse_structured_response("There is no structured response here.")
        with self.assertRaises(HandoffError):
            parse_structured_response('{"report_markdown": "missing handoff"}')

    def test_fallback_requests_review(self) -> None:
        handoff = fallback_error_handoff("bad response")
        self.assertEqual(handoff["status"], "error")
        self.assertEqual(handoff["task_profile"], "general")
        self.assertTrue(handoff["needs_user_input"])
        self.assertIn("bad response", handoff["summary"])
        self.assertEqual(handoff["blockers"], ["bad response"])


if __name__ == "__main__":
    unittest.main()
