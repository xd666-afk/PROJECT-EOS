"""Delegable AI city managers. They only touch cities explicitly marked as delegated."""
from __future__ import annotations

from collections import Counter

from core.society import city_housing
from worldgen import neighbors


class CityManager:
    FOCUS_BY_COUNTRY = {
        "ELAR": "growth",
        "SAHAR": "growth",
        "MARIS": "commerce",
        "VAYR": "industry",
    }
    FOCUS_BY_ARCHETYPE = {
        "river_valley": "growth",
        "semiarid": "growth",
        "maritime": "commerce",
        "highland": "industry",
    }
    FOCUS_ZONE = {"growth": "farm", "industry": "industry", "commerce": "commerce"}

    def __init__(self, state) -> None:
        self.state = state

    def plan(self, engine) -> None:
        for country in self.state.countries.values():
            polity = self.state.world.polities.get(country.country_id, {})
            national_focus = self.FOCUS_BY_COUNTRY.get(
                country.country_id,
                self.FOCUS_BY_ARCHETYPE.get(polity.get("type"), "balanced"),
            )
            for city in country.cities:
                if city.managed_by != "ai":
                    continue
                self_sufficiency = (
                    city.food_output / city.food_need if city.food_need > 1e-9 else 1.0
                )
                food_pressed = self_sufficiency < 0.95
                health_pressed = city.health < self.state.config["city_services"][
                    "low_threshold"
                ]
                personality = getattr(country, "personality", "neutral")
                if food_pressed:
                    desired_focus = "growth"
                elif personality == "aggressive":
                    desired_focus = "industry"
                elif personality == "conservative":
                    desired_focus = "growth"
                else:
                    desired_focus = national_focus
                if desired_focus != "balanced" and city.focus != desired_focus:
                    engine.apply_action(country.country_id, {
                        "type": "SET_CITY_FOCUS",
                        "city_id": city.city_id,
                        "focus": desired_focus,
                    })
                desired_budget = self._desired_budget(country, city, personality)
                if city.budget != desired_budget:
                    engine.apply_action(country.country_id, {
                        "type": "SET_CITY_BUDGET",
                        "city_id": city.city_id,
                        "budget": desired_budget,
                    })
                desired_zone = self._desired_zone(
                    country, city, desired_focus, food_pressed, health_pressed
                )
                if desired_zone is None:
                    continue
                zone_counts = Counter(city.zones.values())
                target_count = max(1, len(city.tiles) // 6)
                if desired_zone == "farm" and food_pressed:
                    target_count = max(target_count, len(city.tiles) // 4)
                candidates = [
                    coord for coord in city.tiles
                    if coord != city.center and city.zones.get(coord) != desired_zone
                ]
                if desired_zone == "residential" and health_pressed:
                    industry_candidates = [
                        coord for coord in candidates
                        if city.zones.get(coord) == "industry"
                    ]
                    if industry_candidates:
                        candidates = industry_candidates
                if not candidates:
                    continue
                target = max(
                    candidates,
                    key=lambda coord: (
                        sum(
                            1 for neighbor in neighbors(*coord)
                            if city.zones.get(neighbor) == desired_zone
                        ),
                        -abs(coord[0] - city.center[0]) - abs(coord[1] - city.center[1]),
                        -coord[1], -coord[0],
                    ),
                )
                engine.apply_action(country.country_id, {
                    "type": "SET_CITY_ZONE",
                    "city_id": city.city_id,
                    "tile": {"col": target[0], "row": target[1]},
                    "zone": desired_zone,
                })

    def _desired_budget(self, country, city, personality: str = "neutral") -> str:
        low_service = min(city.security, city.health) < self.state.config[
            "city_services"
        ]["low_threshold"]
        if personality == "aggressive":
            if low_service and country.treasury >= 10:
                return "investment"
            if city.livability < 58 and country.treasury >= 15:
                return "investment"
            return "balanced" if country.treasury >= 8 else "austerity"
        if personality == "conservative":
            if country.treasury < 45 and city.local_net < 0:
                return "austerity"
            if low_service and country.treasury >= 30:
                return "investment"
            return "balanced"
        if country.treasury < 10 and city.local_net < 0:
            return "austerity"
        if low_service and country.treasury >= 15:
            return "investment"
        if city.livability < 55 and country.treasury >= 25:
            return "investment"
        return "balanced"

    def _desired_zone(
        self,
        country,
        city,
        focus: str,
        food_pressed: bool = False,
        health_pressed: bool = False,
    ) -> str | None:
        housing = city_housing(city, country, self.state.config)
        crowded = city.population / 1000.0 >= housing - 2
        zone_counts = Counter(city.zones.values())
        if food_pressed:
            farm_target = max(1, len(city.tiles) // 4)
            if zone_counts.get("farm", 0) < farm_target:
                return "farm"
        residential = zone_counts.get("residential", 0)
        if health_pressed and residential < max(1, len(city.tiles) // 6):
            return "residential"
        if crowded and residential < max(1, len(city.tiles) // 6):
            return "residential"
        return self.FOCUS_ZONE.get(focus)
