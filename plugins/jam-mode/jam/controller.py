from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .appserver import AppServerError, run_episode_turn
from .context import build_context_pack
from .handoff import (
    HandoffError,
    fallback_error_handoff,
    normalize_handoff,
    parse_structured_response,
)
from .paths import campaign_dir, episode_dir, plugin_root
from .prompts import render_episode_prompt
from .routing import RoutingError, ensure_managed_agents, routing_prompt_summary
from .store import CampaignNotFound, Store, StoreError
from .util import atomic_write, epoch_now, json_dumps, process_is_alive, utc_now


LEASE_TTL_SECONDS = 240
HEARTBEAT_SECONDS = 45


def _elapsed_minutes(campaign: dict[str, Any]) -> float:
    started = campaign.get("started_at") or campaign.get("created_at")
    try:
        parsed = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0)
    except (TypeError, ValueError):
        return 0.0


def _recommended_option(handoff: dict[str, Any] | None) -> dict[str, Any] | None:
    if not handoff:
        return None
    options = handoff.get("next_options") or []
    index = handoff.get("recommended_next_option")
    if isinstance(index, int) and 0 <= index < len(options):
        option = options[index]
        return option if isinstance(option, dict) else None
    if options:
        valid = [option for option in options if isinstance(option, dict)]
        if valid:
            return max(valid, key=lambda option: float(option.get("expected_value") or 0.0))
    return None


def next_episode_plan(
    store: Store, campaign: dict[str, Any]
) -> tuple[str, str | None, str | None]:
    last = store.last_episode(campaign["id"])
    if last and isinstance(last.get("handoff"), dict):
        handoff = normalize_handoff(last["handoff"])
        option = _recommended_option(handoff)
        if option:
            return (
                str(option.get("objective") or campaign["objective"]),
                str(option.get("strategy") or "solo"),
                str(option.get("task_profile") or handoff.get("task_profile") or "general"),
            )
        open_item = (handoff.get("open_items") or [None])[0]
        if open_item:
            return (
                f"Resolve the highest-value open item: {open_item}",
                None,
                str(handoff.get("task_profile") or campaign.get("task_profile") or "adaptive"),
            )
    profile = str(campaign.get("task_profile") or "adaptive")
    return campaign["objective"], None, profile


def _budget_gate(campaign: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    if int(campaign.get("episode_count", 0)) >= int(campaign.get("max_episodes", 20)):
        return False, "stopped_budget", "Maximum episode count reached."
    if _elapsed_minutes(campaign) >= float(campaign.get("max_elapsed_minutes", 480)):
        return False, "stopped_budget", "Maximum elapsed campaign time reached."
    return True, None, None


def continuation_decision(
    campaign: dict[str, Any], handoff: dict[str, Any], *, turn_status: str
) -> tuple[bool, str, str, int]:
    """Return (continue, status, reason, new_low_progress_count)."""
    handoff = normalize_handoff(handoff)
    low_progress = int(campaign.get("low_progress_count", 0))

    if campaign.get("termination_requested"):
        return False, "stopped", "Campaign was stopped by the user.", low_progress
    if not campaign.get("enabled") or campaign.get("stop_after_current"):
        return False, "paused", "JAM was disabled; the current episode completed naturally.", low_progress
    if turn_status not in {"completed", "complete"}:
        return False, "error", f"Codex turn ended with status {turn_status}.", low_progress
    if handoff.get("boundary_flags"):
        return (
            False,
            "needs_input",
            "Continuation would cross or clarify an operating boundary: "
            + "; ".join(map(str, handoff["boundary_flags"])),
            low_progress,
        )
    if handoff.get("needs_user_input") or handoff.get("status") in {"needs_user", "blocked"}:
        return False, "needs_input", str(handoff.get("user_question") or handoff.get("summary")), low_progress
    completion = handoff.get("completion_assessment") or {}
    if handoff.get("status") == "complete" or completion.get("goal_reached"):
        return False, "completed", str(completion.get("reason") or handoff.get("summary")), 0
    if handoff.get("status") == "error":
        return False, "error", str(handoff.get("summary") or "Episode reported an error."), low_progress

    plateau = bool(completion.get("progress_plateau")) or float(
        handoff.get("progress_score") or 0.0
    ) < 0.12
    low_progress = low_progress + 1 if plateau else 0
    if low_progress >= int(campaign.get("max_low_progress", 2)):
        return (
            False,
            "paused",
            "Progress plateau threshold reached; user review is required before resuming.",
            low_progress,
        )

    option = _recommended_option(handoff)
    if not option:
        return False, "completed", "No materially useful next episode was proposed.", low_progress
    expected_value = float(option.get("expected_value") or 0.0)
    threshold = float(campaign.get("continuation_threshold", 0.55))
    if expected_value < threshold:
        return (
            False,
            "completed",
            f"Best next step value {expected_value:.2f} is below threshold {threshold:.2f}.",
            low_progress,
        )
    allowed, budget_status, budget_reason = _budget_gate(campaign)
    if not allowed:
        return False, str(budget_status), str(budget_reason), low_progress
    return True, "queued", str(option.get("reason") or "A valuable next episode is available."), low_progress


class LeaseHeartbeat:
    def __init__(self, store: Store, campaign_id: str, token: str) -> None:
        self.store = store
        self.campaign_id = campaign_id
        self.token = token
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            try:
                if not self.store.refresh_lease(
                    self.campaign_id, self.token, ttl_seconds=LEASE_TTL_SECONDS
                ):
                    return
            except Exception:
                return

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3)


