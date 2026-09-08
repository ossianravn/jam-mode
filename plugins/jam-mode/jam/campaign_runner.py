from __future__ import annotations

import sys
import time
import traceback
import uuid
from typing import Any

from .appserver import AppServerError, run_episode_turn
from .context import build_context_pack
from .controller_decisions import (
    _budget_gate,
    _turn_timeout_seconds,
    continuation_decision,
    next_episode_plan,
)
from .controller_reporting import LEASE_TTL_SECONDS, LeaseHeartbeat, _write_campaign_summary
from .episode_result import read_episode_result
from .handoff import fallback_error_handoff
from .lifecycle import RUNNABLE_CAMPAIGN_STATUSES
from .paths import episode_dir
from .prompts import render_episode_prompt
from .routing import RoutingError, ensure_managed_agents
from .store import CampaignNotFound, CampaignNotRunnable, Store, StoreError
from .util import atomic_write, json_dumps, utc_now


def _record_campaign_failure(
    store: Store,
    campaign_id: str,
    error_text: str,
) -> str | None:
    try:
        active_episode = store.active_episode(campaign_id)
        if active_episode is not None:
            store.finish_episode(
                str(active_episode["id"]),
                status="error",
                turn_status="failed",
                final_text="",
                handoff=fallback_error_handoff(error_text),
                error=error_text,
            )
        store.transition_campaign(campaign_id, "error", last_error=error_text)
        _write_campaign_summary(store, campaign_id)
    except Exception as cleanup_error:  # best effort without hiding the root failure
        return f"{type(cleanup_error).__name__}: {cleanup_error}"
    return None


def _settle_non_runnable(store: Store, campaign: dict[str, Any]) -> bool:
    status = str(campaign["status"])
    if status == "stopping_after_current":
        store.transition_campaign(
            campaign["id"], "stopped", completed_at=utc_now()
        )
        return True
    if status == "pausing_after_current":
        store.transition_campaign(campaign["id"], "paused")
        return True
    return status not in RUNNABLE_CAMPAIGN_STATUSES


