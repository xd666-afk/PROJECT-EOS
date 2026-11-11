"""V2 map generation: continuous terrain first, then fine hex-cell entities.

The v1 generator remains available for the fixed baseline and old saves. V2 keeps
all fields needed by GameState, but adds river depth and occupied road cells.
"""
from __future__ import annotations

import heapq
import json
import math
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

import mapgen
import worldgen
from worldgen import CELL_AREA_KM2 as V1_CELL_AREA_KM2

BASE_DIR = Path(__file__).resolve().parent
V2_WIDTH = 144
V2_HEIGHT = 108
V2_RADIUS_KM = 17.0
V2_CELL_AREA_KM2 = (3 * math.sqrt(3) / 2) * V2_RADIUS_KM ** 2
CONTINUOUS_SCALE = 4
CONTINUOUS_WIDTH = V2_WIDTH * CONTINUOUS_SCALE
CONTINUOUS_HEIGHT = V2_HEIGHT * CONTINUOUS_SCALE
CONTINUOUS_RADIUS_KM = V2_RADIUS_KM / CONTINUOUS_SCALE
CONTINUOUS_CELL_AREA_KM2 = (3 * math.sqrt(3) / 2) * CONTINUOUS_RADIUS_KM ** 2
CONTINUOUS_RIVER_MIN_BASIN = max(1, round(17 * V1_CELL_AREA_KM2 / CONTINUOUS_CELL_AREA_KM2))
DEPTH_STOPS = [
    [0.3, "#b9e6ed"],
    [1.2, "#83cfdd"],
    [2.5, "#54a8c0"],
    [4.5, "#337f9d"],
    [7.0, "#205c79"],
    [10.0, "#153e57"],
]


def _blocks(field: np.ndarray):
    for y in range(V2_HEIGHT):
        for x in range(V2_WIDTH):
            y0 = y * CONTINUOUS_SCALE
            y1 = (y + 1) * CONTINUOUS_SCALE
            x0 = x * CONTINUOUS_SCALE
            x1 = (x + 1) * CONTINUOUS_SCALE
            if field.ndim == 3:
                yield x, y, field[:, y0:y1, x0:x1]
            else:
                yield x, y, field[y0:y1, x0:x1]


def _mean(value: np.ndarray) -> float:
    return float(np.mean(value)) if value.size else 0.0


def _dominant(values: np.ndarray, fallback: str) -> str:
    values = [str(item) for item in values.ravel() if str(item) != "ocean"]
    if not values:
        return fallback
    return Counter(values).most_common(1)[0][0]


def _road_path(
    start: tuple[int, int],
    end: tuple[int, int],
    land: np.ndarray,
    elev: np.ndarray,
    river: np.ndarray,
) -> list[tuple[int, int]] | None:
    height, width = land.shape
    heap = [(0.0, start)]
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    costs = {start: 0.0}
    while heap:
        cost, current = heapq.heappop(heap)
        if current == end:
            break
        if cost > costs.get(current, float("inf")):
            continue
        x, y = current
        for nx, ny in worldgen.neighbors(x, y, width, height):
            if not land[ny, nx]:
                continue
            step = 1.0 + abs(float(elev[ny, nx] - elev[y, x])) / 260.0
            if river[ny, nx]:
                step += 3.5
            new_cost = cost + step
            if new_cost < costs.get((nx, ny), float("inf")):
                costs[(nx, ny)] = new_cost
                previous[(nx, ny)] = current
                heapq.heappush(heap, (new_cost, (nx, ny)))
    if end not in previous:
        return None
    path = []
    current: tuple[int, int] | None = end
    while current is not None:
        path.append(current)
        current = previous[current]
    return list(reversed(path))


