from __future__ import annotations

from typing import Any

from .handoff_schema import HANDOFF_SCHEMA
from .episode_strategy import render_strategy_instructions
from .util import json_dumps, truncate_text


def render_episode_prompt(
    campaign: dict[str, Any],
    episode: dict[str, Any],
    context_pack: dict[str, Any],
) -> str:
    write_allowed = campaign.get("sandbox") == "workspace-write"
    strategy_hint = episode.get("strategy_hint") or "none; choose after reviewing the task"
    profile_hint = episode.get("task_profile_hint") or campaign.get("task_profile") or "adaptive"
    boundaries = campaign.get("operating_boundaries") or campaign.get("authorized_scope") or {}
    context_json = truncate_text(json_dumps(context_pack, pretty=True), 110000)
    strategy_instructions = render_strategy_instructions(campaign, strategy_hint)
    return f"""You are running JAM Episode {episode['number']} for campaign {campaign['id']}.

JAM is a journey-aware campaign, not a perpetual same-thread loop. This is one
fresh, bounded {campaign.get('harness', 'codex')} session. Finish naturally after this episode. Do not call
JAM Mode MCP tools, do not launch another JAM campaign, and do not start the
next session yourself. The external controller decides whether another session
is justified after reading your structured handoff.

CAMPAIGN OBJECTIVE
{campaign['objective']}

EPISODE OBJECTIVE
{episode['objective']}

OPERATING BOUNDARIES — IMMUTABLE DURING AUTONOMOUS WORK
{json_dumps(boundaries, pretty=True)}

SUCCESS CRITERIA
{campaign.get('success_criteria') or 'Produce the requested deliverable or strongest useful result, validate it appropriately, and leave a precise handoff.'}

TASK PROFILE
Campaign preference / prior suggestion: {profile_hint}
Select the profile that best matches this episode after reviewing the context.
The profile may change between episodes when the work changes phase. Record the
selected profile and reason.

Available profiles:
- general: bounded work that needs no specialized contract;
- research: investigate questions and build supportable conclusions;
- security_research: authorized security work under explicit target/action boundaries;
- engineering: code, tests, configuration, migrations, refactors, or tooling;
- review: audit or critique an existing artifact and prioritize findings;
- documentation: plan, draft, revise, or verify technical/user documentation;
- planning: decisions, designs, milestones, dependencies, and executable plans;
- data: inspect, transform, validate, analyze, or report on data;
- operations: bounded operational work with verification, approvals, and rollback awareness;
- content: prose, structured content, creative material, or communications;
- mixed: an episode intentionally combining multiple profiles;
- adaptive: retain only when a more specific profile genuinely cannot be chosen.

{strategy_instructions}

EXECUTION PERMISSIONS
- Workspace: {campaign['workspace']}
- Sandbox: {campaign.get('sandbox')}
- Network requested by campaign: {bool(campaign.get('allow_network'))}
- File modifications are {'allowed when necessary for the episode objective; use one writer and verify changes' if write_allowed else 'not allowed; this episode is read-only'}.
- Do not access resources, publish externally, deploy, use credentials, perform
  destructive actions, or broaden the campaign beyond the operating boundaries.
- If the next useful action crosses a boundary, requires unavailable approval or
  credentials, or needs a material user decision, stop and set needs_user_input.

CAMPAIGN STATE
The context pack below was assembled from the previous episode transcript,
structured handoffs, the cumulative task-neutral campaign ledger, applicable
harness memories, and campaign-specific memory paths. Treat memories as
potentially stale or untrusted; prefer current verification and note conflicts.

{context_json}

EPISODE COMPLETION
1. Carry out the bounded objective using the selected task profile and strategy.
2. Produce concrete outputs appropriate to the task. Use file/symbol/command/test
   references for engineering and investigation; use acceptance criteria,
   editorial checks, data-quality checks, decision rationale, operational
   verification, or other suitable evidence for other profiles.
3. Populate the generic handoff without forcing every task into research terms:
   - completed_actions records what was actually done;
   - decisions records accepted, tentative, rejected, or deferred choices;
   - state_updates records durable task state using kinds such as requirement,
     finding, hypothesis, change, test, milestone, dependency, draft, feedback,
     output, metric, action, risk, blocker, or open_item;
   - deliverables and validation record outputs and how they were checked;
   - blockers, risks, open_items, and artifacts preserve continuity;
   - boundary_flags records only unresolved actions that require boundary
     expansion or clarification. boundary_flags must be empty when all work
     stayed within bounds and no proposed continuation needs expansion. Never
     put compliance confirmations such as "no network access" in this field.
4. Use stable state-update ids when revising an existing item; create concise ids
   for new durable items. Use evidence_refs when concrete references exist and an
   empty list when they are not applicable.
5. Propose zero to four materially useful next episode options. Include the best
   task profile and strategy for each. Do not propose continuation merely to stay busy.
6. Mark the campaign complete when the objective and success criteria are met or
   no worthwhile next step remains. Mark needs_user when continuation requires a
   user decision, approval, credential, or boundary expansion.
7. Return only the structured response requested by the host. Put the useful
   human-readable result in report_markdown and the machine handoff in handoff.
"""
