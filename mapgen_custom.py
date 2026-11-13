"""Hand-drawn maps: a painted draft becomes a playable world, priced by the same march model.

The painter only stores terrain, rivers, roads and capitals. Everything the settlement needs
— climate, hydrology, hazards, core territory, fairness — is derived here from that draft.
`march_preview` runs `core.movement.Movement` over the drafted tiles, so the day count shown
while painting is the number the engine will use once the map is in play.
"""
from __future__ import annotations

from collections import deque
import hashlib
import heapq
import json
import math
from pathlib import Path
from typing import Any
import zlib

import numpy as np

import mapgen
import worldgen
from core.movement import Movement
from mapgen_v2 import DEPTH_STOPS
from worldgen import CELL_AREA_KM2, R_KM, hex_distance, neighbors

BASE_DIR = Path(__file__).resolve().parent
DRAFT_WIDTH, DRAFT_HEIGHT = mapgen.W, mapgen.H
MAX_DRAFT_TILES = DRAFT_WIDTH * DRAFT_HEIGHT

# The brush vocabulary is the single source for the painter palette, the derived tiles and
# the march costs in config/rules.json: one biome name, one char, one price.
BIOME_CHARS = {
    "o": "ocean", "g": "grassland", "f": "forest", "j": "rainforest", "v": "savanna",
    "t": "steppe", "m": "wetland", "d": "desert", "c": "tundra", "l": "alpine",
}
CHAR_BIOMES = {biome: char for char, biome in BIOME_CHARS.items()}
BIOME_LABELS = {
    "ocean": "海洋", "grassland": "草原", "forest": "森林", "rainforest": "雨林",
    "savanna": "稀树草原", "steppe": "半干旱草原", "wetland": "湿地", "desert": "沙漠",
    "tundra": "冻原", "alpine": "高山",
}
# elevation band (m), temperature bias (°C), annual precipitation band (mm), hazard lean
TERRAIN = {
    "ocean": ((-2200, -60), 0.5, (700, 1500), {"cyclone": 0.45, "flood": 0.15}),
    "grassland": ((60, 420), 0.0, (480, 820), {"flood": 0.3, "wildfire": 0.3}),
    "forest": ((60, 640), -0.8, (600, 1100), {"wildfire": 0.45, "earthquake": 0.15}),
    "rainforest": ((40, 520), 1.6, (1400, 2400), {"flood": 0.5, "cyclone": 0.3}),
    "savanna": ((120, 700), 1.2, (500, 900), {"drought": 0.55, "wildfire": 0.4}),
    "steppe": ((150, 760), -0.5, (260, 520), {"drought": 0.5}),
    "wetland": ((0, 120), -0.4, (800, 1500), {"flood": 0.6}),
    "desert": ((120, 900), 1.4, (60, 220), {"drought": 0.8}),
    "tundra": ((40, 400), -9.0, (140, 320), {"drought": 0.2}),
    "alpine": ((900, 2600), -4.5, (300, 700), {"earthquake": 0.6}),
}
LAT_TOP, LAT_BOTTOM = 51.0, 8.0
HAZARD_TYPES = ("flood", "drought", "earthquake", "volcano", "wildfire", "cyclone")


def noise(seed: int, col: int, row: int, tag: str) -> float:
    """Deterministic [0, 1) value — zlib.crc32 stays stable across processes and runs."""
    digest = zlib.crc32(f"{seed}:{col}:{row}:{tag}".encode("utf-8"))
    return (digest & 0xFFFFFF) / 0x1000000


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def palette() -> list[dict[str, Any]]:
    """Brush table for the painter, carrying the march price the engine will apply."""
    return [
        {
            "char": char,
            "biome": biome,
            "label": BIOME_LABELS[biome],
            "color": worldgen.BIOME_COLORS[biome],
            "land": biome != "ocean",
        }
        for char, biome in BIOME_CHARS.items()
    ]