def _write_campaign_summary(store: Store, campaign_id: str) -> None:
    campaign = store.get_campaign(campaign_id)
    episodes = list(reversed(store.list_episodes(campaign_id)))
    lines = [
        f"# {campaign['name']}",
        "",
        f"- ID: `{campaign['id']}`",
        f"- Status: **{campaign['status']}**",
        f"- Workspace: `{campaign['workspace']}`",
        f"- Task profile: `{campaign.get('task_profile') or 'adaptive'}`",
        f"- Episodes: {campaign['episode_count']} / {campaign['max_episodes']}",
        f"- Model policy: `{campaign.get('model_policy') or 'inherit'}`",
        f"- Model validation: `{campaign.get('model_validation') or 'fallback'}`",
        "",
        "## Model and agent routing",
        "",
        "```text",
        routing_prompt_summary(campaign.get("resolved_routing") or {}),
        "```",
        "",
        "## Objective",
        "",
        campaign["objective"],
        "",
        "## Operating boundaries",
        "",
        "```json",
        json_dumps(
            campaign.get("operating_boundaries") or campaign.get("authorized_scope") or {},
            pretty=True,
        ),
        "```",
        "",
        "## Episode history",
        "",
    ]
    for episode in episodes:
        handoff = episode.get("handoff") or {}
        lines.extend(
            [
                f"### Episode {episode['number']}: {episode['objective']}",
                "",
                f"- Status: `{episode['status']}`",
                f"- Task profile: `{episode.get('task_profile_used') or episode.get('task_profile_hint') or handoff.get('task_profile') or 'unknown'}`",
                f"- Strategy: `{episode.get('strategy_used') or episode.get('strategy_hint') or 'unknown'}`",
                f"- Thread: `{episode.get('thread_id') or 'not recorded'}`",
                "",
                str(handoff.get("summary") or episode.get("error") or "No summary recorded."),
                "",
            ]
        )
    atomic_write(campaign_dir(campaign_id) / "campaign.md", "\n".join(lines))


