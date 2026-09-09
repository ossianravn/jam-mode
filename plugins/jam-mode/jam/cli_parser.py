from __future__ import annotations

import argparse
import os

from .contracts import TASK_PROFILES
from .harnesses.registry import HARNESS_IDS
from .resumption import add_resume_parser
from .routing import MODEL_POLICIES, MODEL_VALIDATION_MODES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jam", description="JAM Mode campaign controller"
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Create and start a fresh JAM campaign")
    start.add_argument("--objective", "-o", required=True)
    start.add_argument("--workspace", "-C", default=os.getcwd())
    start.add_argument("--harness", choices=HARNESS_IDS, default="codex")
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
        help="Routing policy. Defaults to saved Codex settings, or inherit for other harnesses.",
    )
    start.add_argument(
        "--model-validation",
        choices=(*MODEL_VALIDATION_MODES, "none"),
        default=None,
        help="Validation mode. Defaults to saved Codex settings, or strict for other harnesses.",
    )
    start.add_argument("--model", help="Parent/synthesizer model override.")
    start.add_argument("--effort", help="Parent/synthesizer reasoning-effort override.")
    start.add_argument(
        "--role-model",
        action="append",
        default=[],
        metavar="ROLE=MODEL",
        help="Override a child-role model; repeat as needed.",
    )
    start.add_argument(
        "--role-effort",
        action="append",
        default=[],
        metavar="ROLE=EFFORT",
        help="Override a child-role reasoning effort; repeat as needed.",
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
    sub.add_parser("harnesses", help="Inspect installed coding harnesses and adapter capabilities")

    models = sub.add_parser("models", help="List the selected harness's advertised models and availability limits")
    models.add_argument("--hidden", action="store_true", help="Include hidden catalog entries.")
    models.add_argument("--harness", choices=HARNESS_IDS, default="codex")

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

    add_resume_parser(sub)

    stop = sub.add_parser("stop", help="End the campaign after the active episode")
    stop.add_argument("campaign", nargs="?")

    memory = sub.add_parser("add-memory", help="Add a campaign memory file or directory")
    memory.add_argument("path")
    memory.add_argument("--campaign")

    log = sub.add_parser("log", help="Show the controller log tail")
    log.add_argument("campaign", nargs="?")
    log.add_argument("--tail", type=int, default=120)

    doctor = sub.add_parser("doctor", help="Check local JAM/harness prerequisites")
    doctor.add_argument("--harness", choices=HARNESS_IDS, default="codex")
    return parser
