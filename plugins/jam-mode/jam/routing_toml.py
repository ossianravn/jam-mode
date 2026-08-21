from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _parse_toml_value(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw in {"true", "false"}:
        return raw == "true"
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise RoutingError(f"Invalid quoted TOML value: {raw}") from exc
    if re.fullmatch(r"[-+]?\d+", raw):
        return int(raw)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)", raw):
        return float(raw)
    return raw


def _minimal_toml_load(text: str) -> dict[str, Any]:
    """Parse the small TOML subset emitted by JAM on Python 3.10."""

    root: dict[str, Any] = {}
    current = root
    for number, original in enumerate(text.splitlines(), start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section:
                raise RoutingError(f"Empty TOML section on line {number}.")
            current = root
            for part in section.split("."):
                key = part.strip()
                if not key:
                    raise RoutingError(f"Invalid TOML section on line {number}.")
                child = current.setdefault(key, {})
                if not isinstance(child, dict):
                    raise RoutingError(f"TOML section conflicts with a value on line {number}.")
                current = child
            continue
        if "=" not in line:
            raise RoutingError(f"Invalid TOML assignment on line {number}: {original}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise RoutingError(f"Empty TOML key on line {number}.")
        current[key] = _parse_toml_value(raw_value)
    return root


def _read_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return _minimal_toml_load(text)
    try:
        value = tomllib.loads(text)
    except Exception as exc:
        raise RoutingError(f"Invalid JAM routing configuration at {path}: {exc}") from exc
    return value if isinstance(value, dict) else {}


def _toml_string(value: str) -> str:
    # JSON quoted strings are valid TOML basic strings for these values.
    return json.dumps(value, ensure_ascii=False)
