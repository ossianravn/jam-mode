from __future__ import annotations

import json
import sys

from .appserver import AppServerError
from .cli_output import _parse_assignments, _print_roster, _print_status
from .cli_parser import build_parser
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
            result = resume_campaign(args.campaign, guidance=args.guidance, max_subagents=args.max_subagents)
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
