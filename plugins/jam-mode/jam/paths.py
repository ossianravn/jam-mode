from __future__ import annotations

import os
import sys
from pathlib import Path


def codex_home_path() -> Path:
    """Return the effective Codex home without creating it."""
    configured = os.environ.get("CODEX_HOME")
    path = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return path.resolve()


def codex_home() -> Path:
    """Return the effective Codex home and ensure it exists."""
    path = codex_home_path()
    path.mkdir(parents=True, exist_ok=True)
    return path


def jam_home_path() -> Path:
    """Return JAM's effective state path without creating it."""
    configured = os.environ.get("JAM_HOME")
    path = Path(configured).expanduser() if configured else codex_home_path() / "jam-mode"
    return path.resolve()


def jam_home() -> Path:
    """Return JAM's writable state directory and ensure its layout exists."""
    path = jam_home_path()
    path.mkdir(parents=True, exist_ok=True)
    (path / "campaigns").mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return jam_home() / "jam.db"


def campaign_dir(campaign_id: str) -> Path:
    path = jam_home() / "campaigns" / campaign_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "episodes").mkdir(parents=True, exist_ok=True)
    return path


def episode_dir(campaign_id: str, number: int) -> Path:
    path = campaign_dir(campaign_id) / "episodes" / f"{number:04d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def python_command() -> list[str]:
    """Return the current interpreter as an argv prefix."""
    return [sys.executable]
