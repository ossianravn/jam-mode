from __future__ import annotations

from typing import Any

from .contracts import normalize_strategy
from .routing import ROLE_AGENT_NAMES, routing_prompt_summary, strategy_routing_instructions


def validate_agent_budget(campaign: dict[str, Any]) -> None:
    if not 2 <= int(campaign.get("max_subagents", 2)) <= 16:
        raise ValueError(
            "Duo requires max_subagents between 2 and 16. "
            "For an existing campaign, use jam resume <id> --max-subagents 2 "
            "(MCP: jam_resume_campaign with max_subagents=2)."
        )


def render_strategy_instructions(campaign: dict[str, Any], hint: object) -> str:
    validate_agent_budget(campaign)
    resolved = campaign.get("resolved_routing") or {}
    roles = resolved.get("roles") or {}

    def agent(role: str) -> str:
        return str((roles.get(role) or {}).get("agent") or ROLE_AGENT_NAMES[role])

    routes = strategy_routing_instructions(resolved)
    warnings = campaign.get("routing_warnings") or resolved.get("warnings") or []
    warning_text = "\n".join(f"- {warning}" for warning in warnings) or "- none"
    return f"""DUO IS THE DEFAULT STRATEGY
Current strategy: {normalize_strategy(hint)}.
Use duo_independent unless another multi-agent strategy is materially better
suited to this episode. Explain any change. A simple task, cost saving, or an
unavailable agent is not a reason to work alone. Single-agent execution is not
an available strategy or fallback.

DUO WORKFLOW
1. Spawn {agent('explorer')} and {agent('critic')} before waiting for either.
   Give both the original episode objective, relevant context, operating
   boundaries, and success criteria. Neither may edit files.
2. The explorer independently investigates the task and develops an evidenced
   answer or proposed solution. The critic independently investigates competing
   explanations, assumptions, weaknesses, and ways the proposed outcome could fail.
   Do not give either the other agent's analysis or your preferred conclusion.
3. Wait for both agents to finish and return their findings before synthesizing,
   implementing, or producing the final deliverable. Do not cancel one to save time.
4. As the parent/synthesizer, compare both contributions, resolve disagreements
   using evidence rather than voting, and form one consolidated answer or plan.
   Perform any authorized implementation as the single writer, then verify it.
5. Explain in report_markdown what each agent contributed and how the synthesis
   resolved material disagreements. Report unresolved uncertainty honestly.

OTHER MULTI-AGENT STRATEGIES
- parallel_explore / map_reduce: at least two independent child assignments, then synthesis;
- critique_synthesize: critique and independent review, then parent synthesis;
- builder_reviewer / producer_critic: one producer, then an independent critic/reviewer;
- planner_executor: planner, then one appropriate executor, then parent synthesis;
- execute_validate / discover_reproduce: execution/discovery, then independent validation;
- evidence_arbitration / reorientation: independent assessments, then parent arbitration;
- closure: closer consolidates the evidence, reviewer checks it, parent delivers the result.
Every strategy requires substantive results from at least two distinct direct
child agents. The parent is additional and always owns the final synthesis.
For dependent roles, wait for the earlier role before starting the next.

MODEL AND SUBAGENT ROUTING
{routing_prompt_summary(resolved)}

Strategy-to-agent routes:
{routes}

Routing warnings:
{warning_text}

Always delegate each bounded role to the exact JAM custom agent named above.
Retain its configured model and effort. For parallel_explore and map_reduce,
spawn at least two instances of the listed role. For planner_executor and
execute_validate, choose one appropriate writer from implementer and producer.
If a required agent cannot start or finish, stop with needs_user_input and
explain the missing contribution. Do not substitute a solo result or claim completion.

You may use at most {campaign.get('max_subagents', 2)} subagents at one time.
Keep independent analyses separate until they return. Never let two agents edit
the same checkout concurrently. There must be no more than one writer.
Child agents must not spawn further agents unless allow_child_ultra is explicitly
true in the roster; nested agents do not replace either required direct child.
"""
