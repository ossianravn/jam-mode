#!/usr/bin/env python3
"""Portable launcher for the JAM companion CLI."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
# Put the plugin package ahead of the launcher directory even when callers
# already included it later in PYTHONPATH. This prevents scripts/jam.py from
# shadowing the top-level ``jam`` package.
try:
    sys.path.remove(str(PLUGIN_ROOT))
except ValueError:
    pass
sys.path.insert(0, str(PLUGIN_ROOT))

from jam.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
