from __future__ import annotations

import json
import os
import re
import secrets
import signal
import string
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def epoch_now() -> float:
    return time.time()


def json_dumps(value: Any, *, pretty: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=pretty,
    )


def json_loads_or(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def slugify(value: str, *, fallback: str = "campaign", max_length: int = 48) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or fallback)[:max_length].rstrip("-")


def new_campaign_id(name: str | None = None) -> str:
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = secrets.token_hex(3)
    prefix = slugify(name or "jam", max_length=28)
    return f"{prefix}-{date}-{suffix}"


def new_id(prefix: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    token = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{prefix}-{token}"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def truncate_text(text: str, max_chars: int, *, marker: str = "\n…[truncated]…\n") -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= len(marker) + 32:
        return text[:max_chars]
    head = int(max_chars * 0.72)
    tail = max_chars - head - len(marker)
    return text[:head] + marker + text[-tail:]


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return default


def process_is_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        if os.name == "nt":
            # tasklist is available on supported Windows versions and avoids
            # requiring third-party packages.
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return str(pid) in result.stdout and "No tasks" not in result.stdout
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def terminate_process(pid: int | None) -> bool:
    if not process_is_alive(pid):
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def normalize_paths(paths: Iterable[str | Path]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in paths:
        try:
            value = str(Path(item).expanduser().resolve())
        except OSError:
            value = str(Path(item).expanduser().absolute())
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
