from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jam.context import build_campaign_ledger, build_context_pack
from jam.handoff import normalize_handoff, public_handoff
from jam.handoff_fields import (
    EXPLICIT_ID_ORIGIN,
    GENERATED_ID_ORIGIN,
    STATE_ID_ORIGIN_FIELD,
)
from jam.store import Store, StoreError


def _campaign(store: Store, workspace: Path, campaign_id: str = "ledger") -> dict:
    return store.create_campaign(
        {
            "id": campaign_id,
            "name": campaign_id,
            "objective": "Verify state-ledger semantics.",
            "workspace": str(workspace),
            "operating_boundaries": {"resources": [str(workspace)]},
        }
    )


def _state(statement: str, *, state_id: str | None = None) -> dict:
    value = {
        "kind": "claim",
        "statement": statement,
        "status": "active",
        "evidence_refs": [],
        "confidence": "medium",
    }
    if state_id is not None:
        value["id"] = state_id
    return value


def _handoff(*updates: dict) -> dict:
    return {
        "status": "progress",
        "summary": "State updated.",
        "state_updates": list(updates),
    }


class StateLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.store = Store(self.root / "jam.db")
        self.campaign = _campaign(self.store, self.workspace)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _finish(self, *updates: dict) -> dict:
        episode = self.store.create_episode(
            self.campaign["id"],
            objective="Update state",
            strategy_hint="solo",
        )
        return self.store.finish_episode(
            episode["id"],
            status="completed",
            turn_status="completed",
            final_text="{}",
            handoff=_handoff(*updates),
        )

    def test_explicit_ids_replace_while_generated_ids_remain_episode_local(self) -> None:
        self._finish(_state("Explicit old", state_id="state-1"))
        self._finish(_state("Generated compatibility state"))
        self._finish(_state("Explicit new", state_id="state-1"))

        ledger = build_campaign_ledger(self.store, self.campaign["id"])
        statements = [item["statement"] for item in ledger["state_updates"]]
        self.assertEqual(
            statements,
            ["Generated compatibility state", "Explicit new"],
        )
        self.assertEqual(
            ledger["state_by_kind"]["claim"],
            ledger["state_updates"],
        )
        context = build_context_pack(
            self.store,
            self.store.get_campaign(self.campaign["id"]),
            "Continue",
        )
        self.assertNotIn(
            STATE_ID_ORIGIN_FIELD,
            context["previous_episode"]["handoff"]["state_updates"][0],
        )
        self.assertTrue(
            all(
                STATE_ID_ORIGIN_FIELD not in item
                for item in context["campaign_ledger"]["state_updates"]
            )
        )

    def test_last_update_order_is_applied_before_the_240_record_cap(self) -> None:
        updates = [_state(f"State {index}", state_id=f"S-{index}") for index in range(241)]
        updates.append(_state("State zero revised last", state_id="S-0"))
        self._finish(*updates)

        ledger = build_campaign_ledger(self.store, self.campaign["id"])
        ids = [item["id"] for item in ledger["state_updates"]]
        self.assertEqual(len(ids), 240)
        self.assertNotIn("S-1", ids)
        self.assertEqual(ids[-1], "S-0")
        self.assertEqual(ledger["state_updates"][-1]["statement"], "State zero revised last")

    def test_normalizer_preserves_only_trusted_internal_provenance(self) -> None:
        explicit = normalize_handoff(_handoff(_state("Explicit", state_id="state-1")))
        generated = normalize_handoff(_handoff(_state("Generated")))
        self.assertEqual(
            explicit["state_updates"][0][STATE_ID_ORIGIN_FIELD],
            EXPLICIT_ID_ORIGIN,
        )
        self.assertEqual(
            generated["state_updates"][0][STATE_ID_ORIGIN_FIELD],
            GENERATED_ID_ORIGIN,
        )

        injected = _state("Injected", state_id="state-1")
        injected[STATE_ID_ORIGIN_FIELD] = GENERATED_ID_ORIGIN
        untrusted = normalize_handoff(_handoff(injected))
        trusted = normalize_handoff(_handoff(injected), preserve_internal=True)
        self.assertEqual(
            untrusted["state_updates"][0][STATE_ID_ORIGIN_FIELD],
            EXPLICIT_ID_ORIGIN,
        )
        self.assertEqual(
            trusted["state_updates"][0][STATE_ID_ORIGIN_FIELD],
            GENERATED_ID_ORIGIN,
        )
        self.assertNotIn(
            STATE_ID_ORIGIN_FIELD,
            public_handoff(trusted)["state_updates"][0],
        )


class StateProvenanceMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _legacy_episode(self, database: Path, *, mismatch: bool = False) -> str:
        store = Store(database)
        campaign = _campaign(store, self.workspace, database.stem)
        episode = store.create_episode(
            campaign["id"], objective="Legacy", strategy_hint="solo"
        )
        raw_handoff = _handoff(_state("Raw generated state"))
        stored_handoff = _handoff(
            _state("Stored mismatch" if mismatch else "Raw generated state")
        )
        store.finish_episode(
            episode["id"],
            status="completed",
            turn_status="completed",
            final_text="{}",
            handoff=stored_handoff,
        )
        raw_payload = {"report_markdown": "# Legacy", "handoff": raw_handoff}
        old_normalized = public_handoff(normalize_handoff(stored_handoff))
        with store.connection(immediate=True) as conn:
            conn.execute(
                "UPDATE episodes SET final_text = ?, handoff = ? WHERE id = ?",
                (
                    json.dumps(raw_payload),
                    json.dumps(old_normalized),
                    episode["id"],
                ),
            )
            conn.execute("PRAGMA user_version = 1")
        return episode["id"]

    def test_migration_reconstructs_generated_id_provenance(self) -> None:
        database = self.root / "migrated.db"
        episode_id = self._legacy_episode(database)
        migrated = Store(database).get_episode(episode_id)
        self.assertEqual(
            migrated["handoff"]["state_updates"][0][STATE_ID_ORIGIN_FIELD],
            GENERATED_ID_ORIGIN,
        )

    def test_migration_fails_with_episode_context_on_mismatch(self) -> None:
        database = self.root / "mismatch.db"
        episode_id = self._legacy_episode(database, mismatch=True)
        with self.assertRaises(StoreError) as raised:
            Store(database)
        self.assertIn(episode_id, str(raised.exception))
        self.assertIn("does not match", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
