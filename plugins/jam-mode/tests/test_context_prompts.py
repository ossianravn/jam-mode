
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.context import build_context_pack
from jam.prompts import HANDOFF_SCHEMA, render_episode_prompt
from jam.routing import build_requested_routing, resolve_routing
from jam.store import Store


class ContextAndPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex_home = self.root / "codex-home"
        self.jam_home = self.root / "jam-home"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.env = patch.dict(
            os.environ,
            {"CODEX_HOME": str(self.codex_home), "JAM_HOME": str(self.jam_home)},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def _campaign(self, store: Store) -> dict:
        return store.create_campaign(
            {
                "id": "context-campaign",
                "name": "Context campaign",
                "objective": "Implement and document a backward-compatible configuration parser.",
                "task_profile": "adaptive",
                "workspace": str(self.workspace),
                "operating_boundaries": {
                    "resources": ["repository"],
                    "allowed_actions": ["read files", "modify files in the workspace"],
                    "excluded_actions": ["deployment", "external publication"],
                },
                "success_criteria": "Implementation and documentation pass focused validation.",
                "sandbox": "workspace-write",
                "allow_network": False,
                "max_subagents": 2,
                "memory_paths": [],
            }
        )

    def test_context_pack_contains_previous_handoff_transcript_and_generic_ledger(self) -> None:
        store = Store(self.jam_home / "test.db")
        campaign = self._campaign(store)
        episode = store.create_episode(
            campaign["id"],
            objective="Implement the parser core",
            strategy_hint="builder_reviewer",
            task_profile_hint="engineering",
        )
        events = self.root / "events.jsonl"
        messages = [
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "userMessage",
                        "content": [{"type": "text", "text": "Implement the parser core."}],
                    }
                },
            },
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": "Implemented the core and focused tests passed.",
                    }
                },
            },
        ]
        events.write_text("\n".join(json.dumps(item) for item in messages) + "\n", encoding="utf-8")
        store.update_episode(
            episode["id"], events_path=str(events), thread_id="thr-previous"
        )
        handoff = {
            "status": "progress",
            "summary": "Parser core implemented.",
            "progress_score": 0.7,
            "task_profile": "engineering",
            "profile_reason": "Code and tests changed.",
            "strategy_used": "builder_reviewer",
            "strategy_reason": "One writer and one reviewer.",
            "completed_actions": ["Implemented the parser core."],
            "decisions": [],
            "state_updates": [
                {
                    "id": "AC-1",
                    "kind": "acceptance_criterion",
                    "statement": "Legacy aliases remain accepted.",
                    "status": "validated",
                    "evidence_refs": ["tests/test_parser.py"],
                    "confidence": "high",
                }
            ],
            "deliverables": [
                {
                    "name": "Parser core",
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
            "open_items": ["Write migration documentation."],
            "next_options": [],
            "recommended_next_option": None,
            "needs_user_input": False,
            "user_question": None,
            "completion_assessment": {
                "goal_reached": False,
                "progress_plateau": False,
                "reason": "Documentation remains.",
            },
            "boundary_flags": [],
        }
        store.finish_episode(
            episode["id"],
            status="completed",
            turn_status="completed",
            final_text="Structured output",
            handoff=handoff,
        )

        context = build_context_pack(
            store, store.get_campaign(campaign["id"]), "Write migration documentation"
        )
        self.assertEqual(context["previous_episode"]["thread_id"], "thr-previous")
        self.assertEqual(context["previous_episode"]["task_profile"], "engineering")
        self.assertIn(
            "focused tests passed", context["previous_episode"]["transcript_excerpt"]
        )
        ledger = context["campaign_ledger"]
        self.assertEqual(ledger["state_by_kind"]["acceptance_criterion"][0]["confidence"], "high")
        self.assertEqual(ledger["deliverables"][0]["name"], "Parser core")
        self.assertEqual(ledger["profile_history"][0]["task_profile"], "engineering")

        prompt = render_episode_prompt(
            store.get_campaign(campaign["id"]),
            {
                "number": 2,
                "objective": "Write migration documentation",
                "strategy_hint": "producer_critic",
                "task_profile_hint": "documentation",
            },
            context,
        )
        self.assertIn("OPERATING BOUNDARIES — IMMUTABLE", prompt)
        self.assertIn("CAMPAIGN STATE", prompt)
        self.assertNotIn("RESEARCH STATE", prompt)
        self.assertIn("documentation: plan, draft, revise", prompt)
        self.assertIn("You may use at most 2 subagents", prompt)
        self.assertIn("Do not call\nJAM Mode MCP tools", prompt)
        self.assertIn("Write migration documentation", prompt)
        self.assertIn("focused tests passed", prompt)


    def test_episode_prompt_routes_exact_named_agents_and_models(self) -> None:
        store = Store(self.jam_home / "routing-prompt.db")
        campaign = self._campaign(store)
        resolved = resolve_routing(
            build_requested_routing(policy="balanced", validation="off"),
            catalog_entries=[],
        )
        campaign = store.update_campaign(
            campaign["id"],
            model_policy="balanced",
            model_validation="off",
            model=resolved["parent"]["model"],
            effort=resolved["parent"]["effort"],
            resolved_routing=resolved,
            requested_routing=build_requested_routing(
                policy="balanced", validation="off"
            ),
        )
        prompt = render_episode_prompt(
            campaign,
            {
                "number": 1,
                "objective": "Implement the parser and review the result.",
                "strategy_hint": "builder_reviewer",
                "task_profile_hint": "engineering",
            },
            {"campaign_ledger": {}, "previous_episode": None},
        )
        self.assertIn("gpt-5.6-sol · high", prompt)
        self.assertIn("jam_implementer · gpt-5.6-terra · high", prompt)
        self.assertIn("jam_reviewer · gpt-5.6-sol · high", prompt)
        self.assertIn("builder_reviewer: jam_implementer → jam_reviewer", prompt)
        self.assertIn(
            "planner_executor: jam_planner first, then choose exactly one writer",
            prompt,
        )
        self.assertIn(
            "execute_validate: choose exactly one writer "
            "(jam_implementer or jam_producer), then jam_validator",
            prompt,
        )
        self.assertNotIn(
            "planner_executor: jam_planner, jam_implementer, jam_producer",
            prompt,
        )
        self.assertIn("delegate each bounded role to the exact", prompt)
        self.assertIn("There must be no more than one writer", prompt)
        self.assertIn("Child agents must not spawn", prompt)
        self.assertIn("boundary_flags must be empty when", prompt)

    def test_handoff_schema_is_task_general(self) -> None:
        handoff = HANDOFF_SCHEMA["properties"]["handoff"]
        properties = handoff["properties"]
        for field in (
            "task_profile",
            "completed_actions",
            "state_updates",
            "deliverables",
            "validation",
            "boundary_flags",
        ):
            self.assertIn(field, properties)
        self.assertNotIn("established_claims", properties)
        self.assertNotIn("hypotheses", properties)
        self.assertIn("content", properties["task_profile"]["enum"])
        self.assertIn("operations", properties["task_profile"]["enum"])
        self.assertIn("producer_critic", properties["strategy_used"]["enum"])
        self.assertIn(
            "Do not record compliance confirmations",
            properties["boundary_flags"]["description"],
        )


if __name__ == "__main__":
    unittest.main()
