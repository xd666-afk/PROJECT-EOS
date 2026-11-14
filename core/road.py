"""Road-network connectivity and the diplomatic gate for cross-border roads."""
from __future__ import annotations

from typing import Any

from worldgen import hex_distance


def road_node_owners(state: Any, country: Any, coord: tuple[int, int]) -> set[str]:
    """Owners of road nodes adjacent to the target tile.

    Cities, built ROAD improvements and map road cells are nodes. Ownership
    follows the live territory after conquest; an eliminated historical road
    sponsor no longer imposes a diplomatic gate on neutral ground.
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
    tile_owners = {}
    for other in state.countries.values():
        for tile in getattr(other, "tiles", ()):
            tile_owners[tuple(tile)] = other.country_id
        for road_coord, building in other.buildings.items():
            if building == "ROAD" and hex_distance(coord, road_coord) == 1:
                owners.add(other.country_id)
    for cell in state.world.road_cells():
        road_coord = (int(cell["tile"]["col"]), int(cell["tile"]["row"]))
        if hex_distance(coord, road_coord) == 1:
            owner_id = tile_owners.get(road_coord, cell.get("owner_id"))
            owners.add(str(owner_id) if owner_id in state.countries else country.country_id)
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
