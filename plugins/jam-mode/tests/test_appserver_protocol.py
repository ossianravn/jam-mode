from __future__ import annotations

import unittest

from jam.appserver import AppServerClient


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


if __name__ == "__main__":
    unittest.main()
