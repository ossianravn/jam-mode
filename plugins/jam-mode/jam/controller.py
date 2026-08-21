from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any

from .campaign_runner import run_campaign
from .controller_decisions import (
    _budget_gate,
    _elapsed_minutes,
    _turn_timeout_seconds,
    continuation_decision,
    next_episode_plan,
)
from .paths import campaign_dir, plugin_root
from .store import Store
from .util import epoch_now, process_is_alive


def spawn_controller(campaign_id: str) -> int:
    store = Store()
    campaign = store.get_campaign(campaign_id)
    lease_expiry = campaign.get("lease_expires_at")
    pid = campaign.get("controller_pid")
    if lease_expiry and float(lease_expiry) > epoch_now() and process_is_alive(pid):
        return int(pid)

    log_path = campaign_dir(campaign_id) / "controller.log"
    log_handle = log_path.open("a", encoding="utf-8")
    env = os.environ.copy()
    root = str(plugin_root())
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")
    command = [sys.executable, "-m", "jam.controller", "run", campaign_id]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "cwd": campaign["workspace"],
        "env": env,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    log_handle.close()
    store.update_campaign(campaign_id, controller_pid=process.pid)
    return process.pid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JAM Mode campaign controller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("campaign_id")
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("campaign_id")
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_campaign(args.campaign_id)
    pid = spawn_controller(args.campaign_id)
    print(pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
