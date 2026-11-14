"""Road-network connectivity and the diplomatic gate for cross-border roads."""
from __future__ import annotations

from typing import Any

from worldgen import hex_distance


def road_node_owners(state: Any, country: Any, coord: tuple[int, int]) -> set[str]:
    """Owners of road nodes adjacent to the target tile.

    Own cities, own built ROAD improvements and map road cells are nodes.
    Foreign city centers are nodes too; whether they may be connected is
    decided by the diplomatic level.
    """
    owners: set[str] = set()
    for city in country.cities:
        if hex_distance(coord, tuple(city.center)) == 1:
            owners.add(country.country_id)
    for other in state.countries.values():
        if other.country_id == country.country_id:
            continue
        for city in other.cities:
            if hex_distance(coord, tuple(city.center)) == 1:
                owners.add(other.country_id)
    for road_coord, building in country.buildings.items():
        if building == "ROAD" and hex_distance(coord, road_coord) == 1:
            owners.add(country.country_id)
    for cell in state.world.road_cells():
        road_coord = (int(cell["tile"]["col"]), int(cell["tile"]["row"]))
        if hex_distance(coord, road_coord) == 1:
            owner_id = cell.get("owner_id")
            if owner_id:
                owners.add(str(owner_id))
    return owners


def road_connection_status(
    state: Any,
    country: Any,
    coord: tuple[int, int],
) -> tuple[bool, list[str], set[str]]:
    """Return (connected, denied_foreign_owners, all_adjacent_owners)."""
    owners = road_node_owners(state, country, coord)
    threshold = state.road_connection_level()
    denied = sorted(
        owner for owner in owners - {country.country_id}
        if state.diplomatic_level(country.country_id, owner) < threshold
    )
    return bool(owners) and not denied, denied, owners
