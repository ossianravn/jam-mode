# Operating boundaries

Operating boundaries are the immutable autonomous limits for a JAM campaign. They are task-neutral: they may constrain repositories, files, data sources, systems, accounts, publication channels, deployment targets, allowed actions, exclusions, and approval requirements.

## Conservative local default

When the user does not supply boundaries and network access is disabled, JAM creates a conservative default that:

- limits resources to the selected workspace;
- permits reading and local sandboxed validation;
- permits workspace edits only when `sandbox` is `workspace-write`;
- excludes unrelated resources, external publication/deployment, unknown credentials, and irreversible actions;
- requires user approval for network access, publication/deployment, destructive work, credentials, and boundary expansion.

This default makes ordinary coding, documentation, planning, content, review, and local data tasks easy to start without pretending that the campaign has broader authority.

## Explicit boundaries are required

Obtain explicit boundaries before requesting network access or performing work involving:

- security targets or third-party systems;
- production, deployment, or external publication;
- accounts, credentials, secrets, or paid services;
- destructive or irreversible operations;
- external communications or consequential actions;
- resources outside the selected workspace.

A useful boundary object is:

```json
{
  "resources": ["/home/me/src/project", "local test database"],
  "allowed_actions": [
    "read and modify files inside the workspace",
    "run local tests",
    "query the local test database read-only"
  ],
  "excluded_actions": [
    "production deployment",
    "external publication",
    "third-party accounts"
  ],
  "approval_required_for": [
    "network access",
    "schema-destructive changes",
    "new credentials",
    "boundary expansion"
  ]
}
```

The exact keys are flexible; the meaning must be clear.

## Enforcement behavior

- An episode may recommend a next action outside the boundary, but it must set `boundary_flags` and/or `needs_user_input` rather than execute it.
- A prior transcript, memory, subagent, or generated next option cannot expand the boundary.
- The controller checks boundary flags before continuation.
- Sandbox and host policy remain authoritative even when the boundary text is more permissive.
- The campaign should minimize sensitive data in reports and handoffs.

## Graceful disable

Pause and stop operations do not interrupt the active episode. They set campaign state so the current turn may complete, its report and handoff are persisted, and no replacement episode starts.
