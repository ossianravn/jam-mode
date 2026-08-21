from __future__ import annotations


ACTIVE_EPISODE_PREDICATE = (
    "ended_at IS NULL AND status IN ('queued', 'running')"
)


class StoreMigrationError(RuntimeError):
    pass
