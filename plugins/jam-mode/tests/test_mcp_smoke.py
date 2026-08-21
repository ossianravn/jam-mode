from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER = PLUGIN_ROOT / "mcp" / "jam_mcp.py"


class McpSmokeTests(unittest.TestCase):
    def test_child_server_hides_mutating_tools_and_handles_calls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = os.environ.copy()
            env.update(
                {
                    "CODEX_HOME": str(root / "codex"),
                    "JAM_HOME": str(root / "jam"),
                    "JAM_CHILD_SESSION": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            process = subprocess.Popen(
                [sys.executable, str(SERVER)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=PLUGIN_ROOT,
            )
            assert process.stdin is not None
            assert process.stdout is not None

            def request(message: dict) -> dict:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                raw = process.stdout.readline()
                self.assertTrue(raw, "MCP server closed without a response")
                return json.loads(raw)

            initialized = request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                }
            )
            self.assertEqual(initialized["result"]["serverInfo"]["name"], "jam-mode")
            self.assertEqual(initialized["result"]["serverInfo"]["version"], "0.3.0")
            self.assertIn("task-general", initialized["result"]["instructions"])
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            )
            process.stdin.flush()

            tools = request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            names = {item["name"] for item in tools["result"]["tools"]}
            self.assertIn("jam_status", names)
            self.assertIn("jam_doctor", names)
            self.assertIn("jam_model_routing", names)
            self.assertIn("jam_list_models", names)
            self.assertNotIn("jam_configure_model_routing", names)
            self.assertNotIn("jam_refresh_campaign_routing", names)
            self.assertNotIn("jam_start_campaign", names)
            self.assertNotIn("jam_resume_campaign", names)

            ping = request({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}})
            self.assertEqual(ping["result"], {})

            listing = request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "jam_list_campaigns", "arguments": {}},
                }
            )
            self.assertFalse(listing["result"]["isError"])
            self.assertEqual(listing["result"]["structuredContent"]["campaigns"], [])

            unknown = request({"jsonrpc": "2.0", "id": 5, "method": "unknown/method"})
            self.assertEqual(unknown["error"]["code"], -32601)

            process.stdin.close()
            return_code = process.wait(timeout=10)
            stderr = process.stderr.read() if process.stderr else ""
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            self.assertEqual(return_code, 0, stderr)

    def test_parent_server_exposes_campaign_routing_controls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = os.environ.copy()
            env.update(
                {
                    "CODEX_HOME": str(root / "codex"),
                    "JAM_HOME": str(root / "jam"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            env.pop("JAM_CHILD_SESSION", None)
            process = subprocess.Popen(
                [sys.executable, str(SERVER)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=PLUGIN_ROOT,
            )
            assert process.stdin is not None
            assert process.stdout is not None

            def request(message: dict) -> dict:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                raw = process.stdout.readline()
                self.assertTrue(raw, "MCP server closed without a response")
                return json.loads(raw)

            request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                }
            )
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            )
            process.stdin.flush()
            response = request(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            )
            tools = {item["name"]: item for item in response["result"]["tools"]}
            self.assertIn("jam_configure_model_routing", tools)
            self.assertIn("jam_refresh_campaign_routing", tools)
            configure = tools["jam_configure_model_routing"]["inputSchema"]["properties"]
            self.assertIn("campaign_id", configure)
            self.assertIn("reset", configure)
            self.assertNotIn(
                "parent",
                configure["role_models"]["properties"],
            )
            self.assertNotIn(
                "parent",
                configure["role_efforts"]["properties"],
            )
            refresh = tools["jam_refresh_campaign_routing"]["inputSchema"]
            self.assertIn("campaign_id", refresh["required"])

            process.stdin.close()
            return_code = process.wait(timeout=10)
            stderr = process.stderr.read() if process.stderr else ""
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            self.assertEqual(return_code, 0, stderr)


if __name__ == "__main__":
    unittest.main()
