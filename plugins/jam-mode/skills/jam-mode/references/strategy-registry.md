# Adaptive strategy registry

JAM keeps top-level episodes serial while allowing the reasoning topology inside one episode to adapt to the task.

| Strategy | Select when | Shape | Write rule |
|---|---|---|---|
| `solo` | Clear, bounded, low-uncertainty work | One agent executes and verifies | One writer at most |
| `parallel_explore` | Alternatives or independent facets benefit from parallel thought | Independent explorers return; parent compares and synthesizes | Read-only children preferred |
| `critique_synthesize` | A proposal, interpretation, or design needs adversarial improvement | Proposal(s), critique, then consolidated result | One final owner |
| `map_reduce` | Work separates cleanly into non-overlapping components | Specialists handle components; aggregator combines | Avoid overlapping edits |
| `builder_reviewer` | Code, configuration, documents, or another concrete artifact must be created or changed | Exactly one writer; independent reviewer and focused verification | Exactly one writer |
| `planner_executor` | Work needs an explicit plan before execution | Planner creates bounded plan; one executor performs it | Executor is the only writer |
| `producer_critic` | A draft, report, document, or content deliverable needs refinement | Producer drafts; critic checks against brief; producer/parent revises | One final writer |
| `execute_validate` | A deterministic change/action should be followed by independent verification | Execute once; validate result and side effects | One executor |
| `duo_independent` | Compatibility/specialized investigator-and-skeptic workflow | Two independent analyses; parent synthesizes | Read-only children preferred |
| `discover_reproduce` | A claim benefits from independent confirmation or falsification | Discoverer develops result; reproducer independently tests it | Reproduction remains within boundaries |
| `evidence_arbitration` | Memories, tests, logs, metrics, or agents disagree materially | Independent audits followed by evidence-weighted arbitration | Usually read-only |
| `reorientation` | Repeated low progress or stale assumptions | Reassess premises and choose a materially different direction | Write only after new direction is justified |
| `closure` | Goal is met or no worthwhile next step remains | Consolidate deliverables, validation, limitations, and artifacts | No speculative continuation |

## Selection factors

Consider uncertainty, decomposability, quality/evidence requirements, cost, action risk, write contention, remaining context, and campaign budget. More agents are not automatically better.

- Prefer `solo` for deterministic follow-ups.
- Prefer `parallel_explore` when independent options or coverage create value.
- Prefer `producer_critic` for writing and content.
- Prefer `builder_reviewer` for concrete edits.
- Prefer `execute_validate` for operations, migrations, and final verification.
- Prefer `closure` once success criteria are met.

## Synthesis rules

- Preserve independence until child agents return.
- Compare evidence, quality criteria, and explicit trade-offs rather than confidence or majority vote.
- Explicitly resolve material disagreements.
- Distinguish completed work, assumptions, decisions, risks, blockers, and unknowns.
- Use task-appropriate references: files/tests/logs for engineering, acceptance/editorial checks for documents, quality metrics for data, and health/rollback checks for operations.
- The parent synthesis owns the final episode result and handoff.


## Named-agent routing

Multi-agent strategies use JAM-prefixed custom agents rather than unnamed generic workers. The parent remains the orchestrator and final synthesizer. See [model-routing.md](model-routing.md) for the exact role registry, presets, catalog validation, and one-writer rule.
