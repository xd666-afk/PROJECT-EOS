"""Road-network connectivity and the diplomatic gate for cross-border roads."""
from __future__ import annotations

from typing import Any

from worldgen import hex_distance


def built_roads(country):
    return set(getattr(country, "roads", ())) | {p for p, b in country.buildings.items() if b == "ROAD"}


def river_width(world, coord):
    """Shortest straight bank-to-bank cross section on the three hex axes.

    A connected river's *length* never becomes its width. Only sections with
    two dry land banks count; lakes and the map edge cannot act as banks.
    """
    def axial(p):
        x, y = p
        return x - (y - (y & 1)) // 2, y
    def offset(q, r):
        return q + (r - (r & 1)) // 2, r
    q, r = axial(coord)
    widths = []
    for dq, dr in ((1, 0), (0, 1), (1, -1)):
        width, banks = 1, 0
        for sign in (-1, 1):
            n = 1
            while True:
                p = offset(q + sign * n * dq, r + sign * n * dr)
                tile = world.tiles.get(p)
                if tile is None or not tile.get("land"):
                    break
                if not tile.get("river"):
                    banks += 1
                    break
                width += 1
                n += 1
        if banks == 2:
            widths.append(width)
    return min(widths) if widths else None


def road_permit(state, country, coord):
    tile = state.world.tiles.get(coord)
    if coord not in country.tiles:
        return "TILE_NOT_OWNED", "只能在本国领土修筑道路"
    if not tile or not tile.get("land") or tile["biome"] in {"ocean", "lake"}:
        return "INVALID_TERRAIN", "海洋和湖泊不能修路，也不能作为桥梁支点"
    if tile["biome"] not in state.config["buildings"]["ROAD"]["allowed_biomes"]:
        return "INVALID_TERRAIN", "该地形不在道路修筑范围内"
    known = set(getattr(country, "known_techs", ()))
    rules = state.config["road_rules"]
    for biome, requirement in rules["terrain_technology"].items():
        if tile["biome"] == biome and requirement not in known:
            return "ROAD_TERRAIN_TECH_REQUIRED", f"{rules['terrain_names'][biome]}道路需要研究「{state.config['research_tree'][requirement]['name']}」"
    if tile.get("river"):
        width = river_width(state.world, coord)
        limit = rules["modern_bridge_width"] if "modern_engineering" in known else rules["ancient_bridge_width"]
        if width is None or width > limit:
            return "ROAD_RIVER_TOO_WIDE", f"河流横断面{str(width) + '格' if width else '缺少两岸陆地'}，当前桥梁许可最多 {limit} 格"
        if "masonry_bridges" not in known:
            return "ROAD_BRIDGE_TECH_REQUIRED", "跨河道路需要研究「石拱桥梁」"
    return None


def road_quote(state, country, coord):
    from core.technology import bonus
    tile = state.world.tile(coord)
    factor = state.config["road_rules"]["terrain_multiplier"].get(tile["biome"], 1.0)
    if tile.get("river"):
        factor *= state.config["road_rules"]["bridge_multiplier"]
    factor *= max(0.25, 1 - bonus(country, state.config, "road_discount"))
    spec = state.config["buildings"]["ROAD"]
    return round(spec["cost"] * factor, 4), round(spec["days"] * factor, 4)


def road_node_owners(state: Any, country: Any, coord: tuple[int, int], include_pending=True) -> set[str]:
    """Owners of road nodes adjacent to the target tile.

    Cities, built ROAD improvements and map road cells are nodes. Ownership
    follows the live territory after conquest; an eliminated historical road
    sponsor no longer imposes a diplomatic gate on neutral ground.
    """
    owners: set[str] = set()
    for city in country.cities:
        if hex_distance(coord, tuple(city.center)) <= 1:
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
        for road_coord in built_roads(other):
            if hex_distance(coord, road_coord) == 1:
                owners.add(other.country_id)
        for project in getattr(other, "projects", ()):
            if include_pending and other.country_id == country.country_id and project["building"] == "ROAD" and hex_distance(coord, tuple(project["tile"])) == 1:
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
    include_pending=True,
) -> tuple[bool, list[str], set[str]]:
    """Return (connected, denied_foreign_owners, all_adjacent_owners)."""
    owners = road_node_owners(state, country, coord, include_pending)
    threshold = state.road_connection_level()
    denied = sorted(
        owner for owner in owners - {country.country_id}
        if state.diplomatic_level(country.country_id, owner) < threshold
    )
    return bool(owners) and not denied, denied, owners
