from __future__ import annotations

from typing import Any, Iterable

from .routing_defs import EFFORT_ORDER, ROLE_MODEL_PREFERENCES
from .routing_normalize import normalize_effort


def _supported_efforts(entry: dict[str, Any]) -> list[str]:
    raw = (
        entry.get("supportedReasoningEfforts")
        or entry.get("supported_reasoning_efforts")
        or []
    )
    efforts: list[str] = []
    for item in raw:
        value = item.get("reasoningEffort") if isinstance(item, dict) else item
        try:
            normalized = normalize_effort(value)
        except RoutingError:
            continue
        if normalized and normalized not in efforts:
            efforts.append(normalized)
    default = entry.get("defaultReasoningEffort") or entry.get(
        "default_reasoning_effort"
    )
    try:
        default_normalized = normalize_effort(default)
    except RoutingError:
        default_normalized = None
    if default_normalized and default_normalized not in efforts:
        efforts.append(default_normalized)
    return efforts


def normalize_catalog(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or raw.get("model") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        try:
            default_effort = normalize_effort(
                raw.get("defaultReasoningEffort")
                or raw.get("default_reasoning_effort")
            )
        except RoutingError:
            default_effort = None
        normalized.append(
            {
                "id": model_id,
                "model": str(raw.get("model") or model_id),
                "display_name": str(
                    raw.get("displayName") or raw.get("display_name") or model_id
                ),
                "hidden": bool(raw.get("hidden", False)),
                "is_default": bool(raw.get("isDefault") or raw.get("is_default")),
                "default_effort": default_effort,
                "supported_efforts": _supported_efforts(raw),
                "input_modalities": list(
                    raw.get("inputModalities")
                    or raw.get("input_modalities")
                    or ["text", "image"]
                ),
            }
        )
    return normalized


def _catalog_map(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in catalog:
        for candidate in (entry.get("id"), entry.get("model")):
            value = str(candidate or "").strip()
            if value:
                result[value] = entry
    return result


def _default_model(catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    visible = [entry for entry in catalog if not entry.get("hidden")]
    for entry in visible:
        if entry.get("is_default"):
            return entry
    if visible:
        return visible[0]
    return catalog[0] if catalog else None


def _fallback_model_for_role(
    role: str,
    catalog: list[dict[str, Any]],
    catalog_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for model_id in ROLE_MODEL_PREFERENCES.get(role, ()):
        if model_id in catalog_by_id and not catalog_by_id[model_id].get("hidden"):
            return catalog_by_id[model_id]
    return _default_model(catalog)


def _nearest_effort(
    requested: str, supported: list[str], default: str | None
) -> str | None:
    if requested in supported:
        return requested
    if not supported:
        return default
    requested_index = EFFORT_ORDER.index(requested)
    normalized_supported = [item for item in supported if item in EFFORT_ORDER]
    ranked = sorted(
        normalized_supported,
        key=lambda item: (
            # Prefer the nearest supported effort; on a tie prefer lower usage.
            abs(EFFORT_ORDER.index(item) - requested_index),
            EFFORT_ORDER.index(item) > requested_index,
            EFFORT_ORDER.index(item),
        ),
    )
    return ranked[0] if ranked else default
