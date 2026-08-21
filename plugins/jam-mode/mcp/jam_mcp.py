#!/usr/bin/env python3
"""Dependency-free stdio MCP server for the JAM Mode Codex plugin."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
try:
    sys.path.remove(str(PLUGIN_ROOT))
except ValueError:
    pass
sys.path.insert(0, str(PLUGIN_ROOT))

from jam import __version__  # noqa: E402
from jam.store import CampaignNotFound, StoreError  # noqa: E402
from mcp.invoke import _invoke  # noqa: E402
from mcp.settings import (  # noqa: E402
    CHILD_SESSION,
    DEFAULT_PROTOCOL_VERSION,
    SERVER_NAME,
    ToolFailure,
)
from mcp.tool_catalog import READ_ONLY_CHILD_TOOLS, TOOLS  # noqa: E402


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _result(request_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str, data: Any | None = None) -> None:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    _send({"jsonrpc": "2.0", "id": request_id, "error": payload})


def _tools_for_host() -> list[dict[str, Any]]:
    if not CHILD_SESSION:
        return TOOLS
    return [tool for tool in TOOLS if tool["name"] in READ_ONLY_CHILD_TOOLS]


def _handle(message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        requested = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
        instructions = (
            "JAM Mode manages bounded, task-general campaigns across fresh Codex sessions. Require an explicit "
            "objective and workspace. Use conservative local boundaries by default, and require explicit operating "
            "boundaries for networked, security-sensitive, deployment, or other elevated work. Pause is graceful: "
            "the active episode finishes naturally, then no replacement starts. Model routing uses validated "
            "JAM-prefixed custom agents and can be inspected or configured with the routing tools."
        )
        if CHILD_SESSION:
            instructions += " This is a JAM child session; mutating campaign tools are intentionally hidden."
        _result(
            request_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": instructions,
            },
        )
        return
    if method in {"notifications/initialized", "initialized", "notifications/cancelled"}:
        return
    if method == "ping":
        _result(request_id, {})
        return
    if method == "tools/list":
        _result(request_id, {"tools": _tools_for_host()})
        return
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            _result(
                request_id,
                {
                    "isError": True,
                    "content": [{"type": "text", "text": "Tool arguments must be an object."}],
                },
            )
            return
        try:
            payload, text = _invoke(name, arguments)
            _result(
                request_id,
                {
                    "structuredContent": payload,
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            )
        except (ValueError, StoreError, CampaignNotFound, ToolFailure, OSError) as exc:
            _result(
                request_id,
                {
                    "structuredContent": {"error": str(exc), "tool": name},
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        except Exception as exc:  # defensive server boundary
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            _result(
                request_id,
                {
                    "structuredContent": {"error": str(exc), "tool": name},
                    "content": [{"type": "text", "text": f"Unexpected JAM error: {exc}"}],
                    "isError": True,
                },
            )
        return
    if request_id is not None:
        _error(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object")
            _handle(message)
        except json.JSONDecodeError as exc:
            _error(None, -32700, "Parse error", str(exc))
        except Exception as exc:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            request_id = message.get("id") if isinstance(locals().get("message"), dict) else None
            _error(request_id, -32603, "Internal error", str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
