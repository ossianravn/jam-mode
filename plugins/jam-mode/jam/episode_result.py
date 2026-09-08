from __future__ import annotations

import json
from pathlib import Path

from .appserver import TurnResult
from .collaboration import CollaborationError, verify_contributions
from .contracts import STRATEGIES
from .handoff import HandoffError, fallback_error_handoff, parse_structured_response


def read_episode_result(result: TurnResult) -> tuple[str, dict, str | None]:
    try:
        report, handoff = parse_structured_response(result.final_text)
    except HandoffError as exc:
        error = str(exc)
        return (
            f"# Episode did not return a valid handoff\n\n{error}\n\n"
            f"## Raw final response\n\n{result.final_text}",
            fallback_error_handoff(error), error,
        )
    if result.error or result.status not in {"completed", "complete"}:
        return report, handoff, result.error
    if handoff["status"] == "error":
        return report, handoff, handoff["summary"] or "Episode reported an error."
    if handoff["status"] in {"needs_user", "blocked"} or handoff["needs_user_input"] or handoff["boundary_flags"]:
        return report, handoff, None
    try:
        if handoff["strategy_used"] not in STRATEGIES:
            raise CollaborationError("JAM requires a multi-agent strategy; solo, single, and missing strategies are not accepted.")
        with Path(result.events_path).open(encoding="utf-8") as stream:
            verify_contributions(
                (json.loads(line) for line in stream if line.strip()),
                thread_id=result.thread_id, turn_id=result.turn_id,
                final_text=result.final_text, strategy=handoff["strategy_used"],
            )
    except (CollaborationError, OSError, ValueError) as exc:
        error = f"Multi-agent verification failed: {exc}"
        return report + f"\n\n## JAM verification failed\n\n{error}", fallback_error_handoff(error), error
    return report, handoff, None
