from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from .types import HarnessAdapter, HarnessError, HarnessRequest

if TYPE_CHECKING:
    from ..appserver import TurnResult

HARNESS_IDS = ("codex", "claude-code", "copilot", "opencode")


def validate_harness(value: str) -> str:
    if value not in HARNESS_IDS:
        raise HarnessError(f"Unknown harness {value!r}; choose one of {', '.join(HARNESS_IDS)}.")
    return value


def get_adapter(harness: str) -> HarnessAdapter:
    name = validate_harness(harness)
    module = import_module(f".{'claude' if name == 'claude-code' else name}", __package__)
    return module.Adapter()


def list_harnesses() -> dict:
    results = []
    for name in HARNESS_IDS:
        try:
            details = get_adapter(name).inspect()
        except (HarnessError, OSError, ValueError) as exc:
            details = {"available": False, "supported": False, "limitations": [str(exc)]}
        results.append({**details, "harness": name})
    return {"harnesses": results}


def harness_doctor(harness: str) -> dict:
    if harness == "codex":
        from ..service_doctor import doctor
        return doctor()
    details = get_adapter(harness).inspect()
    checks = [{"name": "executable", "ok": bool(details.get("available")),
               "detail": details.get("executable") or "not found"},
              {"name": "adapter_capabilities", "ok": bool(details.get("supported")),
               "detail": "; ".join(details.get("limitations") or []) or "supported"}]
    return {"harness": harness, "ok": all(c["ok"] for c in checks), "checks": checks, "details": details}


def run_episode_turn(**kwargs) -> TurnResult:
    from ..appserver import TurnResult
    request = HarnessRequest(**kwargs)
    harness = request.campaign.get("harness", "codex")
    result = get_adapter(harness).run(request)
    return TurnResult(result.session_id, result.turn_id, result.status, result.final_text,
                      str(request.events_path), str(request.stderr_path), result.error,
                      result.agent_activity, result.model_events, result.token_usage)