def _coord(raw: Any, where: str, width: int, height: int) -> tuple[int, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError(f"{where} 必须是 [列, 行] 两个坐标")
    col, row = int(raw[0]), int(raw[1])
    if not 0 <= col < width or not 0 <= row < height:
        raise ValueError(f"{where} ({col},{row}) 超出地图范围")
    return col, row


def normalize_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a painted draft and expand it into a coordinate keyed tile table."""
    if not isinstance(payload, dict):
        raise ValueError("地图草稿必须是一个对象")
    grid = payload.get("grid")
    if not isinstance(grid, list) or not grid:
        raise ValueError("地图草稿缺少地形格网 grid")
    if len(grid) != DRAFT_HEIGHT:
        raise ValueError(f"地图高度固定为 {DRAFT_HEIGHT} 行，当前 {len(grid)} 行")
    rows = [str(line) for line in grid]
    for index, line in enumerate(rows):
        if len(line) != DRAFT_WIDTH:
            raise ValueError(f"第 {index + 1} 行宽度为 {len(line)}，应为 {DRAFT_WIDTH} 列")
        unknown = sorted({char for char in line if char not in BIOME_CHARS})
        if unknown:
            raise ValueError(f"第 {index + 1} 行含未知地形字符 {''.join(unknown)}")
    if sum(line.count("o") == len(line) for line in rows) == len(rows):
        raise ValueError("全海地图无法定居，请先绘制陆地")
    if not any("o" in line for line in rows):
        # Hydrology drains every land tile toward the sea; a map with no ocean has nowhere
        # for its rivers to run, so the settlement contract cannot be satisfied.
        raise ValueError("地图至少需要一格海洋，否则河流没有入海口")

    width, height = DRAFT_WIDTH, DRAFT_HEIGHT
    tiles: dict[tuple[int, int], dict[str, Any]] = {}
    for row, line in enumerate(rows):
        for col, char in enumerate(line):
            biome = BIOME_CHARS[char]
            tiles[(col, row)] = {
                "biome": biome,
                "land": biome != "ocean",
                "river": False,
                "road": False,
            }

    rivers = payload.get("rivers") or []
    roads = payload.get("roads") or []
    for name, raw_list, flag in (("河流", rivers, "river"), ("道路", roads, "road")):
        if not isinstance(raw_list, list):
            raise ValueError(f"{name}图层必须是坐标列表")
        for raw in raw_list:
            coord = _coord(raw, f"{name}坐标", width, height)
            if not tiles[coord]["land"]:
                raise ValueError(f"{name}只能画在陆地上：({coord[0]},{coord[1]}) 是海洋")
            tiles[coord][flag] = True

    polities = payload.get("polities")
    if not isinstance(polities, list) or not polities:
        raise ValueError("手绘地图需要用「都城」画笔标出至少一个国家")
    countries = mapgen.normalize_countries(
        [
            {
                "name": item.get("name"),
                "color": item.get("color"),
                "archetype": item.get("archetype"),
                "population": item.get("population"),
            }
            for item in polities
        ]
    )
    capitals = []
    for index, (country, item) in enumerate(zip(countries, polities)):
        capital = _coord(item.get("capital"), f"国家 {country['name']} 的都城", width, height)
        if not tiles[capital]["land"]:
            raise ValueError(f"国家 {country['name']} 的都城必须位于陆地")
        if capital in capitals:
            raise ValueError(f"国家 {country['name']} 的都城与其他国家重叠")
        capitals.append(capital)
        country["capital"] = capital
    minimum_gap = int(payload.get("capital_separation", 4))
    for i, first in enumerate(capitals):
        for second in capitals[i + 1:]:
            if hex_distance(first, second) < minimum_gap:
                raise ValueError(
                    f"两个都城至少相隔 {minimum_gap} 格，当前 {hex_distance(first, second)} 格")

    return {
        "width": width,
        "height": height,
        "grid": rows,
        "tiles": tiles,
        "countries": countries,
        "capitals": capitals,
        "seed": int(payload.get("seed") or 0) or None,
        "name": str(payload.get("name") or "手绘世界"),
    }


def _latitude(row: int, height: int) -> float:
    if height <= 1:
        return LAT_TOP
    return LAT_TOP - (LAT_TOP - LAT_BOTTOM) * row / (height - 1)


def _derive_terrain(draft: dict[str, Any], seed: int) -> None:
    """Fill elevation, slope, climate, hazards and hydrology onto every drafted tile."""
    width, height, tiles = draft["width"], draft["height"], draft["tiles"]
    for row in range(height):
        for col in range(width):
            tile = tiles[(col, row)]
            biome = tile["biome"]
            elev_band, temp_bias, precip_band, _ = TERRAIN[biome]
            lat = _latitude(row, height)
            elevation = elev_band[0] + (elev_band[1] - elev_band[0]) * noise(seed, col, row, "elev")
            if tile["land"]:
                elevation = max(elevation, 0.0)
            tile["latitude_deg"] = round(lat, 2)
            tile["elevation_m"] = int(round(elevation))
            mean = 27.5 - 0.42 * (lat - LAT_BOTTOM) - max(elevation, 0.0) / 220.0 + temp_bias
            mean += 1.6 * noise(seed, col, row, "temp")
            tile["annual_mean_temp_c"] = round(_clamp(mean, -28.0, 32.0), 1)
            annual = precip_band[0] + (precip_band[1] - precip_band[0]) * noise(seed, col, row, "rain")
            if tile["river"]:
                annual *= 1.15
            tile["annual_precip_mm"] = int(round(annual))

    for row in range(height):
        for col in range(width):
            tile = tiles[(col, row)]
            amplitude = 3.0 + 0.42 * (tile["latitude_deg"] - LAT_BOTTOM)
            amplitude += 2.5 * noise(seed, col, row, "season")
            amplitude += max(tile["elevation_m"], 0) / 900.0
            amplitude = _clamp(amplitude, 1.5, 26.0)
            tile["monthly_temp_c"] = [
                round(tile["annual_mean_temp_c"] - amplitude * math.cos(index * math.pi / 6.0), 1)
                for index in range(12)
            ]
            swing = 0.12 + 0.45 * noise(seed, col, row, "wet")
            phase = noise(seed, col, row, "phase") * math.pi
            shape = [max(0.05, 1.0 + swing * math.cos(index * math.pi / 6.0 - phase))
                     for index in range(12)]
            scale = tile["annual_precip_mm"] / sum(shape)
            tile["monthly_precip_mm"] = [round(value * scale, 1) for value in shape]

    for row in range(height):
        for col in range(width):
            tile = tiles[(col, row)]
            adjacent = list(neighbors(col, row, width, height))
            drop = max(
                abs(tile["elevation_m"] - tiles[nb]["elevation_m"]) for nb in adjacent
            ) if adjacent else 0
            tile["slope"] = round(_clamp(drop / (R_KM * 1.5) / 0.05, 0.0, 1.0), 4)

    near_river = _water_distance(tiles, width, height)
    for (col, row), tile in tiles.items():
        biome = tile["biome"]
        _, _, _, lean = TERRAIN[biome]
        coastal = any(not tiles[nb]["land"] for nb in neighbors(col, row, width, height))
        lowland = 1.0 - _clamp(max(tile["elevation_m"], 0) / 900.0, 0.0, 1.0)
        aridity = _clamp(1.0 - tile["annual_precip_mm"] / 900.0, 0.0, 1.0)
        exposure = {
            "flood": _clamp(lean.get("flood", 0.0) * (0.45 + 0.55 * lowland)
                            + (0.25 if tile["river"] else 0.0)
                            + 0.15 * noise(seed, col, row, "flood"), 0.0, 1.0),
            "drought": _clamp(lean.get("drought", 0.0) * (0.5 + 0.5 * aridity)
                              + 0.1 * noise(seed, col, row, "drought"), 0.0, 1.0),
            "earthquake": _clamp(lean.get("earthquake", 0.0) * (0.55 + 0.45 * noise(seed, col, row, "quake"))
                                 + 0.05 * lowland, 0.0, 1.0),
            "volcano": _clamp(0.35 * noise(seed, col, row, "volcano") ** 3
                              + (0.1 if biome == "alpine" else 0.0), 0.0, 1.0),
            "wildfire": _clamp(lean.get("wildfire", 0.0) * (0.4 + 0.6 * aridity)
                               + 0.08 * noise(seed, col, row, "fire"), 0.0, 1.0),
            "cyclone": _clamp(lean.get("cyclone", 0.0) * (1.0 if coastal else 0.25)
                              * _clamp(1.0 - (tile["latitude_deg"] - 8.0) / 26.0, 0.15, 1.0)
                              + 0.05 * noise(seed, col, row, "storm"), 0.0, 1.0),
        }
        tile["hazards"] = {key: round(exposure[key], 3) for key in HAZARD_TYPES}
        tile["river_distance"] = near_river[(col, row)]
    _derive_drainage(draft)


def _water_distance(tiles: dict[tuple[int, int], dict[str, Any]], width: int, height: int) -> dict[tuple[int, int], int]:
    """Hex distance to the nearest river or coast, used for humidity flavoured hazards."""
    pending = {
        coord: 0 for coord, tile in tiles.items()
        if not tile["land"] or tile["river"]
    }
    seen = dict(pending)
    queue = deque(pending)
    while queue:
        col, row = queue.popleft()
        for nb in neighbors(col, row, width, height):
            if nb in seen:
                continue
            seen[nb] = seen[(col, row)] + 1
            queue.append(nb)
    return {coord: max(0, value - 1) for coord, value in seen.items()}


def _derive_drainage(draft: dict[str, Any]) -> None:
    """Priority flood to the sea so every land tile has a one-hop downstream neighbour."""
    width, height, tiles = draft["width"], draft["height"], draft["tiles"]
    dist: dict[tuple[int, int], float] = {}
    parent: dict[tuple[int, int], tuple[int, int] | None] = {}
    heap: list[tuple[float, int, int, tuple[int, int]]] = []
    for coord, tile in tiles.items():
        if not tile["land"]:
            dist[coord] = -1.0
            parent[coord] = None
            heap.append((0.0, coord[1], coord[0], coord))
    heapq.heapify(heap)
    settled: set[tuple[int, int]] = set()
    while heap:
        total, _, _, current = heapq.heappop(heap)
        if current in settled:
            continue
        settled.add(current)
        for nb in neighbors(current[0], current[1], width, height):
            if nb in settled or not tiles[nb]["land"]:
                continue
            candidate = total + (max(tiles[nb]["elevation_m"], 0) + 1.0) / 1000.0
            if candidate < dist.get(nb, math.inf) - 1e-12:
                dist[nb] = candidate
                parent[nb] = current
                heapq.heappush(heap, (candidate, nb[1], nb[0], nb))

    children: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for coord, source in parent.items():
        if source is not None and tiles[coord]["land"]:
            children.setdefault(source, []).append(coord)
    basin = {coord: 1 for coord, tile in tiles.items() if tile["land"]}
    for coord in sorted(basin, key=lambda key: -dist.get(key, 0.0)):
        source = parent.get(coord)
        if source is not None and tiles[source]["land"]:
            basin[source] += basin[coord]

    for coord, tile in tiles.items():
        if not tile["land"]:
            tile["downstream"] = None
            tile["drainage_area_km2"] = 0
            continue
        source = parent.get(coord)
        tile["downstream"] = list(source) if source else None
        tile["drainage_area_km2"] = int(basin.get(coord, 1) * CELL_AREA_KM2)


def _arrays(draft: dict[str, Any]) -> dict[str, Any]:
    width, height, tiles = draft["width"], draft["height"], draft["tiles"]
    shape = (height, width)
    land = np.zeros(shape, bool)
    elev = np.zeros(shape, float)
    precip = np.zeros(shape, float)
    biome = np.empty(shape, dtype=object)
    river = np.zeros(shape, bool)
    hazards = {key: np.zeros(shape, float) for key in ("flood", "drought")}
    for row in range(height):
        for col in range(width):
            tile = tiles[(col, row)]
            land[row, col] = tile["land"]
            elev[row, col] = tile["elevation_m"]
            precip[row, col] = tile["annual_precip_mm"]
            biome[row, col] = tile["biome"]
            river[row, col] = tile["river"]
            for key in hazards:
                hazards[key][row, col] = tile["hazards"][key]
    return {"land": land, "elev": elev, "precip": precip, "biome": biome,
            "river": river, "hazards": hazards}


def build_world_from_draft(payload: dict[str, Any], seed: int | None = None) -> dict[str, Any]:
    """Turn a painted draft into a schema-v2 world document, complete and playable."""
    draft = normalize_draft(payload)
    world_seed = int(seed if seed is not None else (draft["seed"] or 1234)) % 2_000_000_000
    _derive_terrain(draft, world_seed)
    arrays = _arrays(draft)
    width, height, tiles = draft["width"], draft["height"], draft["tiles"]

    available = arrays["land"].copy()
    ownership, territories = mapgen._grow_equal_territories(
        draft["capitals"], arrays["land"], available, w=width, h=height)
    for country, cells in zip(draft["countries"], territories):
        if len(cells) < mapgen.CORE_TILES:
            raise ValueError(
                f"国家 {country['name']} 的都城周围只有 {len(cells)} 格连通陆地，"
                f"至少需要 {mapgen.CORE_TILES} 格才能开局")
    for row in range(height):
        for col in range(width):
            owner = ownership[row, col]
            tiles[(col, row)]["owner_id"] = str(owner) if owner else None

    fairness = mapgen._fairness(
        draft["countries"], territories, arrays["elev"], arrays["precip"],
        arrays["biome"], arrays["river"], arrays["hazards"],
    )
    fairness["mode"] = "hand_drawn"

    polities = []
    identifiers = mapgen.country_ids(len(draft["countries"]))
    for index, (country, capital, cells) in enumerate(
            zip(draft["countries"], draft["capitals"], territories)):
        col, row = capital
        tile = tiles[capital]
        polities.append({
            "id": identifiers[index],
            "name": country["name"],
            "type": country["archetype"],
            "color": country["color"],
            "government": mapgen.ARCHETYPES[country["archetype"]],
            "description": f"玩家手绘地图上的{mapgen.ARCHETYPES[country['archetype']]}",
            "population": country["population"],
            "capital": {"col": col, "row": row, "q": col - (row - (row & 1)) // 2, "r": row},
            "initial_tiles": cells,
            "territorial_area_km2": round(len(cells) * CELL_AREA_KM2),
            "avg_annual_temp_c": tile["annual_mean_temp_c"],
            "avg_annual_precip_mm": tile["annual_precip_mm"],
            "elevation_m": tile["elevation_m"],
            "river_distance_tiles": float(tile["river_distance"]),
            "dominant_biome": tile["biome"],
            "technology": {
                "agriculture": 1,
                "bronze_metallurgy": 2 if country["archetype"] == "highland" else 1,
                "writing": 1 if country["archetype"] in {"river_valley", "semiarid"} else 0,
            },
            "treasury_units": 100,
            "food_storage_units": 160,
            "diplomatic_status": "no_contact",
        })

    world_tiles = []
    river_cells = []
    road_cells = []
    for row in range(height):
        for col in range(width):
            tile = tiles[(col, row)]
            world_tiles.append({
                "q": col - (row - (row & 1)) // 2, "r": row, "col": col, "row": row,
                "latitude_deg": tile["latitude_deg"],
                "land": tile["land"],
                "elevation_m": tile["elevation_m"],
                "biome": tile["biome"],
                "annual_mean_temp_c": tile["annual_mean_temp_c"],
                "annual_precip_mm": tile["annual_precip_mm"],
                "monthly_temp_c": tile["monthly_temp_c"],
                "monthly_precip_mm": tile["monthly_precip_mm"],
                "slope": tile["slope"],
                "river": tile["river"],
                "drainage_area_km2": tile["drainage_area_km2"],
                "downstream": (
                    {"col": tile["downstream"][0], "row": tile["downstream"][1]}
                    if tile["downstream"] else None
                ),
                "hazards": tile["hazards"],
                "owner_id": tile["owner_id"],
            })
            if tile["river"]:
                max_depth = _clamp(tile["drainage_area_km2"] / 40000.0, 0.3, 12.0)
                river_cells.append({
                    "id": f"RV{col:03d}{row:03d}",
                    "network_id": None,
                    "tile": {"col": col, "row": row},
                    "depth_m": round(max_depth, 3),
                    "coverage": 0.6,
                    "flow_m3_per_year": round(
                        tile["annual_precip_mm"] * tile["drainage_area_km2"] * 1000.0, 1),
                    "drainage_area_km2": tile["drainage_area_km2"],
                })
            if tile["road"]:
                road_cells.append({
                    "id": f"RD{col:03d}{row:03d}",
                    "network_id": None,
                    "tile": {"col": col, "row": row},
                    "kind": "road",
                    "owner_id": tile["owner_id"],
                })

    land_count = sum(1 for tile in tiles.values() if tile["land"])
    return {
        "metadata": {
            "project": "Project Eos",
            "version": "0.2.0",
            "schema_version": 2,
            "generator": "mapgen_custom",
            "seed": world_seed,
            "world_year_bce": 2000,
            "astronomical_year": -1999,
            "start_month": 1,
            "day_count": 0,
            "grid_type": "odd-r pointy-top hex",
            "grid_width": width,
            "grid_height": height,
            "hex_radius_km": R_KM,
            "cell_area_km2": round(CELL_AREA_KM2, 1),
            "assumed_planet": "Earth-like, 24h day, 365-day year, Northern Hemisphere",
            "latitude_range_deg": [LAT_BOTTOM, LAT_TOP],
            "custom_game": True,
            "draft_name": draft["name"],
            "draft_digest": _draft_digest(draft),
            "fairness": fairness,
            "core_tiles_per_country": mapgen.CORE_TILES,
        },
        "world_summary": {
            "land_hexes": land_count,
            "ocean_hexes": width * height - land_count,
            "land_area_km2": round(land_count * CELL_AREA_KM2),
            "maximum_elevation_m": max(
                (tile["elevation_m"] for tile in tiles.values()), default=0),
            "river_hexes": sum(1 for tile in tiles.values() if tile["river"]),
            "river_cell_count": len(river_cells),
            "road_cell_count": len(road_cells),
            "unclaimed_land_hexes": sum(
                1 for tile in tiles.values() if tile["land"] and not tile["owner_id"]),
        },
        "rendering": {
            "river_depth_stops": DEPTH_STOPS,
            "road_color": "#8da4a7",
            "bridge_color": "#b0c4c8",
        },
        "polities": polities,
        "tiles": world_tiles,
        "river_cells": river_cells,
        "road_cells": road_cells,
        "weather_samples": [],
        "illustrative_hazard_events": [],
    }


def _draft_digest(draft: dict[str, Any]) -> str:
    """Content fingerprint of a painted draft: saves pin the world file by SHA-256, so
    two different maps must never share a filename."""
    tiles = draft["tiles"]
    rivers = sorted(f"{col},{row}" for (col, row), tile in tiles.items() if tile["river"])
    roads = sorted(f"{col},{row}" for (col, row), tile in tiles.items() if tile["road"])
    blob = "|".join(draft["grid"]) + "|" + ",".join(rivers) + "|" + ",".join(roads)
    blob += "|" + ";".join(f"{col},{row}" for col, row in draft["capitals"])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def draft_report(payload: dict[str, Any]) -> dict[str, Any]:
    """What the painter's side panel shows after each stroke: is this map playable?"""
    draft = normalize_draft(payload)
    width, height, tiles = draft["width"], draft["height"], draft["tiles"]
    land = np.array(
        [[tiles[(col, row)]["land"] for col in range(width)] for row in range(height)],
        dtype=bool)
    _, territories = mapgen._grow_equal_territories(
        draft["capitals"], land, land.copy(), w=width, h=height)
    identifiers = mapgen.country_ids(len(draft["capitals"]))
    biome_counts: dict[str, int] = {}
    for tile in tiles.values():
        biome_counts[tile["biome"]] = biome_counts.get(tile["biome"], 0) + 1
    land_tiles = sum(1 for tile in tiles.values() if tile["land"])
    countries = []
    for index, (country, capital, cells) in enumerate(
            zip(draft["countries"], draft["capitals"], territories)):
        biome_tally: dict[str, int] = {}
        for col, row in cells:
            biome = tiles[(col, row)]["biome"]
            biome_tally[biome] = biome_tally.get(biome, 0) + 1
        dominant = max(biome_tally, key=lambda key: biome_tally[key]) if biome_tally else "ocean"
        countries.append({
            "id": identifiers[index],
            "name": country["name"],
            "color": country["color"],
            "capital": list(capital),
            "core_tiles": len(cells),
            "core_tiles_required": mapgen.CORE_TILES,
            "openable": len(cells) >= mapgen.CORE_TILES,
            "dominant_biome": dominant,
            "dominant_biome_label": BIOME_LABELS[dominant],
            "capital_biome_label": BIOME_LABELS[tiles[capital]["biome"]],
            "archetype_label": mapgen.ARCHETYPES[country["archetype"]],
        })
    warnings = [
        f"{country['name']} 的都城周围只有 {country['core_tiles']} 格连通陆地，"
        f"至少需要 {mapgen.CORE_TILES} 格"
        for country in countries if not country["openable"]
    ]
    if land_tiles < width * height * 0.2:
        warnings.append("陆地不足全图两成，多数国家难以凑满开局领土")
    return {
        "ok": all(country["openable"] for country in countries),
        "width": width,
        "height": height,
        "tiles": width * height,
        "land_tiles": land_tiles,
        "ocean_tiles": width * height - land_tiles,
        "land_share": round(land_tiles / (width * height), 3),
        "river_tiles": sum(1 for tile in tiles.values() if tile["river"]),
        "road_tiles": sum(1 for tile in tiles.values() if tile["road"]),
        "biomes": {
            BIOME_LABELS[biome]: count
            for biome, count in sorted(biome_counts.items(), key=lambda item: -item[1])
        },
        "cell_area_km2": round(CELL_AREA_KM2, 1),
        "countries": countries,
        "warnings": warnings,
        "digest": _draft_digest(draft),
    }


def write_draft_world(world: dict[str, Any]) -> Path:
    directory = BASE_DIR / "runs" / "worlds"
    directory.mkdir(parents=True, exist_ok=True)
    digest = world["metadata"].get("draft_digest", "0")
    path = directory / f"world_draft_{world['metadata']['seed']}_{digest[:10]}.json"
    path.write_text(json.dumps(world, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def movement(draft: dict[str, Any], config: dict[str, Any],
             extra_roads: Any = ()) -> Movement:
    """A Movement model over drafted tiles; `extra_roads` adds freshly built road tiles."""
    tiles = draft["tiles"]
    width, height = draft["width"], draft["height"]
    roads = {tuple(coord) for coord in extra_roads}

    def state_of(coord: tuple[int, int]) -> dict[str, Any] | None:
        tile = tiles.get(coord)
        if tile is None:
            return None
        return {
            "land": tile["land"],
            "biome": tile["biome"],
            "road": tile["road"] or coord in roads,
        }

    return Movement(
        config, state_of,
        lambda coord: list(neighbors(coord[0], coord[1], width, height)),
    )


def march_preview(payload: dict[str, Any], config: dict[str, Any],
                  start: Any, target: Any) -> dict[str, Any]:
    """Live march timing for the painter: same model, same numbers as the running game.

    Only terrain, roads and core territory matter here, so the climate and hydrology
    derivation stays out of the hover path.
    """
    draft = normalize_draft(payload)
    land = np.array(
        [[draft["tiles"][(col, row)]["land"] for col in range(draft["width"])]
         for row in range(draft["height"])], dtype=bool)
    capitals = draft["capitals"]
    _, territories = mapgen._grow_equal_territories(
        capitals, land, land.copy(), w=draft["width"], h=draft["height"])
    identifiers = mapgen.country_ids(len(capitals))
    owner_of = {}
    for country_id, cells in zip(identifiers, territories):
        for col, row in cells:
            owner_of[(col, row)] = country_id
    names = dict(zip(identifiers, [country["name"] for country in draft["countries"]]))

    start_coord = _coord(start, "行军起点", draft["width"], draft["height"])
    target_coord = _coord(target, "行军终点", draft["width"], draft["height"])
    model = movement(draft, config)
    specs = config["movement"]
    result: dict[str, Any] = {
        "ok": False,
        "from": list(start_coord),
        "to": list(target_coord),
        "hex_distance": hex_distance(start_coord, target_coord),
        "straight_km": round(
            hex_distance(start_coord, target_coord) * R_KM * math.sqrt(3.0), 1),
        "daily_budget": float(specs["daily_budget"]),
        "maximum_order_cost": float(specs["maximum_order_cost"]),
        "route": [],
        "cost": None,
        "days": None,
        "reason": None,
        "hint": None,
        "segments": None,
        "single_order": False,
    }
    for coord, label in ((start_coord, "起点"), (target_coord, "终点")):
        if not draft["tiles"][coord]["land"]:
            result["reason"] = f"{label}位于海洋，军队无法从海面行军"
            return result

    def describe(where: tuple[int, int]) -> dict[str, Any]:
        tile = draft["tiles"][where]
        owner = owner_of.get(where)
        return {
            "tile": list(where),
            "biome": tile["biome"],
            "biome_label": BIOME_LABELS[tile["biome"]],
            "owner": owner,
            "owner_name": names.get(owner),
            "road": tile["road"],
            "entry_cost": model.cost(where),
        }

    result["from_info"] = describe(start_coord)
    result["to_info"] = describe(target_coord)
    if start_coord == target_coord:
        result.update({
            "ok": True, "single_order": True,
            "cost": 0.0, "days": 0, "route": [list(start_coord)],
        })
        return result

    plan = model.plan(start_coord, target_coord)
    if plan is None:
        # Same model with the per-order cap lifted: that answers both questions the player
        # has — is there any land corridor at all, and how many orders would it take.
        uncapped = movement(
            draft,
            {**config, "movement": {**specs, "maximum_order_cost": 10.0 ** 9}},
        )
        plan = uncapped.plan(start_coord, target_coord)
        if plan is None:
            result["reason"] = "起点与终点之间没有连通陆路（被海洋隔断），无法行军"
            return result
        result["segments"] = max(
            1, math.ceil(plan["cost"] / float(specs["maximum_order_cost"]) - 1e-9))
        result["hint"] = (
            f"最近陆路成本 {plan['cost']}（约 {plan['days']} 天），超过单条行军命令上限 "
            f"{specs['maximum_order_cost']}，需要分 {result['segments']} 段下令")
    road_steps = sum(1 for coord in plan["route"][1:] if draft["tiles"][coord]["road"])
    counts: dict[str, int] = {}
    crossings: dict[str, int] = {}
    for coord in plan["route"][1:]:
        tile = draft["tiles"][coord]
        key = "road" if tile["road"] else tile["biome"]
        counts[key] = counts.get(key, 0) + 1
        owner = owner_of.get(coord)
        if owner:
            crossings[owner] = crossings.get(owner, 0) + 1
    steps = max(1, len(plan["route"]) - 1)
    result.update({
        "ok": True,
        "single_order": result["hint"] is None,
        "route": [list(coord) for coord in plan["route"]],
        "cost": plan["cost"],
        "days": plan["days"],
        "steps": steps,
        "road_share": round(road_steps / steps, 3),
        "terrain_mix": {
            (BIOME_LABELS[biome] if biome in BIOME_LABELS else "道路"): count
            for biome, count in sorted(counts.items(), key=lambda item: -item[1])
        },
        "crossings": [
            {"country_id": owner, "name": names.get(owner, owner), "tiles": count}
            for owner, count in sorted(crossings.items(), key=lambda item: -item[1])
        ],
    })
    return result
