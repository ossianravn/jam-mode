from __future__ import annotations

from .store_campaign_updates import CampaignUpdateStoreMixin
from .store_campaigns import CampaignStoreMixin
from .store_core import (
    CampaignNotFound,
    CampaignNotRunnable,
    StoreCore,
    StoreError,
)
from .store_episodes import EpisodeStoreMixin
from .store_leases import LeaseStoreMixin


class Store(
    CampaignUpdateStoreMixin,
    CampaignStoreMixin,
    EpisodeStoreMixin,
    LeaseStoreMixin,
    StoreCore,
):
    """SQLite-backed campaign store shared by Desktop, CLI, and workers."""
