from __future__ import annotations

import unittest

from jam.appserver import AppServerClient
from jam.appserver_transport import AppServerError


class AppServerProtocolTests(unittest.TestCase):
    def _handled(self, method: str) -> dict:
        client = object.__new__(AppServerClient)
        sent: list[dict] = []
        client._write = sent.append  # type: ignore[method-assign]
        client._handle_server_request({"id": 7, "method": method, "params": {}})
        self.assertEqual(len(sent), 1)
        return sent[0]

    def test_declines_approval_requests(self) -> None:
        message = self._handled("item/commandExecution/requestApproval")
        self.assertEqual(message["result"], {"decision": "decline"})

    def test_returns_empty_answers_for_user_input(self) -> None:
        message = self._handled("item/tool/requestUserInput")
        self.assertEqual(message["result"], {"answers": {}})

    def test_cancels_mcp_elicitation(self) -> None:
        message = self._handled("mcpServer/elicitation/request")
        self.assertEqual(message["result"], {"action": "cancel", "content": None})

    def test_supplies_external_current_time(self) -> None:
        message = self._handled("currentTime/read")
        self.assertIsInstance(message["result"]["currentTimeAt"], int)

    def test_model_list_paginates(self) -> None:
        client = object.__new__(AppServerClient)
        calls: list[tuple[str, dict]] = []

        def request(method: str, params: dict, timeout: float = 0) -> dict:
            calls.append((method, dict(params)))
            if len(calls) == 1:
                return {"data": [{"id": "model-a"}], "nextCursor": "next"}
            return {"data": [{"id": "model-b"}], "nextCursor": None}

        client.request = request  # type: ignore[method-assign]
        models = client.list_models(include_hidden=True, page_size=25)
        self.assertEqual([item["id"] for item in models], ["model-a", "model-b"])
        self.assertEqual(calls[0][0], "model/list")
        self.assertEqual(calls[0][1]["includeHidden"], True)
        self.assertEqual(calls[1][1]["cursor"], "next")

    def _thread_start_params(self, sandbox: str) -> dict:
        client = object.__new__(AppServerClient)
        calls: list[tuple[str, dict]] = []

        def request(method: str, params: dict, timeout: float = 0) -> dict:
            calls.append((method, dict(params)))
            if method == "thread/start":
                return {"thread": {"id": "thread-1"}}
            return {}

        client.request = request  # type: ignore[method-assign]
        client.start_thread(
            cwd="C:\\bounded-workspace",
            model=None,
            sandbox=sandbox,
            name="Bounded thread",
        )
        self.assertEqual(calls[0][0], "thread/start")
        return calls[0][1]

    def test_thread_start_uses_permission_profiles(self) -> None:
        expected_profiles = {
            "read-only": ":read-only",
            "workspace-write": ":workspace",
        }
        for sandbox, profile in expected_profiles.items():
            with self.subTest(sandbox=sandbox):
                params = self._thread_start_params(sandbox)
                self.assertEqual(params["permissions"], profile)
                self.assertNotIn("sandbox", params)

    def test_transport_error_response_raises_app_server_error(self) -> None:
        client = object.__new__(AppServerClient)
        client._next_id = 1
        client._write = lambda message: None  # type: ignore[method-assign]
        client._read_message = lambda **kwargs: {  # type: ignore[method-assign]
            "id": 1,
            "error": {"code": -32602, "message": "invalid params"},
        }
        client._pending_notifications = []

        with self.assertRaises(AppServerError) as raised:
            client.request("thread/start", {})
        self.assertIn("app-server thread/start failed", str(raised.exception))
        self.assertIn("invalid params", str(raised.exception))

    def test_turn_error_notification_is_serialized(self) -> None:
        client = object.__new__(AppServerClient)
        client._pending_notifications = [
            {
                "method": "error",
                "params": {"error": {"code": "episode_failed"}},
            },
            {
                "method": "turn/completed",
                "params": {"turn": {"id": "turn-1", "status": "failed"}},
            },
        ]
        client.request = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "turn": {"id": "turn-1", "status": "inProgress"}
        }

        result = client.run_turn(
            thread_id="thread-1",
            prompt="Stay inside the workspace.",
            cwd="C:\\bounded-workspace",
            model=None,
            effort=None,
            sandbox="read-only",
            allow_network=False,
            timeout_seconds=5,
        )

        self.assertEqual(result[1], "failed")
        self.assertIn('"code": "episode_failed"', result[3] or "")

    def _turn_start_params(self, sandbox: str, *, allow_network: bool) -> dict:
        client = object.__new__(AppServerClient)
        client._pending_notifications = [
            {
                "method": "turn/completed",
                "params": {"turn": {"id": "turn-1", "status": "completed"}},
            }
        ]
        calls: list[tuple[str, dict]] = []

        def request(method: str, params: dict, timeout: float = 0) -> dict:
            calls.append((method, dict(params)))
            return {"turn": {"id": "turn-1", "status": "inProgress"}}

        client.request = request  # type: ignore[method-assign]
        client.run_turn(
            thread_id="thread-1",
            prompt="Stay inside the workspace.",
            cwd="C:\\bounded-workspace",
            model=None,
            effort=None,
            sandbox=sandbox,
            allow_network=allow_network,
            timeout_seconds=5,
        )
        self.assertEqual(calls[0][0], "turn/start")
        return calls[0][1]

    def test_workspace_write_uses_restricted_permission_profile(self) -> None:
        params = self._turn_start_params("workspace-write", allow_network=False)
        self.assertEqual(params["permissions"], ":workspace")
        self.assertNotIn("sandboxPolicy", params)

    def test_read_only_uses_restricted_permission_profile(self) -> None:
        params = self._turn_start_params("read-only", allow_network=False)
        self.assertEqual(params["permissions"], ":read-only")
        self.assertNotIn("sandboxPolicy", params)

    def test_network_access_uses_current_sandbox_policy_shape(self) -> None:
        params = self._turn_start_params("read-only", allow_network=True)
        self.assertEqual(
            params["sandboxPolicy"],
            {
                "type": "readOnly",
                "networkAccess": True,
            },
        )
        self.assertNotIn("permissions", params)


if __name__ == "__main__":
    unittest.main()
