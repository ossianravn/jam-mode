from __future__ import annotations

import threading

from .paths import campaign_dir
from .routing import routing_prompt_summary
from .store import Store
from .util import atomic_write, json_dumps


LEASE_TTL_SECONDS = 240
HEARTBEAT_SECONDS = 45


class LeaseHeartbeat:
    def __init__(self, store: Store, campaign_id: str, token: str) -> None:
        self.store = store
        self.campaign_id = campaign_id
        self.token = token
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            try:
                if not self.store.refresh_lease(
                    self.campaign_id, self.token, ttl_seconds=LEASE_TTL_SECONDS
                ):
                    return
            except Exception:
                return

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3)


def _write_campaign_summary(store: Store, campaign_id: str) -> None:
    campaign = store.get_campaign(campaign_id)
    episodes = list(reversed(store.list_episodes(campaign_id)))
    lines = [
        f"# {campaign['name']}",
        "",
        f"- ID: `{campaign['id']}`",
        f"- Status: **{campaign['status']}**",
        f"- Workspace: `{campaign['workspace']}`",
        f"- Task profile: `{campaign.get('task_profile') or 'adaptive'}`",
        f"- Episodes: {campaign['episode_count']} / {campaign['max_episodes']}",
        f"- Model policy: `{campaign.get('model_policy') or 'inherit'}`",
        f"- Model validation: `{campaign.get('model_validation') or 'fallback'}`",
        "",
        "## Model and agent routing",
        "",
        "```text",
        routing_prompt_summary(campaign.get("resolved_routing") or {}),
        "```",
        "",
        "## Objective",
        "",
        campaign["objective"],
        "",
        "## Operating boundaries",
        "",
        "```json",
        json_dumps(
            campaign.get("operating_boundaries") or campaign.get("authorized_scope") or {},
            pretty=True,
        ),
        "```",
        "",
        "## Episode history",
        "",
    ]
    for episode in episodes:
        handoff = episode.get("handoff") or {}
        lines.extend(
            [
                f"### Episode {episode['number']}: {episode['objective']}",
                "",
                f"- Status: `{episode['status']}`",
                f"- Task profile: `{episode.get('task_profile_used') or episode.get('task_profile_hint') or handoff.get('task_profile') or 'unknown'}`",
                f"- Strategy: `{episode.get('strategy_used') or episode.get('strategy_hint') or 'unknown'}`",
                f"- Thread: `{episode.get('thread_id') or 'not recorded'}`",
                "",
                str(handoff.get("summary") or episode.get("error") or "No summary recorded."),
                "",
            ]
        )
    atomic_write(campaign_dir(campaign_id) / "campaign.md", "\n".join(lines))
