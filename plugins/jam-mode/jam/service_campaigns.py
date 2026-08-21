from __future__ import annotations

from pathlib import Path
from typing import Any

from .controller import spawn_controller
from .paths import campaign_dir
from .routing import inspect_managed_agents
from .service_boundaries import _assert_single_live_campaign
from .service_refresh import refresh_campaign_routing
from .store import Store
from .util import process_is_alive, utc_now


def get_status(identifier: str | None = None) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    last = store.last_episode(campaign["id"])
    episodes = store.list_episodes(campaign["id"], limit=20)
    return {
        "campaign": campaign,
        "controller_alive": process_is_alive(campaign.get("controller_pid")),
        "last_episode": last,
        "episodes": episodes,
        "campaign_directory": str(campaign_dir(campaign["id"])),
        "managed_agents": inspect_managed_agents(),
    }


def list_campaigns() -> list[dict[str, Any]]:
    return Store().list_campaigns(limit=200)


def pause_campaign(identifier: str | None = None) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    if campaign.get("active_episode_id"):
        status = "pausing_after_current"
        message = "JAM will pause after the current episode finishes naturally."
    else:
        status = "paused"
        message = "JAM is paused. No new episode will start."
    updated = store.transition_campaign(
        campaign["id"],
        status,
    )
    return {"campaign": updated, "message": message}


def resume_campaign(
    identifier: str | None = None, *, guidance: str | None = None
) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    _assert_single_live_campaign(store, exclude_id=campaign["id"])
    if guidance:
        store.append_guidance(campaign["id"], guidance)
    refresh = refresh_campaign_routing(campaign["id"])
    updated = store.transition_campaign(
        campaign["id"],
        "queued",
        completed_at=None,
        last_error=None,
    )
    pid = spawn_controller(campaign["id"])
    return {
        "campaign": store.get_campaign(campaign["id"]),
        "controller_pid": pid,
        "managed_agents": refresh["managed_agents"],
        "routing_warnings": refresh["routing_warnings"],
    }


def stop_campaign(identifier: str | None = None) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    active = bool(campaign.get("active_episode_id"))
    updated = store.transition_campaign(
        campaign["id"],
        "stopping_after_current" if active else "stopped",
        completed_at=None if active else utc_now(),
    )
    return {
        "campaign": updated,
        "message": (
            "The current episode will finish naturally, then the campaign will stop."
            if active
            else "The campaign is stopped."
        ),
    }


def add_memory_path(identifier: str | None, path: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"Memory path does not exist: {resolved}")
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    updated = store.add_memory_path(campaign["id"], str(resolved))
    return {"campaign": updated, "memory_path": str(resolved)}


def campaign_log(identifier: str | None = None, *, tail: int = 120) -> dict[str, Any]:
    campaign = Store().get_campaign(identifier or "active")
    path = campaign_dir(campaign["id"]) / "controller.log"
    if not path.exists():
        text = ""
    else:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        text = "\n".join(lines[-max(1, tail) :])
    return {"campaign_id": campaign["id"], "path": str(path), "text": text}
