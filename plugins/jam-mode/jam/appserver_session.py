from __future__ import annotations

from typing import Any

from .appserver_transport import AppServerError


class AppServerSessionMixin:
    def list_models(
        self,
        *,
        include_hidden: bool = False,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the account/client model catalog using the stable ``model/list`` API."""

        data: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "limit": max(1, min(int(page_size), 500)),
                "includeHidden": bool(include_hidden),
            }
            if cursor:
                params["cursor"] = cursor
            result = self.request("model/list", params, timeout=120)
            page = result.get("data") or []
            if not isinstance(page, list):
                raise AppServerError(f"model/list returned invalid data: {result!r}")
            data.extend(item for item in page if isinstance(item, dict))
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)
            if cursor in seen_cursors:
                raise AppServerError("model/list returned a repeated pagination cursor.")
            seen_cursors.add(cursor)
        return data

    def start_thread(
        self,
        *,
        cwd: str,
        model: str | None,
        sandbox: str,
        name: str,
    ) -> str:
        sandbox_value = "workspaceWrite" if sandbox == "workspace-write" else "readOnly"
        params: dict[str, Any] = {
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": sandbox_value,
            "serviceName": "jam_mode",
        }
        if model:
            params["model"] = model
        result = self.request("thread/start", params, timeout=120)
        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not thread_id:
            raise AppServerError(f"thread/start returned no thread id: {result!r}")
        try:
            self.request(
                "thread/name/set",
                {"threadId": thread_id, "name": name},
                timeout=30,
            )
        except AppServerError:
            # Naming is cosmetic and may differ across app-server versions.
            pass
        return str(thread_id)