def run_campaign(campaign_id: str) -> int:
    store = Store()
    token = uuid.uuid4().hex
    if not store.acquire_lease(campaign_id, token, ttl_seconds=LEASE_TTL_SECONDS):
        return 0
    heartbeat = LeaseHeartbeat(store, campaign_id, token)
    heartbeat.start()
    try:
        campaign = store.get_campaign(campaign_id)
        if campaign.get("active_episode_id"):
            store.recover_orphaned_episode(campaign_id)
            campaign = store.get_campaign(campaign_id)

        while True:
            campaign = store.get_campaign(campaign_id)
            if _settle_non_runnable(store, campaign):
                break
            allowed, budget_status, budget_reason = _budget_gate(campaign)
            if not allowed:
                store.transition_campaign(
                    campaign_id,
                    str(budget_status),
                    last_error=budget_reason,
                    completed_at=utc_now(),
                )
                break

            store.transition_campaign(campaign_id, "planning", last_error=None)
            campaign = store.get_campaign(campaign_id)
            objective, strategy_hint, task_profile_hint = next_episode_plan(store, campaign)
            # Build continuity from completed history before registering the new
            # active episode, otherwise the just-created empty row would look like
            # the previous session.
            context_pack = build_context_pack(store, campaign, objective)

            # Planning and memory review may take long enough for the user to pause
            # or stop JAM. Re-read state immediately before creating a thread so an
            # off toggle can never race into an unwanted replacement episode.
            campaign = store.get_campaign(campaign_id)
            if _settle_non_runnable(store, campaign):
                break
            allowed, budget_status, budget_reason = _budget_gate(campaign)
            if not allowed:
                store.transition_campaign(
                    campaign_id,
                    str(budget_status),
                    last_error=budget_reason,
                    completed_at=utc_now(),
                )
                break

            resolved_routing = campaign.get("resolved_routing") or {}
            if resolved_routing:
                ensure_managed_agents(
                    resolved_routing, workspace=campaign["workspace"]
                )

            timeout_seconds = _turn_timeout_seconds(campaign)
            if timeout_seconds <= 0:
                store.transition_campaign(
                    campaign_id,
                    "stopped_budget",
                    last_error="Elapsed-time budget exhausted.",
                    completed_at=utc_now(),
                )
                break
            try:
                episode = store.create_episode(
                    campaign_id,
                    objective=objective,
                    strategy_hint=strategy_hint,
                    task_profile_hint=task_profile_hint,
                    routing_snapshot=resolved_routing,
                )
            except CampaignNotRunnable:
                campaign = store.get_campaign(campaign_id)
                _settle_non_runnable(store, campaign)
                break
            paths = episode_dir(campaign_id, int(episode["number"]))
            prompt = render_episode_prompt(campaign, episode, context_pack)
            context_path = paths / "context.json"
            prompt_path = paths / "prompt.md"
            events_path = paths / "events.jsonl"
            stderr_path = paths / "app-server.stderr.log"
            final_path = paths / "report.md"
            handoff_path = paths / "handoff.json"
            routing_path = paths / "routing.json"
            agent_activity_path = paths / "agent-activity.json"
            model_events_path = paths / "model-events.json"
            token_usage_path = paths / "token-usage.json"
            atomic_write(context_path, json_dumps(context_pack, pretty=True))
            atomic_write(prompt_path, prompt)
            atomic_write(routing_path, json_dumps(resolved_routing, pretty=True))
            store.update_episode(
                episode["id"],
                prompt_path=str(prompt_path),
                events_path=str(events_path),
                final_path=str(final_path),
                handoff_path=str(handoff_path),
            )

            result = run_episode_turn(
                campaign=campaign,
                episode=episode,
                prompt=prompt,
                events_path=events_path,
                stderr_path=stderr_path,
                timeout_seconds=timeout_seconds,
            )
            atomic_write(agent_activity_path, json_dumps(result.agent_activity, pretty=True))
            atomic_write(model_events_path, json_dumps(result.model_events, pretty=True))
            atomic_write(token_usage_path, json_dumps(result.token_usage or {}, pretty=True))
            store.update_episode(
                episode["id"],
                thread_id=result.thread_id,
                turn_id=result.turn_id,
                agent_activity=result.agent_activity,
                model_events=result.model_events,
                token_usage=result.token_usage,
            )

            report, handoff, parse_error = read_episode_result(result)

            atomic_write(final_path, report)
            atomic_write(handoff_path, json_dumps(handoff, pretty=True))
            error = result.error or parse_error
            episode_status = "completed" if result.status in {"completed", "complete"} and not error else "error"
            store.finish_episode(
                episode["id"],
                status=episode_status,
                turn_status=result.status,
                final_text=result.final_text,
                handoff=handoff,
                error=error,
            )
            campaign = store.get_campaign(campaign_id)
            should_continue, status, reason, low_progress = continuation_decision(
                campaign, handoff, turn_status=episode_status
            )
            updates: dict[str, Any] = {
                "low_progress_count": low_progress,
                "last_error": (error or reason) if status in {"error", "needs_input", "stopped_budget"} else None,
            }
            if not should_continue:
                if status in {"completed", "stopped", "stopped_budget"}:
                    updates["completed_at"] = utc_now()
            store.transition_campaign(campaign_id, status, **updates)
            _write_campaign_summary(store, campaign_id)
            if not should_continue:
                break
            time.sleep(1.0)
        _write_campaign_summary(store, campaign_id)
        return 0
    except (CampaignNotFound, StoreError, AppServerError, RoutingError, OSError, TimeoutError) as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        cleanup_error = _record_campaign_failure(store, campaign_id, error_text)
        message = error_text
        if cleanup_error:
            message += f"\nFailure cleanup also failed: {cleanup_error}"
        print(message, file=sys.stderr)
        return 1
    except Exception as exc:  # defensive daemon boundary
        error_text = f"Unexpected controller failure: {exc}\n{traceback.format_exc()}"
        cleanup_error = _record_campaign_failure(store, campaign_id, error_text)
        message = error_text
        if cleanup_error:
            message += f"\nFailure cleanup also failed: {cleanup_error}"
        print(message, file=sys.stderr)
        return 1
    finally:
        heartbeat.stop()
        store.release_lease(campaign_id, token)
