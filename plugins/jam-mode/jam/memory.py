from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .paths import codex_home_path
from .util import normalize_paths, truncate_text


_TEXT_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".rst",
    ".csv",
}
_SKIP_NAMES = {
    "auth.json",
    "credentials.json",
    "secrets.json",
    ".env",
    ".env.local",
    "id_rsa",
    "id_ed25519",
}
_SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def _terms(*values: str) -> set[str]:
    words: set[str] = set()
    for value in values:
        for word in re.findall(r"[a-zA-Z0-9_\-]{3,}", value.lower()):
            if word not in {
                "the",
                "and",
                "for",
                "with",
                "from",
                "that",
                "this",
                "into",
                "then",
                "should",
                "campaign",
            }:
                words.add(word)
    return words


def _candidate_files(roots: list[str], *, max_files: int = 1000) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for root_value in roots:
        root = Path(root_value).expanduser()
        if not root.exists():
            continue
        try:
            resolved_root = root.resolve()
        except (OSError, PermissionError):
            continue
        iterator = [root] if root.is_file() else root.rglob("*")
        for path in iterator:
            if len(result) >= max_files:
                return result
            try:
                resolved_path = path.resolve()
                if root.is_dir() and not resolved_path.is_relative_to(resolved_root):
                    continue
                if not resolved_path.is_file() or resolved_path.suffix.lower() not in _TEXT_SUFFIXES:
                    continue
                names = {path.name.lower(), resolved_path.name.lower()}
                if any(
                    name in _SKIP_NAMES or name.startswith(".env.")
                    for name in names
                ):
                    continue
                parts = {part.lower() for part in (*path.parts, *resolved_path.parts)}
                if parts.intersection(_SKIP_PARTS):
                    continue
                resolved = str(resolved_path)
                if resolved in seen:
                    continue
                seen.add(resolved)
                result.append(resolved_path)
            except (OSError, PermissionError):
                continue
    return result


def _safe_excerpt(path: Path, *, max_chars: int = 12000) -> str:
    try:
        if path.stat().st_size > 2_000_000:
            return "[file omitted: larger than 2 MB]"
        text = path.read_text(encoding="utf-8", errors="replace")
        return truncate_text(text, max_chars)
    except (OSError, PermissionError) as exc:
        return f"[unreadable: {exc}]"


def collect_memories(
    campaign: dict[str, Any], current_objective: str, *, max_excerpt_chars: int = 42000
) -> dict[str, Any]:
    home = codex_home_path()
    roots = normalize_paths(
        [
            home / "memories",
            home / "memories_extensions" / "chronicle",
            *(campaign.get("memory_paths") or []),
        ]
    )
    files = _candidate_files(roots)
    terms = _terms(campaign.get("objective", ""), current_objective)
    inventory: list[dict[str, Any]] = []
    scored: list[tuple[float, float, Path]] = []
    for path in files:
        try:
            stat = path.stat()
            relative_hint = str(path)
            lower_name = relative_hint.lower()
            lexical = sum(4.0 for term in terms if term in lower_name)
            age_days = max(0.0, (time.time() - stat.st_mtime) / 86400.0)
            recency = max(0.0, 2.0 - (age_days / 90.0))
            # Filename relevance dominates. Recency only breaks ties and fades
            # gradually over roughly six months.
            score = lexical + recency
            scored.append((score, stat.st_mtime, path))
            inventory.append(
                {
                    "path": str(path),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
        except OSError:
            continue

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    excerpts: list[dict[str, str]] = []
    remaining = max_excerpt_chars
    for score, _mtime, path in scored[:16]:
        if remaining < 800:
            break
        excerpt = _safe_excerpt(path, max_chars=min(9000, remaining))
        remaining -= len(excerpt)
        excerpts.append({"path": str(path), "score": f"{score:.2f}", "excerpt": excerpt})

    return {
        "roots_considered": roots,
        "inventory_count": len(inventory),
        "inventory": inventory[:500],
        "relevant_excerpts": excerpts,
        "inventory_truncated": len(inventory) > 500,
    }
