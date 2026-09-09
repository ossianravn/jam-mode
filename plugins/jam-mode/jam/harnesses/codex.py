from __future__ import annotations

from ..appserver import run_episode_turn
from ..routing import fetch_installed_model_catalog, model_catalog_snapshot
from ..service_doctor import doctor
from .types import HarnessRequest, HarnessResult


class Adapter:
    def inspect(self) -> dict:
        result = doctor()
        return {"harness": "codex", "available": result["ok"], "supported": result["ok"],
                "checks": result["checks"], "limitations": []}

    def models(self) -> dict:
        models = model_catalog_snapshot(fetch_installed_model_catalog(include_hidden=True))
        return {"models": models, "catalog_status": "installed", "warnings": []}

    def run(self, request: HarnessRequest) -> HarnessResult:
        result = run_episode_turn(campaign=request.campaign, episode=request.episode, prompt=request.prompt,
                                  events_path=request.events_path, stderr_path=request.stderr_path,
                                  timeout_seconds=request.timeout_seconds)
        return HarnessResult(result.thread_id, result.status, result.final_text, result.error,
                             result.agent_activity, result.model_events, result.token_usage, result.turn_id)
