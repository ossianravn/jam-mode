from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Iterable

from .paths import jam_home_path
from .routing_catalog import normalize_catalog
from .routing_normalize import normalize_validation_mode
from .routing_resolve import resolve_routing


def model_catalog_snapshot(
    catalog_entries: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return normalize_catalog(catalog_entries or [])


def fetch_installed_model_catalog(
    *, include_hidden: bool = True
) -> list[dict[str, Any]]:
    """Read the current account/client model catalog through `codex app-server`."""

    from .appserver import AppServerClient  # Lazy import avoids prompt/appserver cycles.

    import tempfile

    state_home = jam_home_path()
    if state_home.exists():
        log_dir = state_home / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = log_dir / "model-catalog.stderr.log"
        with AppServerClient(stderr_path=stderr_path) as client:
            return client.list_models(include_hidden=include_hidden)

    with tempfile.TemporaryDirectory(prefix="jam-model-catalog-") as temp_dir:
        stderr_path = Path(temp_dir) / "app-server.stderr.log"
        with AppServerClient(stderr_path=stderr_path) as client:
            return client.list_models(include_hidden=include_hidden)


def resolve_requested_with_installed_catalog(
    requested: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation = normalize_validation_mode(requested.get("validation"))
    if validation == "off":
        resolved = resolve_routing(requested, catalog_entries=[])
        return resolved, []
    try:
        raw_catalog = fetch_installed_model_catalog(include_hidden=True)
    except Exception as exc:
        resolved = resolve_routing(
            requested,
            catalog_entries=[],
            catalog_error=f"{type(exc).__name__}: {exc}",
        )
        return resolved, []
    snapshot = model_catalog_snapshot(raw_catalog)
    resolved = resolve_routing(requested, catalog_entries=raw_catalog)
    return resolved, snapshot
