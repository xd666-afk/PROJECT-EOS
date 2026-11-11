"""Cheap, deterministic frontier expansion for AI-controlled countries."""
from __future__ import annotations

from worldgen import neighbors


def _owned_map(state) -> dict[tuple[int, int], str]:
    return {
        coord: country.country_id
        for country in state.countries.values()
        for coord in country.tiles
    }


def choose_frontier(state, country) -> tuple[int, int] | None:
    """Pick a useful adjacent unowned land tile, preferring safe/river/grassland."""
    owned = _owned_map(state)
    candidates: dict[tuple[int, int], tuple[float, int, int]] = {}
    for origin in country.tiles:
        for coord in state.world.neighbors(*origin):
            if coord in owned or coord in candidates:
                continue
            tile = state.world.tile(coord)
            if not tile["land"]:
                continue
            foreign_neighbor = any(
                neighbor in owned and owned[neighbor] != country.country_id
                for neighbor in state.world.neighbors(*coord)
            )
            biome = {
                "grassland": 4.0, "savanna": 3.2,
                "wetland": 3.0, "forest": 2.6, "steppe": 2.0,
                "desert": 0.8, "alpine": 0.2, "tundra": 0.2,
            }.get(tile["biome"], 0.5)
            score = (
                (0 if foreign_neighbor else 10)
                + (2.5 if tile["river"] else 0)
                + biome
                - abs(coord[0] - country.cities[0].center[0]) * 0.01
                - abs(coord[1] - country.cities[0].center[1]) * 0.01
            )
            candidates[coord] = (score, -coord[1], -coord[0])
    if not candidates:
        return None
    return max(candidates, key=candidates.get)


def frontier_ready(state, country, interval_days: int, treasury_reserve: float) -> bool:
    expansion = state.config["expansion"]
    if len(country.outposts) >= expansion["max_outposts"]:
        return False
    if country.population < expansion["minimum_population"]:
        return False
    if country.treasury < expansion["treasury_cost"] + treasury_reserve:
        return False
    last_founded = max((city.founded_day for city in country.cities), default=0)
    return state.day_index - last_founded >= interval_days