def _build_roads(
    polities: list[dict[str, Any]],
    land: np.ndarray,
    elev: np.ndarray,
    river: np.ndarray,
) -> list[dict[str, Any]]:
    """Connect capitals through a real, cost-aware road network on the raster."""
    capitals = [
        (int(polity["capital"]["col"]), int(polity["capital"]["row"]), polity["id"])
        for polity in polities
    ]
    if len(capitals) < 2:
        return []
    edges = []
    for index, left in enumerate(capitals):
        for right in capitals[index + 1:]:
            distance = worldgen.hex_distance(left[:2], right[:2])
            edges.append((distance, left, right))
    edges.sort(key=lambda item: item[0])
    parent = {cid: cid for _, _, cid in capitals}

    def find(cid: str) -> str:
        while parent[cid] != cid:
            parent[cid] = parent[parent[cid]]
            cid = parent[cid]
        return cid

    raw_paths: list[dict[str, Any]] = []
    for _, left, right in edges:
        left_id, right_id = left[2], right[2]
        if find(left_id) == find(right_id):
            continue
        parent[find(left_id)] = find(right_id)
        start = (left[0] * CONTINUOUS_SCALE + 1, left[1] * CONTINUOUS_SCALE + 1)
        end = (right[0] * CONTINUOUS_SCALE + 1, right[1] * CONTINUOUS_SCALE + 1)
        path = _road_path(start, end, land, elev, river)
        if not path:
            continue
        network_id = f"RN_{left_id}_{right_id}"
        for x, y in path:
            left_distance = worldgen.hex_distance((x // CONTINUOUS_SCALE, y // CONTINUOUS_SCALE), left[:2])
            right_distance = worldgen.hex_distance((x // CONTINUOUS_SCALE, y // CONTINUOUS_SCALE), right[:2])
            raw_paths.append({
                "x": x, "y": y, "owner_id": left_id if left_distance <= right_distance else right_id,
                "network_id": network_id,
            })
    return raw_paths


def _aggregate_roads(raw_paths: list[dict[str, Any]], river_mask: np.ndarray) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for point in raw_paths:
        key = (point["x"] // CONTINUOUS_SCALE, point["y"] // CONTINUOUS_SCALE)
        grouped.setdefault(key, []).append(point)
    cells = []
    for (col, row), points in grouped.items():
        cells.append({
            "id": f"RD{col:03d}{row:03d}",
            "network_id": Counter(point["network_id"] for point in points).most_common(1)[0][0],
            "tile": {"col": col, "row": row},
            "kind": "bridge" if any(river_mask[point["y"], point["x"]] for point in points) else "road",
            "owner_id": Counter(point["owner_id"] for point in points).most_common(1)[0][0],
        })
    return sorted(cells, key=lambda cell: (cell["tile"]["row"], cell["tile"]["col"]))


def _split_road_networks(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_network: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        by_network.setdefault(cell["network_id"], []).append(cell)
    result = []
    for network_id, members in by_network.items():
        coords = {(cell["tile"]["col"], cell["tile"]["row"]): cell for cell in members}
        remaining = set(coords)
        part = 0
        while remaining:
            start = next(iter(remaining))
            queue = deque([start])
            component = {start}
            remaining.remove(start)
            while queue:
                current = queue.popleft()
                for neighbor in worldgen.neighbors(*current, V2_WIDTH, V2_HEIGHT):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        queue.append(neighbor)
            part += 1
            for coord in component:
                cell = dict(coords[coord])
                cell["network_id"] = network_id if part == 1 else f"{network_id}_{part}"
                result.append(cell)
    return result


def _terrain_texture(
    elev: np.ndarray,
    land: np.ndarray,
    biome: np.ndarray,
    precip: np.ndarray,
    temp: np.ndarray,
    seed: int,
) -> Path:
    """Render the continuous terrain once, before hex quantization."""
    palette = {
        "desert": (192, 162, 108),
        "alpine": (112, 120, 116),
        "tundra": (135, 148, 127),
        "forest": (50, 105, 70),
        "rainforest": (36, 92, 64),
        "wetland": (76, 130, 115),
        "steppe": (150, 140, 92),
        "savanna": (140, 152, 82),
        "grassland": (104, 145, 86),
    }
    height, width = elev.shape
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    gy, gx = np.gradient(elev)
    shade = np.clip(1.0 - gx * 0.0018 - gy * 0.0008, .72, 1.22)
    for y in range(height):
        for x in range(width):
            if not land[y, x]:
                depth = np.clip(-float(elev[y, x]) / 1400.0, 0, 1)
                base = np.array([35, 89, 112], dtype=np.float32) * (1 - depth) + np.array([7, 30, 45], dtype=np.float32) * depth
                rgb[y, x] = base
                continue
            base = np.array(palette.get(str(biome[y, x]), palette["grassland"]), dtype=np.float32)
            dry = 1 - min(1.0, float(precip[y, x]) / 1200.0)
            base = base * (1 - dry * .25) + np.array([125, 100, 70], dtype=np.float32) * (dry * .25)
            base = base * (1 - min(1.0, max(0.0, float(elev[y, x])) / 3000.0) * .22) + np.array([180, 184, 172], dtype=np.float32) * (min(1.0, max(0.0, float(elev[y, x])) / 3000.0) * .22)
            rgb[y, x] = base * shade[y, x]
    path = BASE_DIR / "runs" / "worlds" / f"world_v2_custom_{seed}_terrain.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    image = image.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
    image.save(path, optimize=True)
    return path


def _generate_candidate(seed: int, countries: list[dict[str, Any]]) -> dict[str, Any]:
    rng, X, Y, lat, land, elev, fault, ridge = worldgen.gen_base(
        seed, CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT
    )
    p, tmean, monthly_temp, monthly_rain, biome, dist_ocean = worldgen.gen_climate(
        rng, lat, land, elev, CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT, CONTINUOUS_RADIUS_KM
    )
    parent, flow, basin, river, slope = worldgen.gen_hydrology(
        land, elev, p,
        CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT,
        CONTINUOUS_RADIUS_KM, CONTINUOUS_CELL_AREA_KM2,
        CONTINUOUS_RIVER_MIN_BASIN,
    )
    hazards = worldgen.gen_hazards(
        land, elev, fault, biome, p, tmean, lat, river, basin, slope, dist_ocean,
        CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT, CONTINUOUS_RADIUS_KM,
    )

    aggregated: dict[tuple[int, int], dict[str, Any]] = {}
    for x, y, block in _blocks(land):
        land_cell = bool(block.sum() >= (CONTINUOUS_SCALE ** 2) / 2)
        aggregated[(x, y)] = {"land": land_cell}
    for x, y, block in _blocks(elev):
        aggregated[(x, y)]["elevation_m"] = _mean(block)
    for x, y, block in _blocks(p):
        aggregated[(x, y)]["annual_precip_mm"] = _mean(block)
    for x, y, block in _blocks(tmean):
        aggregated[(x, y)]["annual_mean_temp_c"] = _mean(block)
    for x, y, block in _blocks(monthly_temp):
        aggregated[(x, y)]["monthly_temp_c"] = [
            float(value) for value in block.mean(axis=(1, 2))
        ]
    for x, y, block in _blocks(monthly_rain):
        aggregated[(x, y)]["monthly_precip_mm"] = [
            float(value) for value in block.mean(axis=(1, 2))
        ]
    for x, y, block in _blocks(biome):
        aggregated[(x, y)]["biome"] = _dominant(block, "ocean" if not aggregated[(x, y)]["land"] else "grassland")
    for key in hazards:
        for x, y, block in _blocks(hazards[key]):
            aggregated[(x, y)][key] = _mean(block)
    for x, y, block in _blocks(river):
        aggregated[(x, y)]["river_count"] = int(block.sum())
    for x, y, block in _blocks(flow):
        aggregated[(x, y)]["flow"] = float(block.max()) if block.size else 0.0
    for x, y, block in _blocks(basin):
        aggregated[(x, y)]["basin"] = int(block.max()) if block.size else 0

    v2_elev = np.array([
        [aggregated[(x, y)]["elevation_m"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    v2_land = np.array([
        [aggregated[(x, y)]["land"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    _, _, v2_basin, _, v2_slope = worldgen.gen_hydrology(
        v2_land, v2_elev,
        np.array([[aggregated[(x, y)]["annual_precip_mm"] for x in range(V2_WIDTH)] for y in range(V2_HEIGHT)]),
        V2_WIDTH, V2_HEIGHT, V2_RADIUS_KM, V2_CELL_AREA_KM2,
    )

    polity_land = v2_land
    polity_biome = np.array([
        [aggregated[(x, y)]["biome"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ], dtype=object)
    polity_p = np.array([
        [aggregated[(x, y)]["annual_precip_mm"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    polity_tmean = np.array([
        [aggregated[(x, y)]["annual_mean_temp_c"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    polity_river = np.array([
        [aggregated[(x, y)]["river_count"] > 0 for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    polity_basin = v2_basin
    polity_hazards = {
        key: np.array([
            [aggregated[(x, y)][key] for x in range(V2_WIDTH)]
            for y in range(V2_HEIGHT)
        ])
        for key in hazards
    }
    polity_lat = np.array([
        [float(lat[y * CONTINUOUS_SCALE, x * CONTINUOUS_SCALE]) for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    polity_dist_ocean = worldgen.distance_transform_edt(polity_land) * V2_RADIUS_KM * 1.7
    capitals = mapgen._place_capitals(
        countries, polity_land, v2_elev, polity_biome, polity_p, polity_tmean,
        polity_river, polity_basin, v2_slope, polity_dist_ocean,
        polity_hazards, polity_lat, V2_WIDTH, V2_HEIGHT, True, polity_river,
    )
    available = polity_land.copy()
    ownership, territories = mapgen._grow_equal_territories(
        capitals, polity_land, available, V2_WIDTH, V2_HEIGHT
    )
    if any(len(cells) < mapgen.CORE_TILES for cells in territories):
        raise RuntimeError("v2 map cannot provide equal connected cores")
    fairness = mapgen._fairness(
        countries, territories, v2_elev, polity_p, polity_biome,
        polity_river, polity_hazards,
    )

    polities = []
    ids = mapgen.country_ids(len(countries))
    for index, (country, capital, cells) in enumerate(zip(countries, capitals, territories)):
        x0, y0 = capital
        polities.append({
            "id": ids[index], "name": country["name"], "type": country["archetype"],
            "color": country["color"], "government": mapgen.ARCHETYPES[country["archetype"]],
            "description": f"{mapgen.ARCHETYPES[country['archetype']]}风格的自定义国家",
            "population": country["population"],
            "capital": {"col": x0, "row": y0, "q": x0 - (y0 - (y0 & 1)) // 2, "r": y0},
            "initial_tiles": cells,
            "territorial_area_km2": round(len(cells) * V2_CELL_AREA_KM2, 1),
            "avg_annual_temp_c": round(float(polity_tmean[y0, x0]), 1),
            "avg_annual_precip_mm": round(float(polity_p[y0, x0])),
            "elevation_m": round(float(v2_elev[y0, x0])),
            "river_distance_tiles": round(float(worldgen.distance_transform_edt(~polity_river)[y0, x0]), 1),
            "dominant_biome": str(polity_biome[y0, x0]),
            "technology": {
                "agriculture": 1,
                "bronze_metallurgy": 2 if country["archetype"] == "highland" else 1,
                "writing": 1 if country["archetype"] in {"river_valley", "semiarid"} else 0,
            },
            "treasury_units": 100, "food_storage_units": 160, "diplomatic_status": "no_contact",
        })

    raw_roads = _build_roads(polities, land, elev, river)
    road_cells = _split_road_networks([
        cell for cell in _aggregate_roads(raw_roads, river)
        if polity_land[cell["tile"]["row"], cell["tile"]["col"]]
    ])
    tiles = []
    river_cells = []
    max_river_basin = max(
        (data["basin"] for data in aggregated.values()
         if data["land"] and data["river_count"]),
        default=1,
    )
    for y in range(V2_HEIGHT):
        for x in range(V2_WIDTH):
            data = aggregated[(x, y)]
            px, py = -1, -1
            # Recompute the downstream parent on the v2 grid to preserve the old contract.
            tiles.append({
                "q": x - (y - (y & 1)) // 2, "r": y, "col": x, "row": y,
                "latitude_deg": round(float(polity_lat[y, x]), 2),
                "land": bool(data["land"]),
                "elevation_m": int(round(data["elevation_m"])),
                "biome": str(data["biome"]),
                "annual_mean_temp_c": round(data["annual_mean_temp_c"], 1),
                "annual_precip_mm": int(round(data["annual_precip_mm"])),
                "monthly_temp_c": [round(value, 1) for value in data["monthly_temp_c"]],
                "monthly_precip_mm": [round(value, 1) for value in data["monthly_precip_mm"]],
                "slope": round(float(v2_slope[y, x]), 4),
                "river": bool(data["land"] and data["river_count"] > 0),
                "drainage_area_km2": int(v2_basin[y, x] * V2_CELL_AREA_KM2),
                "downstream": None,  # filled below from v2 parent
                "hazards": {key: round(float(data[key]), 3) for key in hazards},
                "owner_id": str(ownership[y, x]) or None,
            })
            if data["land"] and data["river_count"]:
                ratio = min(1.0, data["basin"] / max(1, max_river_basin))
                depth = max(0.3, min(12.0, 0.3 + 9.6 * ratio ** 0.55))
                river_cells.append({
                    "id": f"RV{x:03d}{y:03d}",
                    "network_id": f"RV{x // 8:02d}{y // 8:02d}",
                    "tile": {"col": x, "row": y},
                    "depth_m": round(depth, 3),
                    "coverage": round(data["river_count"] / (CONTINUOUS_SCALE ** 2), 3),
                    "flow_m3_per_year": round(data["flow"], 1),
                    "drainage_area_km2": int(data["basin"] * CONTINUOUS_CELL_AREA_KM2),
                })
    # A second hydrology pass supplies valid v2 parent pointers without drawing lines.
    v2_parent, _, _, _, _ = worldgen.gen_hydrology(
        v2_land, v2_elev, polity_p,
        V2_WIDTH, V2_HEIGHT, V2_RADIUS_KM, V2_CELL_AREA_KM2,
    )
    for tile in tiles:
        x, y = tile["col"], tile["row"]
        px, py = v2_parent[y, x]
        tile["downstream"] = {"col": int(px), "row": int(py)} if tile["land"] and px >= 0 else None

    weather_samples, events = worldgen.demo_weather_hazards(
        seed, polity_land,
        np.array([[aggregated[(x, y)]["monthly_precip_mm"] for x in range(V2_WIDTH)] for y in range(V2_HEIGHT)]).transpose(2, 0, 1),
        np.array([[aggregated[(x, y)]["monthly_temp_c"] for x in range(V2_WIDTH)] for y in range(V2_HEIGHT)]).transpose(2, 0, 1),
        polity_hazards, polities, V2_WIDTH, V2_HEIGHT,
    )
    texture_path = _terrain_texture(elev, land, biome, p, tmean, seed)
    try:
        texture_reference = str(texture_path.relative_to(BASE_DIR)).replace("\\", "/")
    except ValueError:
        texture_reference = str(texture_path)
    world = {
        "metadata": {
            "project": "Project Eos",
            "version": "0.2.0",
            "schema_version": 2,
            "generator": "mapgen_v2",
            "seed": seed,
            "world_year_bce": 2000,
            "astronomical_year": -1999,
            "start_month": 1,
            "day_count": 0,
            "grid_type": "odd-r pointy-top hex",
            "grid_width": V2_WIDTH,
            "grid_height": V2_HEIGHT,
            "hex_radius_km": V2_RADIUS_KM,
            "cell_area_km2": round(V2_CELL_AREA_KM2, 1),
            "assumed_planet": "Earth-like, 24h day, 365-day year, Northern Hemisphere",
            "latitude_range_deg": [8, 51],
            "custom_game": True,
            "terrain_texture": texture_reference,
            "fairness": fairness,
            "core_tiles_per_country": mapgen.CORE_TILES,
            "continuous_grid": {
                "width": CONTINUOUS_WIDTH,
                "height": CONTINUOUS_HEIGHT,
                "resolution_km": CONTINUOUS_RADIUS_KM,
                "sampling": "4x4 block aggregation at hex centers",
            },
            "river_depth_model": "log_flow_proxy_v1; depth is an estimate, not a hydraulic measurement",
        },
        "world_summary": {
            "land_hexes": int(polity_land.sum()),
            "ocean_hexes": int((~polity_land).sum()),
            "land_area_km2": round(float(polity_land.sum() * V2_CELL_AREA_KM2)),
            "maximum_elevation_m": round(float(v2_elev.max())),
            "river_hexes": int(polity_river.sum()),
            "river_cell_count": len(river_cells),
            "road_cell_count": len(road_cells),
            "unclaimed_land_hexes": int(np.count_nonzero(polity_land & (ownership == ""))),
        },
        "terrain": {
            "kind": "continuous_raster",
            "width": CONTINUOUS_WIDTH,
            "height": CONTINUOUS_HEIGHT,
            "resolution_km": CONTINUOUS_RADIUS_KM,
            "elevation_m": np.rint(elev).astype(int).tolist(),
            "land": land.tolist(),
        },
        "rendering": {
            "river_depth_stops": DEPTH_STOPS,
            "road_color": "#c6a065",
            "bridge_color": "#88949b",
        },
        "polities": polities,
        "tiles": tiles,
        "river_cells": river_cells,
        "road_cells": road_cells,
        "weather_samples": weather_samples,
        "illustrative_hazard_events": events,
    }
    validate_v2(world)
    return world


def validate_v2(world: dict[str, Any]) -> bool:
    metadata = world["metadata"]
    width, height = metadata["grid_width"], metadata["grid_height"]
    assert metadata["schema_version"] == 2
    assert len(world["tiles"]) == width * height
    assert world["world_summary"]["land_hexes"] == sum(tile["land"] for tile in world["tiles"])
    all_occupied = set()
    for polity in world["polities"]:
        assert len(polity["initial_tiles"]) == mapgen.CORE_TILES
        capital = (polity["capital"]["col"], polity["capital"]["row"])
        assert capital in {tuple(coord) for coord in polity["initial_tiles"]}
        capital_tile = next(
            tile for tile in world["tiles"]
            if (tile["col"], tile["row"]) == capital
        )
        assert capital_tile["land"] and not capital_tile["river"], "capital must be dry land"
        for coord in polity["initial_tiles"]:
            assert tuple(coord) not in all_occupied
            all_occupied.add(tuple(coord))

    tiles = {(tile["col"], tile["row"]): tile for tile in world["tiles"]}
    for tile in world["tiles"]:
        if not tile["land"]:
            continue
        current = tile
        seen = set()
        for _ in range(width * height):
            key = (current["col"], current["row"])
            assert key not in seen, "v2 drainage loop"
            seen.add(key)
            destination = current["downstream"]
            assert destination is not None, "v2 land has no downstream"
            next_tile = tiles[(destination["col"], destination["row"])]
            assert worldgen.hex_distance(key, (next_tile["col"], next_tile["row"])) == 1
            if not next_tile["land"]:
                break
            current = next_tile
        else:
            raise AssertionError("v2 drainage does not reach ocean")

    river_ids = set()
    for cell in world["river_cells"]:
        assert cell["id"] not in river_ids
        river_ids.add(cell["id"])
        coord = (cell["tile"]["col"], cell["tile"]["row"])
        assert tiles[coord]["land"]
        assert tiles[coord]["river"]
        assert cell["depth_m"] > 0
    for tile in world["tiles"]:
        assert tile["river"] == any(
            cell["tile"]["col"] == tile["col"] and cell["tile"]["row"] == tile["row"]
            for cell in world["river_cells"]
        )
    depths = [stop[0] for stop in world["rendering"]["river_depth_stops"]]
    assert depths == sorted(depths)

    road_ids = set()
    by_network: dict[str, list[tuple[int, int]]] = {}
    for cell in world["road_cells"]:
        assert cell["id"] not in road_ids
        road_ids.add(cell["id"])
        coord = (cell["tile"]["col"], cell["tile"]["row"])
        assert tiles[coord]["land"]
        assert cell["kind"] in {"road", "bridge"}
        by_network.setdefault(cell["network_id"], []).append(coord)
    for coords in by_network.values():
        if not coords:
            continue
        seen = {coords[0]}
        queue = deque(seen)
        while queue:
            current = queue.popleft()
            for neighbor in worldgen.neighbors(*current, width, height):
                if neighbor in coords and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        assert seen == set(coords), "road network is not hex-connected"
    return True


def generate_fair_world_v2(
    countries: list[dict[str, Any]] | None = None,
    base_seed: int | None = None,
    attempts: int = 8,
) -> tuple[dict[str, Any], Path]:
    normalized = mapgen.normalize_countries(countries)
    import secrets

    base = secrets.randbelow(2_000_000_000) if base_seed is None else int(base_seed)
    best = None
    for offset in range(max(1, attempts)):
        seed = base + offset
        try:
            world = _generate_candidate(seed, normalized)
        except RuntimeError:
            continue
        score = world["metadata"]["fairness"]["score"]
        if best is None or score > best[0]:
            best = (score, world)
        if score >= 0.72:
            break
    if best is None:
        raise RuntimeError("could not generate a playable fair v2 map")
    world = best[1]
    world["metadata"]["generation"] = {
        "base_seed": base,
        "selected_seed": world["metadata"]["seed"],
        "attempts": min(attempts, world["metadata"]["seed"] - base + 1),
        "fairness_floor": 0.72,
    }
    directory = BASE_DIR / "runs" / "worlds"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"world_v2_custom_{world['metadata']['seed']}.json"
    path.write_text(json.dumps(world, ensure_ascii=False, indent=1), encoding="utf-8")
    return world, path
