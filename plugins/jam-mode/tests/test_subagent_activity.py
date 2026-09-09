from __future__ import annotations

import copy
import unittest

from jam.appserver import AppServerClient
from jam.collaboration import CollaborationError, verify_contributions
from tests.collaboration_events import duo_events, event, final_event


PARENT = "thr_fake_001"
CHILDREN = ("thr_explorer", "thr_critic")


def activity(child, kind, *, thread=PARENT, turn="turn_fake_001"):
    return event({
        "type": "subAgentActivity", "id": f"{child}-{kind}", "kind": kind,
        "agentThreadId": child, "agentPath": f"/root/{child.removeprefix('thr_')}",
    }, thread=thread, turn=turn)


def child_result(child, *, turn="child_turn"):
    return [
        event({"type": "agentMessage", "phase": "final_answer", "text": "Independent findings."},
              thread=child, turn=turn),
        {"method": "turn/completed", "params": {
            "threadId": child, "turn": {"id": turn, "status": "completed", "error": None},
        }},
        activity(child, "completed"),
    ]


def modern_events():
    return [activity(child, "started") for child in CHILDREN] + [
        *child_result(CHILDREN[0]), *child_result(CHILDREN[1]),
        event({"type": "collabAgentToolCall", "tool": "wait", "status": "completed",
               "senderThreadId": PARENT, "receiverThreadIds": [], "agentsStates": {}}),
        final_event(),
    ]


class SubagentActivityTests(unittest.TestCase):
    def verify(self, events, *, strategy="duo_independent"):
        verify_contributions(events, thread_id=PARENT, turn_id="turn_fake_001",
                             final_text="parent synthesis", strategy=strategy)

    def test_recorded_event_shape_verifies_and_is_collected(self):
        events = modern_events()
        self.verify(events)
        client = object.__new__(AppServerClient)
        client._pending_notifications = events + [{
            "method": "turn/completed", "params": {
                "threadId": PARENT, "turn": {"id": "turn_fake_001", "status": "completed"},
            },
        }]
        client.request = lambda *args, **kwargs: {"turn": {"id": "turn_fake_001"}}
        result = client.run_turn(thread_id=PARENT, prompt="Research.", cwd=".", model=None,
                                 effort=None, sandbox="read-only", allow_network=False,
                                 timeout_seconds=5)
        self.assertEqual(result[2], "parent synthesis")
        recorded = [i for i in result[4] if i["type"] == "subAgentActivity"]
        self.assertEqual([(i["agentThreadId"], i["kind"]) for i in recorded], [
            (CHILDREN[0], "started"), (CHILDREN[1], "started"),
            (CHILDREN[0], "completed"), (CHILDREN[1], "completed"),
        ])
        self.assertTrue(all(i["threadId"] == PARENT for i in recorded))

    def test_completion_requires_result_success_and_parent_delivery(self):
        for missing in ("text", "final_phase", "turn_success", "turn_identity", "delivery"):
            events = modern_events()
            if missing == "text":
                events[5]["params"]["item"]["text"] = " "
            elif missing == "final_phase":
                events[5]["params"]["item"]["phase"] = "commentary"
            elif missing == "turn_success":
                events[6]["params"]["turn"]["status"] = "failed"
            elif missing == "turn_identity":
                events[6]["params"]["turn"]["id"] = "another_turn"
            else:
                events.pop(7)
            with self.subTest(missing=missing), self.assertRaises(CollaborationError):
                self.verify(events)

    def test_only_current_parent_direct_children_before_final_count(self):
        for invalid in ("other_parent", "other_turn", "grandchild", "duplicate", "late"):
            events = modern_events()
            if invalid in {"other_parent", "grandchild"}:
                events[1]["params"]["threadId"] = CHILDREN[0] if invalid == "grandchild" else "other"
            elif invalid == "other_turn":
                events[1]["params"]["turnId"] = "old_turn"
            elif invalid == "duplicate":
                events[5:8] = copy.deepcopy(events[2:5])
            else:
                events.insert(5, events.pop())
            with self.subTest(invalid=invalid), self.assertRaises(CollaborationError):
                self.verify(events)

    def test_informational_messages_preserve_completed_results(self):
        messages = [
            activity(CHILDREN[1], "interacted"),
            event({"type": "collabAgentToolCall", "tool": "sendMessage", "status": "completed",
                   "senderThreadId": PARENT, "receiverThreadIds": [CHILDREN[1]]}),
        ]
        for build_events, message in ((modern_events, messages[0]), (modern_events, messages[1]),
                                      (lambda: duo_events() + [final_event()], messages[1])):
            with self.subTest(message=message, modern=build_events is modern_events):
                events = build_events()[:-1] + [message]
                self.verify(events + [final_event()])
                new_turn = {"method": "turn/started", "params": {
                    "threadId": CHILDREN[1], "turn": {"id": "followup", "status": "inProgress"},
                }}
                with self.assertRaises(CollaborationError):
                    self.verify(events + [new_turn, final_event()])

    def test_new_child_turn_invalidates_previous_result_until_new_completion(self):
        events = modern_events()[:-1]
        events.append(activity(CHILDREN[1], "interacted"))
        events.append({"method": "turn/started", "params": {
            "threadId": CHILDREN[1], "turn": {"id": "followup", "status": "inProgress"},
        }})
        with self.assertRaises(CollaborationError):
            self.verify(events + [activity(CHILDREN[1], "completed"), final_event()])
        self.verify(events + child_result(CHILDREN[1], turn="followup") + [final_event()])

    def test_duo_must_start_both_before_waiting(self):
        events = modern_events()
        events.insert(1, events.pop(-2))
        with self.assertRaisesRegex(CollaborationError, "before waiting"):
            self.verify(events)
        self.verify(events, strategy="builder_reviewer")


if __name__ == "__main__":
    unittest.main()
