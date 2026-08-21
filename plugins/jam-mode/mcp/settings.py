from __future__ import annotations

import os


DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "jam-mode"
CHILD_SESSION = os.environ.get("JAM_CHILD_SESSION") == "1"


class ToolFailure(RuntimeError):
    pass
