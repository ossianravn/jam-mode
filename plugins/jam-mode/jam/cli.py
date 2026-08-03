from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .appserver import AppServerError
from .contracts import TASK_PROFILES
from .routing import (
    ALL_ROUTING_ROLES,
    MODEL_POLICIES,
    MODEL_VALIDATION_MODES,
)
from .service import (
    add_memory_path,
    campaign_log,
    configure_model_routing,
    doctor,
    get_model_routing,
    get_status,
    list_campaigns,
    list_model_catalog,
    pause_campaign,
    refresh_campaign_routing,
    resume_campaign,
    start_campaign,
    stop_campaign,
)
from .store import CampaignNotFound, StoreError
from .util import json_dumps


def _parse_assignments(values: list[str] | None, *, label: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"{label} must use ROLE=VALUE syntax: {raw!r}")
        role, value = raw.split("=", 1)
        role = role.strip().lower().replace("-", "_")
        if role not in ALL_ROUTING_ROLES:
            raise ValueError(
                f"Unknown routing role {role!r}; use one of: "
                + ", ".join(ALL_ROUTING_ROLES)
            )
        if not value.strip():
            raise ValueError(f"{label} has an empty value for role {role!r}.")
        output[role] = value.strip()
    return output


def _print_roster(resolved: dict[str, Any]) -> None:
    parent = resolved.get("parent") or {}
    print(
        "Parent:       "
        f"{parent.get('model') or 'inherit'} · {parent.get('effort') or 'default'}"
    )
    for role, item in (resolved.get("roles") or {}).items():
        print(
            f"{role + ':':<14} {item.get('agent') or 'unknown'} · "
            f"{item.get('model') or 'inherit'} · {item.get('effort') or 'default'} · "
            f"{item.get('sandbox') or 'inherit'}"
        )


