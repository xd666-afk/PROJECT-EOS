"""Persistent stochastic weather built on the restored v0.1 weather_day function."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

from core.state import MONTH_DAYS, WorldStatic
from worldgen import weather_day

MONTH_ENDS = np.cumsum(MONTH_DAYS)


class WeatherModel:
    def __init__(
        self,
        world: WorldStatic,
        seed: int,
        saved: dict[str, Any] | None = None,
    ) -> None:
        tiles = world.data["tiles"]
        width = world.data["metadata"]["grid_width"]
        height = world.data["metadata"]["grid_height"]
        self.width = width
        self.height = height
        self.land = np.array([tile["land"] for tile in tiles]).reshape(height, width)
        self.monthly_temp = np.array(
            [tile["monthly_temp_c"] for tile in tiles]
        ).reshape(height, width, 12).transpose(2, 0, 1)
        self.monthly_rain = np.array(
            [tile["monthly_precip_mm"] for tile in tiles]
        ).reshape(height, width, 12).transpose(2, 0, 1)
        self.capitals = {
            country_id: (polity["capital"]["row"], polity["capital"]["col"])
            for country_id, polity in world.polities.items()
        }
        self.rng = np.random.default_rng(seed)
        self.anomaly = np.zeros((height, width))
        self.month_accumulators = self._empty_accumulators()
        if saved is not None:
            self.rng.bit_generator.state = saved["rng_state"]
            anomaly = np.array(saved["anomaly"], dtype=float)
            if anomaly.shape != (height, width):
                raise ValueError("saved weather anomaly has the wrong shape")
            self.anomaly = anomaly
            self.month_accumulators = saved["month_accumulators"]

    def _empty_accumulators(self) -> dict[str, dict[str, float]]:
        return {
            country_id: {"rain": 0.0, "temperature": 0.0, "days": 0}
            for country_id in self.capitals
        }

    def forget(self, country_id: str) -> None:
        """Stop reporting capital weather for a realm that has left the board.

        The grid keeps being sampled exactly as before, so this cannot move a single
        raindrop of an action-log replay; it only drops the dead realm's rows.
        """
        self.capitals.pop(country_id, None)
        self.month_accumulators.pop(country_id, None)

    def sample(self, day_index: int) -> dict[str, np.ndarray]:
        self.anomaly, rain, temperature, snow = weather_day(
            self.rng,
            day_index,
            self.monthly_rain,
            self.monthly_temp,
            self.land,
            self.anomaly,
        )
        return {
            "rain": rain,
            "temperature": temperature,
            "snow": snow,
            "anomaly": self.anomaly,
        }

    def observe_day(self, rain: np.ndarray, temperature: np.ndarray) -> None:
        for country_id, (row, col) in self.capitals.items():
            values = self.month_accumulators[country_id]
            values["rain"] += float(rain[row, col])
            values["temperature"] += float(temperature[row, col])
            values["days"] += 1

    @staticmethod
    def is_month_end(day_index: int) -> bool:
        return day_index % 365 + 1 in set(MONTH_ENDS.tolist())

    def complete_month(self, day_index: int) -> dict[str, Any]:
        month = int(np.searchsorted(MONTH_ENDS, day_index % 365 + 1, side="left"))
        result: dict[str, Any] = {"month": month + 1, "countries": {}}
        for country_id, (row, col) in self.capitals.items():
            values = self.month_accumulators[country_id]
            days = max(int(values["days"]), 1)
            expected = float(self.monthly_rain[month, row, col]) * days / MONTH_DAYS[month]
            result["countries"][country_id] = {
                "rain_mm": round(values["rain"], 4),
                "expected_rain_mm": round(expected, 4),
                "average_temperature_c": round(values["temperature"] / days, 4),
                "rain_anomaly_ratio": round(values["rain"] / max(expected, 1.0), 6),
                "days": days,
            }
        self.month_accumulators = self._empty_accumulators()
        return result

    def random(self) -> float:
        return float(self.rng.random())

    def uniform(self, minimum: float, maximum: float) -> float:
        return float(self.rng.uniform(minimum, maximum))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rng_state": deepcopy(self.rng.bit_generator.state),
            "anomaly": self.anomaly.tolist(),
            "month_accumulators": self.month_accumulators,
        }
