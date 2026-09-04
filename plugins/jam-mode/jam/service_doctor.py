from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .paths import codex_home_path, jam_home_path, plugin_root
from .routing import (
    CHILD_ROLES,
    EFFORT_ORDER,
    MODEL_POLICIES,
    MODEL_VALIDATION_MODES,
    inspect_managed_agents,
    load_routing_config,
    routing_config_path,
)


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _codex_command(codex: str, *arguments: str) -> list[str]:
    if os.name == "nt" and Path(codex).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", codex, *arguments]
    return [codex, *arguments]


def doctor() -> dict[str, Any]:
    codex = shutil.which("codex")
    codex_path = codex_home_path()
    state_path = jam_home_path()
    state_probe = state_path if state_path.exists() else _nearest_existing_parent(state_path)
    state_writable = state_probe.is_dir() and os.access(state_probe, os.W_OK)
    state_detail = str(state_path)
    if not state_path.exists():
        state_detail += f" (will be created under {state_probe})"
    agents_path = codex_path / "agents"
    agents_probe = agents_path if agents_path.exists() else _nearest_existing_parent(agents_path)
    try:
        routing_config = load_routing_config(create=False)
        routing_config_ok = True
        routing_detail = (
            f"{routing_config_path()} · {routing_config['policy']} / "
            f"{routing_config['validation']}"
        )
    except Exception as exc:
        routing_config_ok = False
        routing_detail = f"{routing_config_path()}: {exc}"
    checks: list[dict[str, Any]] = [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": sys.version.split()[0],
        },
        {
            "name": "codex_on_path",
            "ok": bool(codex),
            "detail": codex or "not found",
        },
        {
            "name": "codex_home",
            "ok": codex_path.is_dir(),
            "detail": str(codex_path),
        },
        {
            "name": "agents_directory",
            "ok": agents_probe.is_dir() and os.access(agents_probe, os.W_OK),
            "detail": str(agents_path),
        },
        {
            "name": "jam_home",
            "ok": state_writable,
            "detail": state_detail,
        },
        {
            "name": "routing_config",
            "ok": routing_config_ok,
            "detail": routing_detail,
        },
        {
            "name": "plugin_root",
            "ok": (plugin_root() / ".codex-plugin" / "plugin.json").exists(),
            "detail": str(plugin_root()),
        },
    ]
    if codex:
        try:
            result = subprocess.run(
                _codex_command(codex, "features", "list"),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            checks.append(
                {
                    "name": "codex_config",
                    "ok": result.returncode == 0,
                    "detail": (result.stdout or result.stderr).strip()[:500],
                }
            )
        except (OSError, subprocess.SubprocessError) as exc:
            checks.append({"name": "codex_config", "ok": False, "detail": str(exc)})
        try:
            result = subprocess.run(
                _codex_command(codex, "app-server", "--help"),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            checks.append(
                {
                    "name": "app_server",
                    "ok": result.returncode == 0,
                    "detail": (result.stdout or result.stderr).strip()[:500],
                }
            )
        except (OSError, subprocess.SubprocessError) as exc:
            checks.append({"name": "app_server", "ok": False, "detail": str(exc)})
    return {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
        "routing": {
            "policies": list(MODEL_POLICIES),
            "validation_modes": list(MODEL_VALIDATION_MODES),
            "efforts": list(EFFORT_ORDER),
            "roles": list(CHILD_ROLES),
            "managed_agents": inspect_managed_agents(),
        },
    }