def run_campaign(campaign_id: str) -> int:
    store = Store()
    token = uuid.uuid4().hex
    if not store.acquire_lease(campaign_id, token, ttl_seconds=LEASE_TTL_SECONDS):
        return 0
    heartbeat = LeaseHeartbeat(store, campaign_id, token)
    heartbeat.start()
    active_episode_id: str | None = None
    try:
        campaign = store.get_campaign(campaign_id)
        if campaign.get("active_episode_id"):
            store.recover_orphaned_episode(campaign_id)
            campaign = store.get_campaign(campaign_id)

        while True:
            campaign = store.get_campaign(campaign_id)
            if campaign.get("termination_requested"):
                store.update_campaign(
                    campaign_id,
                    status="stopped",
                    enabled=False,
                    stop_after_current=False,
                    completed_at=utc_now(),
                )
                break
            if not campaign.get("enabled"):
                store.update_campaign(campaign_id, status="paused")
                break
            allowed, budget_status, budget_reason = _budget_gate(campaign)
            if not allowed:
                store.update_campaign(
                    campaign_id,
                    status=budget_status,
                    enabled=False,
                    last_error=budget_reason,
                    completed_at=utc_now(),
                )
                break

            store.update_campaign(campaign_id, status="planning", last_error=None)
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
            if campaign.get("termination_requested"):
                store.update_campaign(
                    campaign_id,
                    status="stopped",
                    enabled=False,
                    stop_after_current=False,
                    completed_at=utc_now(),
                )
                break
            if not campaign.get("enabled") or campaign.get("stop_after_current"):
                store.update_campaign(
                    campaign_id,
                    status="paused",
                    enabled=False,
                    stop_after_current=False,
                )
                break
            allowed, budget_status, budget_reason = _budget_gate(campaign)
            if not allowed:
                store.update_campaign(
                    campaign_id,
                    status=budget_status,
                    enabled=False,
                    last_error=budget_reason,
                    completed_at=utc_now(),
                )
                break

            resolved_routing = campaign.get("resolved_routing") or {}
            if resolved_routing:
                ensure_managed_agents(
                    resolved_routing, workspace=campaign["workspace"]
                )

            episode = store.create_episode(
                campaign_id,
                objective=objective,
                strategy_hint=strategy_hint,
                task_profile_hint=task_profile_hint,
                routing_snapshot=resolved_routing,
            )
            active_episode_id = episode["id"]
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

            parse_error: str | None = None
            try:
                report, handoff = parse_structured_response(result.final_text)
            except HandoffError as exc:
                parse_error = str(exc)
                report = (
                    "# Episode did not return a valid handoff\n\n"
                    f"{parse_error}\n\n## Raw final response\n\n{result.final_text}"
                )
                handoff = fallback_error_handoff(parse_error)

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
            active_episode_id = None
            campaign = store.get_campaign(campaign_id)
            should_continue, status, reason, low_progress = continuation_decision(
                campaign, handoff, turn_status=result.status
            )
            updates: dict[str, Any] = {
                "status": status,
                "low_progress_count": low_progress,
                "last_error": reason if status in {"error", "needs_input", "stopped_budget"} else None,
            }
            if not should_continue:
                updates["enabled"] = False
                updates["stop_after_current"] = False
                if status in {"completed", "stopped", "stopped_budget"}:
                    updates["completed_at"] = utc_now()
            store.update_campaign(campaign_id, **updates)
            _write_campaign_summary(store, campaign_id)
            if not should_continue:
                break
            time.sleep(1.0)
        _write_campaign_summary(store, campaign_id)
        return 0
    except (CampaignNotFound, StoreError, AppServerError, RoutingError, OSError, TimeoutError) as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        try:
            if active_episode_id:
                handoff = fallback_error_handoff(error_text)
                store.finish_episode(
                    active_episode_id,
                    status="error",
                    turn_status="failed",
                    final_text="",
                    handoff=handoff,
                    error=error_text,
                )
            store.update_campaign(
                campaign_id,
                status="error",
                enabled=False,
                stop_after_current=False,
                last_error=error_text,
            )
            _write_campaign_summary(store, campaign_id)
        except Exception:
            pass
        print(error_text, file=sys.stderr)
        return 1
    except Exception as exc:  # defensive daemon boundary
        error_text = f"Unexpected controller failure: {exc}\n{traceback.format_exc()}"
        try:
            store.update_campaign(
                campaign_id,
                status="error",
                enabled=False,
                stop_after_current=False,
                last_error=error_text,
            )
        except Exception:
            pass
        print(error_text, file=sys.stderr)
        return 1
    finally:
        heartbeat.stop()
        store.release_lease(campaign_id, token)


def spawn_controller(campaign_id: str) -> int:
    store = Store()
    campaign = store.get_campaign(campaign_id)
    lease_expiry = campaign.get("lease_expires_at")
    pid = campaign.get("controller_pid")
    if lease_expiry and float(lease_expiry) > epoch_now() and process_is_alive(pid):
        return int(pid)

    log_path = campaign_dir(campaign_id) / "controller.log"
    log_handle = log_path.open("a", encoding="utf-8")
    env = os.environ.copy()
    root = str(plugin_root())
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")
    command = [sys.executable, "-m", "jam.controller", "run", campaign_id]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "cwd": campaign["workspace"],
        "env": env,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    log_handle.close()
    store.update_campaign(campaign_id, controller_pid=process.pid)
    return process.pid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JAM Mode campaign controller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("campaign_id")
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("campaign_id")
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_campaign(args.campaign_id)
    pid = spawn_controller(args.campaign_id)
    print(pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