def _print_status(payload: dict[str, Any]) -> None:
    campaign = payload["campaign"]
    last = payload.get("last_episode")
    print(f"JAM campaign: {campaign['name']}")
    print(f"ID:           {campaign['id']}")
    print(f"Status:       {campaign['status']}")
    print(f"Enabled:      {campaign['enabled']}")
    print(f"Workspace:    {campaign['workspace']}")
    print(f"Profile:      {campaign.get('task_profile') or 'adaptive'}")
    print(f"Episodes:     {campaign['episode_count']} / {campaign['max_episodes']}")
    print(f"Sandbox:      {campaign['sandbox']}")
    print(f"Model policy: {campaign.get('model_policy') or 'inherit'}")
    print(f"Validation:   {campaign.get('model_validation') or 'fallback'}")
    parent = (campaign.get("resolved_routing") or {}).get("parent") or {}
    print(
        f"Parent model: {parent.get('model') or campaign.get('model') or 'inherit'} · "
        f"{parent.get('effort') or campaign.get('effort') or 'default'}"
    )
    print(f"Controller:   {'running' if payload.get('controller_alive') else 'not running'}")
    if campaign.get("active_episode_id"):
        print(f"Active:       {campaign['active_episode_id']}")
    if last:
        print(f"Last episode: {last['number']} — {last['status']}")
        handoff = last.get("handoff") or {}
        if handoff.get("task_profile"):
            print(f"Last profile: {handoff['task_profile']}")
        if handoff.get("summary"):
            print(f"Last result:  {handoff['summary']}")
        if handoff.get("user_question"):
            print(f"Question:     {handoff['user_question']}")
        if last.get("thread_id"):
            print(f"Thread:       {last['thread_id']}")
        if last.get("agent_activity"):
            print(f"Subagents:    {len(last['agent_activity'])} collaboration call(s) recorded")
    warnings = campaign.get("routing_warnings") or []
    if warnings:
        print("Routing warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    if campaign.get("last_error"):
        print(f"Attention:    {campaign['last_error']}")
    print(f"Files:        {payload['campaign_directory']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jam", description="JAM Mode campaign controller for Codex"
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Create and start a fresh JAM campaign")
    start.add_argument("--objective", "-o", required=True)
    start.add_argument("--workspace", "-C", default=os.getcwd())
    boundaries = start.add_mutually_exclusive_group()
    boundaries.add_argument(
        "--boundaries",
        help="Operating-boundaries text or JSON. Defaults to conservative local-workspace limits.",
    )
    boundaries.add_argument("--scope", help="Deprecated alias for --boundaries.")
    start.add_argument("--profile", choices=TASK_PROFILES, default="adaptive")
    start.add_argument("--name")
    start.add_argument("--success", default="")
    start.add_argument(
        "--model-policy",
        choices=MODEL_POLICIES,
        default=None,
        help="Role routing preset. Omit to use the saved JAM routing defaults.",
    )
    start.add_argument(
        "--model-validation",
        choices=(*MODEL_VALIDATION_MODES, "none"),
        default=None,
        help="Validation mode. Omit to use the saved JAM routing defaults.",
    )
    start.add_argument("--model", help="Parent/synthesizer model override.")
    start.add_argument("--effort", help="Parent/synthesizer reasoning-effort override.")
    start.add_argument(
        "--role-model",
        action="append",
        default=[],
        metavar="ROLE=MODEL",
        help="Override a role model; repeat as needed.",
    )
    start.add_argument(
        "--role-effort",
        action="append",
        default=[],
        metavar="ROLE=EFFORT",
        help="Override a role reasoning effort; repeat as needed.",
    )
    child_ultra = start.add_mutually_exclusive_group()
    child_ultra.add_argument(
        "--allow-child-ultra",
        action="store_true",
        dest="allow_child_ultra",
        help="Permit child roles to use Ultra when the selected model advertises it.",
    )
    child_ultra.add_argument(
        "--disallow-child-ultra",
        action="store_false",
        dest="allow_child_ultra",
    )
    parent_ultra = start.add_mutually_exclusive_group()
    parent_ultra.add_argument(
        "--allow-parent-ultra",
        action="store_true",
        dest="allow_parent_ultra",
        help="Permit the parent/synthesizer to use Ultra when advertised.",
    )
    parent_ultra.add_argument(
        "--disallow-parent-ultra",
        action="store_false",
        dest="allow_parent_ultra",
    )
    start.set_defaults(allow_child_ultra=None, allow_parent_ultra=None)
    start.add_argument(
        "--sandbox", choices=["read-only", "workspace-write"], default="read-only"
    )
    start.add_argument("--network", action="store_true")
    start.add_argument("--max-episodes", type=int, default=20)
    start.add_argument("--max-minutes", type=int, default=480)
    start.add_argument("--threshold", type=float, default=0.55)
    start.add_argument("--max-low-progress", type=int, default=2)
    start.add_argument("--max-subagents", type=int, default=2)
    start.add_argument("--memory", action="append", default=[])
    start.add_argument("--tag", action="append", default=[])

    status = sub.add_parser("status", help="Show campaign state")
    status.add_argument("campaign", nargs="?")

    sub.add_parser("list", help="List campaigns")

    models = sub.add_parser("models", help="List models and reasoning efforts advertised by Codex")
    models.add_argument("--hidden", action="store_true", help="Include hidden catalog entries.")

    routing = sub.add_parser(
        "routing",
        help="Inspect or update global defaults, or a paused campaign's routing roster",
    )
    routing.add_argument(
        "campaign",
        nargs="?",
        help="Optional campaign id/name. Omit to inspect or update global defaults.",
    )
    routing.add_argument("--policy", choices=MODEL_POLICIES)
    routing.add_argument("--validation", choices=(*MODEL_VALIDATION_MODES, "none"))
    routing.add_argument("--model", help="Parent model override; use 'inherit' to clear.")
    routing.add_argument("--effort", help="Parent effort override; use 'inherit' to clear.")
    routing.add_argument("--role-model", action="append", default=[], metavar="ROLE=MODEL")
    routing.add_argument("--role-effort", action="append", default=[], metavar="ROLE=EFFORT")
    ultra = routing.add_mutually_exclusive_group()
    ultra.add_argument("--allow-child-ultra", action="store_true", dest="allow_child_ultra")
    ultra.add_argument("--disallow-child-ultra", action="store_false", dest="allow_child_ultra")
    parent_ultra = routing.add_mutually_exclusive_group()
    parent_ultra.add_argument("--allow-parent-ultra", action="store_true", dest="allow_parent_ultra")
    parent_ultra.add_argument("--disallow-parent-ultra", action="store_false", dest="allow_parent_ultra")
    routing.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip App Server model/list compatibility checks.",
    )
    routing.add_argument(
        "--reset",
        action="store_true",
        help="Reset global defaults, or reset a paused campaign to current global defaults.",
    )
    routing.add_argument(
        "--refresh",
        action="store_true",
        help="Revalidate and rematerialize a paused campaign without changing overrides.",
    )
    routing.set_defaults(allow_child_ultra=None, allow_parent_ultra=None)

    pause = sub.add_parser("pause", help="Stop after the active episode")
    pause.add_argument("campaign", nargs="?")

    resume = sub.add_parser("resume", help="Resume with a fresh planning pass")
    resume.add_argument("campaign", nargs="?")
    resume.add_argument("--guidance")

    stop = sub.add_parser("stop", help="End the campaign after the active episode")
    stop.add_argument("campaign", nargs="?")

    memory = sub.add_parser("add-memory", help="Add a campaign memory file or directory")
    memory.add_argument("path")
    memory.add_argument("--campaign")

    log = sub.add_parser("log", help="Show the controller log tail")
    log.add_argument("campaign", nargs="?")
    log.add_argument("--tail", type=int, default=120)

    sub.add_parser("doctor", help="Check local JAM/Codex prerequisites")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start_campaign(
                objective=args.objective,
                workspace=args.workspace,
                operating_boundaries=args.boundaries,
                authorized_scope=args.scope,
                task_profile=args.profile,
                name=args.name,
                success_criteria=args.success,
                model=args.model,
                effort=args.effort,
                model_policy=args.model_policy,
                model_validation=args.model_validation,
                allow_child_ultra=args.allow_child_ultra,
                allow_parent_ultra=args.allow_parent_ultra,
                role_models=_parse_assignments(args.role_model, label="--role-model"),
                role_efforts=_parse_assignments(args.role_effort, label="--role-effort"),
                sandbox=args.sandbox,
                allow_network=args.network,
                max_episodes=args.max_episodes,
                max_elapsed_minutes=args.max_minutes,
                continuation_threshold=args.threshold,
                max_low_progress=args.max_low_progress,
                max_subagents=args.max_subagents,
                memory_paths=args.memory,
                tags=args.tag,
            )
        elif args.command == "status":
            result = get_status(args.campaign)
        elif args.command == "list":
            result = {"campaigns": list_campaigns()}
        elif args.command == "models":
            result = list_model_catalog(include_hidden=args.hidden)
        elif args.command == "routing":
            has_updates = any(
                [
                    args.policy is not None,
                    args.validation is not None,
                    args.model is not None,
                    args.effort is not None,
                    bool(args.role_model),
                    bool(args.role_effort),
                    args.allow_child_ultra is not None,
                    args.allow_parent_ultra is not None,
                    args.reset,
                ]
            )
            if args.refresh:
                if not args.campaign:
                    raise ValueError("jam routing --refresh requires a campaign id or exact name.")
                if has_updates:
                    raise ValueError("Use --refresh by itself; configure overrides separately.")
                result = refresh_campaign_routing(
                    args.campaign, validate=not args.no_validate
                )
            elif has_updates:
                result = configure_model_routing(
                    args.campaign,
                    model_policy=args.policy,
                    model_validation=args.validation,
                    model=args.model,
                    effort=args.effort,
                    role_models=_parse_assignments(args.role_model, label="--role-model"),
                    role_efforts=_parse_assignments(args.role_effort, label="--role-effort"),
                    allow_child_ultra=args.allow_child_ultra,
                    allow_parent_ultra=args.allow_parent_ultra,
                    validate=not args.no_validate,
                    reset=args.reset,
                )
            else:
                result = get_model_routing(
                    args.campaign, validate=not args.no_validate
                )
        elif args.command == "pause":
            result = pause_campaign(args.campaign)
        elif args.command == "resume":
            result = resume_campaign(args.campaign, guidance=args.guidance)
        elif args.command == "stop":
            result = stop_campaign(args.campaign)
        elif args.command == "add-memory":
            result = add_memory_path(args.campaign, args.path)
        elif args.command == "log":
            result = campaign_log(args.campaign, tail=args.tail)
        elif args.command == "doctor":
            result = doctor()
        else:
            parser.error("Unknown command")
            return 2

        if args.json_output:
            print(json_dumps(result, pretty=True))
        elif args.command == "status":
            _print_status(result)
        elif args.command == "list":
            campaigns = result["campaigns"]
            if not campaigns:
                print("No JAM campaigns.")
            for campaign in campaigns:
                enabled = "on" if campaign["enabled"] else "off"
                print(
                    f"{campaign['id']}  {campaign['status']:<23} {enabled:<3} "
                    f"{campaign['episode_count']:>3}  {campaign['name']}"
                )
        elif args.command == "models":
            for model in result["models"]:
                efforts = ", ".join(model.get("supported_efforts") or []) or "not advertised"
                flags = []
                if model.get("is_default"):
                    flags.append("default")
                if model.get("hidden"):
                    flags.append("hidden")
                suffix = f" [{' · '.join(flags)}]" if flags else ""
                print(f"{model['id']}{suffix}")
                print(
                    f"  default effort: {model.get('default_effort') or 'not advertised'}; "
                    f"supported: {efforts}"
                )
        elif args.command == "routing":
            resolved = result.get("resolved") or {}
            print(
                f"Policy: {resolved.get('policy') or result.get('policy') or 'inherit'}; "
                f"validation: {resolved.get('validation') or result.get('validation') or 'fallback'}; "
                f"catalog: {resolved.get('catalog_status') or 'unknown'}"
            )
            _print_roster(resolved)
            warnings = result.get("warnings") or resolved.get("warnings") or []
            if warnings:
                print("Warnings:")
                for warning in warnings:
                    print(f"  - {warning}")
        elif args.command == "log":
            print(result["text"] or f"No controller log at {result['path']}")
        elif args.command == "doctor":
            for check in result["checks"]:
                print(f"{'OK' if check['ok'] else 'FAIL':<4} {check['name']}: {check['detail']}")
            return 0 if result["ok"] else 1
        else:
            campaign = result.get("campaign") or {}
            if campaign:
                print(f"{campaign['id']}: {campaign['status']}")
            if result.get("message"):
                print(result["message"])
            if result.get("controller_pid"):
                print(f"Controller PID: {result['controller_pid']}")
            for warning in result.get("routing_warnings") or result.get("warnings") or []:
                print(f"Routing warning: {warning}")
        return 0
    except (ValueError, StoreError, CampaignNotFound, AppServerError) as exc:
        if args.json_output:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(f"jam: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("jam: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
