# Adaptive task profiles

A task profile selects the vocabulary, validation style, and durable state that best fit one JAM episode. The campaign may begin with `adaptive`, and each episode may select a more specific profile after reviewing the current objective and prior state. Profiles may change as the campaign moves between phases.

| Profile | Select when | Typical durable state | Typical validation |
|---|---|---|---|
| `adaptive` | The next phase is not known before context review | A profile decision plus general state | Explain why a specific profile could not yet be selected |
| `general` | The task is bounded but does not need a specialist contract | Actions, decisions, deliverables, open items | Direct completion checks |
| `research` | Questions, explanations, or evidence must be investigated | Findings, claims, hypotheses, assumptions, dead ends | Source/code/log/test references and falsification |
| `security_research` | Authorized security investigation or validation | Findings, hypotheses, reproductions, affected boundaries | Reproduction or falsification within explicit target/action scope |
| `engineering` | Code, tests, configuration, migrations, refactors, or tooling are created or changed | Requirements, changes, tests, review findings, acceptance criteria | Focused tests, static checks, build/integration checks |
| `review` | An existing artifact must be audited, critiqued, or approved | Findings, risks, decisions, checked items | Coverage statement, severity/rationale, independent checks |
| `documentation` | Technical or user documentation is planned, drafted, revised, or verified | Audience, requirements, outline/drafts, feedback, examples | Link/example/command checks and editorial criteria |
| `planning` | Decisions, architecture, milestones, dependencies, or execution plans are required | Decisions, assumptions, milestones, dependencies, unresolved choices | Feasibility, dependency, risk, and acceptance review |
| `data` | Data is inspected, transformed, validated, analyzed, or reported | Inputs, transformations, quality checks, outputs, metrics | Reconciliation, schema, completeness, and reproducibility checks |
| `operations` | Bounded operational work is prepared or performed | Actions, observations, validation, approvals, rollback state | Health checks, post-action verification, rollback readiness |
| `content` | Prose, structured content, creative material, or communications are produced | Requirements, drafts, variants, feedback, final deliverables | Audience/style/brief checks and independent critique |
| `mixed` | One episode intentionally combines multiple profiles | State kinds from each relevant profile | Explicitly identify which criteria were applied to each output |

## Phase changes

A profile is an episode-level choice, not a permanent campaign label. Common sequences include:

```text
research → engineering → review → documentation → closure
planning → engineering → execute_validate → closure
data → documentation/content → review → closure
content → producer_critic → review → closure
operations planning → approval needed → execute_validate → closure
```

The next-option record should suggest the profile that best fits the proposed next objective. A profile change must not broaden operating boundaries or permissions.

## Task-neutral state

The `state_updates` array uses durable kinds such as:

- `finding`, `claim`, `hypothesis`, `assumption`, and `dead_end`;
- `requirement`, `acceptance_criterion`, `change`, `test`, and `review_finding`;
- `decision`, `milestone`, `dependency`, and `open_item`;
- `input`, `transformation`, `quality_check`, `output`, and `metric`;
- `action`, `observation`, `rollback`, `risk`, and `blocker`;
- `draft`, `feedback`, and `other`.

Use stable ids when updating a prior state item so later episodes can recognize superseded or completed work.
