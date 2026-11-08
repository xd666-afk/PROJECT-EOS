"""Country controller interface; implementations return JSON actions only."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CountryAgent(ABC):
    @abstractmethod
    async def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Return {country_id, world_day, actions[], reason} without mutating state."""
