from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class HarnessError(ValueError):
    """The selected harness cannot satisfy the requested execution contract."""


@dataclass(frozen=True)
class HarnessRequest:
    campaign: dict[str, Any]
    episode: dict[str, Any]
    prompt: str
    events_path: Path
    stderr_path: Path
    timeout_seconds: float


@dataclass
class HarnessResult:
    session_id: str
    status: str
    final_text: str
    error: str | None = None
    agent_activity: list[dict[str, Any]] = field(default_factory=list)
    model_events: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, Any] | None = None
    turn_id: str | None = None


class HarnessAdapter(Protocol):
    def inspect(self) -> dict[str, Any]: ...
    def models(self) -> dict[str, Any]: ...
    def run(self, request: HarnessRequest) -> HarnessResult: ...
