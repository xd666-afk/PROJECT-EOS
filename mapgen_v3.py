"""V3 map generation: lay the hex grid first, then fill every hex.

The earlier v2 pipeline generated a continuous raster and quantized it to hexes,
which left sub-hex coastlines and terrain edges looking jagged. V3 samples the
same geological/climate model directly at hex centers, classifies one biome per
hex, and renders flat, clean hex terrain. Water bodies and rivers remain hex
entities; rivers stay one cell wide.
"""
from __future__ import annotations

import heapq
import json
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import distance_transform_edt

import mapgen
import worldgen
from mapgen_v2 import (
    DEPTH_STOPS,
    V2_CELL_AREA_KM2,
    V2_HEIGHT,
    V2_RADIUS_KM,
    V2_RIVER_MIN_BASIN,
    V2_WIDTH,
    WATER_COLOR,
    _endorheic_catchments,
    _enclosed_water_bodies,
    _find_inland_lakes,
    _label_river_networks,
    _lake_cells,
    _recompute_accumulation,
    _shape_rivers,
    _split_road_networks,
    _terminal_lakes,
    validate_v2,
)

BASE_DIR = Path(__file__).resolve().parent


def _clean_land(land: np.ndarray, width: int, height: int) -> np.ndarray:
    """Remove one-cell islands and one-cell holes before climate sampling."""
    cleaned = land.copy()
    for y in range(height):
        for x in range(width):
            neighbors = [
                land[ny, nx]
                for nx, ny in worldgen.neighbors(x, y, width, height)
            ]
            land_neighbors = sum(neighbors)
            if land[y, x] and land_neighbors <= 1:
                cleaned[y, x] = False
            elif not land[y, x] and land_neighbors >= 5:
                cleaned[y, x] = True
    cleaned[0, :] = False
    cleaned[-1, :] = False
    cleaned[:, 0] = False
    cleaned[:, -1] = False
    return cleaned


def _smooth_biomes(
    biome: np.ndarray,
    land: np.ndarray,
    width: int,
    height: int,
    iterations: int = 1,
) -> np.ndarray:
    """Reduce single-hex biome specks while keeping hex-scale transitions."""
    result = biome.copy()
    for _ in range(iterations):
        following = result.copy()
        for y in range(height):
            for x in range(width):
                if not land[y, x]:
                    continue
                counts = Counter(
                    str(result[ny, nx])
                    for nx, ny in worldgen.neighbors(x, y, width, height)
                    if land[ny, nx]
                )
                if not counts:
                    continue
                counts[str(result[y, x])] += 2
                best, count = counts.most_common(1)[0]
                if best != str(result[y, x]) and count >= 4:
                    following[y, x] = best
        result = following
    return result


def _build_road_cells(
    polities: list[dict[str, Any]],
    land: np.ndarray,
    elev: np.ndarray,
    river: np.ndarray,
    width: int,
    height: int,
    biome: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Build a capital-spanning road network directly on the hex grid."""
    capitals = [
        (int(polity["capital"]["col"]), int(polity["capital"]["row"]), polity["id"])
        for polity in polities
    ]
    if len(capitals) < 2:
        return []
    edges = []
    for index, left in enumerate(capitals):
        for right in capitals[index + 1:]:
            edges.append((worldgen.hex_distance(left[:2], right[:2]), left, right))
    edges.sort(key=lambda item: item[0])
    parent = {country_id: country_id for _, _, country_id in capitals}

    def find(country_id: str) -> str:
        while parent[country_id] != country_id:
            parent[country_id] = parent[parent[country_id]]
            country_id = parent[country_id]
        return country_id

    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for _, left, right in edges:
        if find(left[2]) == find(right[2]):
            continue
        path = _ancient_road_path(left[:2], right[:2], land, elev, river, biome)
        if not path:
            continue
        parent[find(left[2])] = find(right[2])
        network_id = f"RN_{left[2]}_{right[2]}"
        for x, y in path:
            left_distance = worldgen.hex_distance((x, y), left[:2])
            right_distance = worldgen.hex_distance((x, y), right[:2])
            cells[(x, y)] = {
                "id": f"RD{x:03d}{y:03d}",
                "network_id": network_id,
                "tile": {"col": x, "row": y},
                "kind": "bridge" if river[y, x] else "road",
                "owner_id": left[2] if left_distance <= right_distance else right[2],
            }
    road_cells = sorted(cells.values(), key=lambda cell: (cell["tile"]["row"], cell["tile"]["col"]))
    return _split_road_networks(road_cells)


def _ancient_road_path(start, end, land, elev, river, biome):
    """Initial roads obey ancient terrain and two-cell bridge limits too."""
    from heapq import heappop, heappush
    from types import SimpleNamespace
    from core.road import river_width

    height, width = land.shape
    world = SimpleNamespace(tiles={(x, y): {"land": bool(land[y, x]), "river": bool(river[y, x])}
                                   for y in range(height) for x in range(width)})
    allowed = land.copy()
    if biome is not None:
        allowed &= ~np.isin(biome, ["alpine", "tundra", "desert"])
    for y, x in zip(*np.where(river & land)):
        span = river_width(world, (int(x), int(y)))
        if span is None or span > 2:
            allowed[y, x] = False
    if not allowed[start[1], start[0]] or not allowed[end[1], end[0]]:
        return None
    first = (start, 0)
    costs, previous, heap = {first: 0.0}, {first: None}, [(0.0, first)]
    finish = None
    while heap:
        cost, key = heappop(heap)
        if cost != costs[key]:
            continue
        coord, run = key
        if coord == end:
            finish = key
            break
        x, y = coord
        for nx, ny in worldgen.neighbors(x, y, width, height):
            if not allowed[ny, nx]:
                continue
            next_run = run + 1 if river[ny, nx] else 0
            if next_run > 2:
                continue
            candidate = cost + 1.0 + abs(float(elev[ny, nx] - elev[y, x])) / 260.0 + (3.5 if river[ny, nx] else 0.0)
            next_key = ((nx, ny), next_run)
            if candidate < costs.get(next_key, float("inf")):
                costs[next_key], previous[next_key] = candidate, key
                heappush(heap, (candidate, next_key))
    if finish is None:
        return None
    path = []
    while finish is not None:
        path.append(finish[0])
        finish = previous[finish]
    return list(reversed(path))


def _generate_candidate(seed: int, countries: list[dict[str, Any]]) -> dict[str, Any]:
    rng, _, _, lat, base_land, base_elev, fault, _ = worldgen.gen_base(
        seed, V2_WIDTH, V2_HEIGHT
    )
    land = _clean_land(base_land, V2_WIDTH, V2_HEIGHT)
    elev = np.where(land & ~base_land, 10.0, base_elev)
    p, tmean, monthly_temp, monthly_rain, biome, dist_ocean = worldgen.gen_climate(
        rng, lat, land, elev, V2_WIDTH, V2_HEIGHT, V2_RADIUS_KM
    )
    biome = _smooth_biomes(biome, land, V2_WIDTH, V2_HEIGHT)
    parent, _, seed_basin, river_seed, slope = worldgen.gen_hydrology(
        land, elev, p,
        V2_WIDTH, V2_HEIGHT, V2_RADIUS_KM, V2_CELL_AREA_KM2,
        V2_RIVER_MIN_BASIN,
    )
    hazards = worldgen.gen_hazards(
        land, elev, fault, biome, p, tmean, lat, river_seed, seed_basin, slope, dist_ocean,
        V2_WIDTH, V2_HEIGHT, V2_RADIUS_KM,
    )

    polity_p = np.asarray(p, dtype=float)
    polity_elev = np.asarray(elev, dtype=float)
    polity_land = land.copy()
    lake_mask, lakes = _find_inland_lakes(land, elev, p, V2_WIDTH, V2_HEIGHT)
    for body in _enclosed_water_bodies(land, V2_WIDTH, V2_HEIGHT):
        unassigned = [(x, y) for x, y in body if not lake_mask[y, x]]
        if len(unassigned) < 3:
            continue
        body = unassigned
        levels = [float(elev[y, x]) for x, y in body]
        level = max(levels) + .3
        lakes.append({
            "id": f"LK{len(lakes) + 1:02d}",
            "center": [
                round(sum(x for x, _ in body) / len(body)),
                round(sum(y for _, y in body) / len(body)),
            ],
            "lowest": [
                min(body, key=lambda item: elev[item[1], item[0]])[0],
                min(body, key=lambda item: elev[item[1], item[0]])[1],
            ],
            "level_m": round(level, 1),
            "depth_m": round(max(1.2, min(12.0, level - min(levels) + .8)), 2),
            "spill_height_m": 110.0,
            "origin": "enclosed",
            "cells": [[x, y] for x, y in sorted(body, key=lambda item: (item[1], item[0]))],
        })
        for x, y in body:
            lake_mask[y, x] = True
    polity_land = land & ~lake_mask
    hydro_parent, by_lake, _ = _endorheic_catchments(
        land, elev, lake_mask, lakes, parent, V2_WIDTH, V2_HEIGHT
    )
    basin, flow = _recompute_accumulation(
        land, lake_mask, hydro_parent, polity_p, V2_WIDTH, V2_HEIGHT
    )
    terminus = _terminal_lakes(
        land, lake_mask, hydro_parent, lakes, V2_WIDTH, V2_HEIGHT
    )
    river_count = np.where(land, 16.0, 0.0)
    polity_river, river_meta, max_river_basin = _shape_rivers(
        land, lake_mask, elev, hydro_parent, basin, flow,
        by_lake, terminus, river_count, V2_WIDTH, V2_HEIGHT, seed,
    )

    polity_biome = biome.copy()
    polity_tmean = np.asarray(tmean, dtype=float)
    polity_dist_ocean = distance_transform_edt(polity_land) * V2_RADIUS_KM * 1.7
    politics = mapgen._place_capitals(
        countries, polity_land, polity_elev, polity_biome, polity_p, polity_tmean,
        polity_river, basin, slope, polity_dist_ocean,
        hazards, lat, V2_WIDTH, V2_HEIGHT, True, polity_river,
    )
    available = polity_land.copy()
    ownership, territories = mapgen._grow_equal_territories(
        politics, polity_land, available, V2_WIDTH, V2_HEIGHT
    )
    if any(len(cells) < mapgen.CORE_TILES for cells in territories):
        raise RuntimeError("v3 map cannot provide equal connected cores")
    fairness = mapgen._fairness(
        countries, territories, polity_elev, polity_p, polity_biome,
        polity_river, hazards,
    )

    polities = []
    ids = mapgen.country_ids(len(countries))
    for index, (country, capital, cells) in enumerate(zip(countries, politics, territories)):
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
            "elevation_m": round(float(polity_elev[y0, x0])),
            "river_distance_tiles": round(float(worldgen.distance_transform_edt(~polity_river)[y0, x0]), 1),
            "dominant_biome": str(polity_biome[y0, x0]),
            "technology": {
                "agriculture": 1,
                "bronze_metallurgy": 2 if country["archetype"] == "highland" else 1,
                "writing": 1 if country["archetype"] in {"river_valley", "semiarid"} else 0,
            },
            "treasury_units": 100, "food_storage_units": 160, "diplomatic_status": "no_contact",
        })

    road_cells = [
        cell for cell in _build_road_cells(polities, polity_land, polity_elev, polity_river, V2_WIDTH, V2_HEIGHT, polity_biome)
        if polity_land[cell["tile"]["row"], cell["tile"]["col"]]
    ]
    for cell in road_cells:
        cell["kind"] = (
            "bridge" if polity_river[cell["tile"]["row"], cell["tile"]["col"]]
            else "road"
        )

    tiles = []
    river_cells = []
    for y in range(V2_HEIGHT):
        for x in range(V2_WIDTH):
            lake = bool(lake_mask[y, x])
            tiles.append({
                "q": x - (y - (y & 1)) // 2, "r": y, "col": x, "row": y,
                "latitude_deg": round(float(lat[y, x]), 2),
                "land": bool(land[y, x] and not lake),
                "lake": lake,
                "elevation_m": int(round(polity_elev[y, x])),
                "biome": "lake" if lake else str(polity_biome[y, x]),
                "annual_mean_temp_c": round(float(polity_tmean[y, x]), 1),
                "annual_precip_mm": int(round(polity_p[y, x])),
                "monthly_temp_c": [round(float(monthly_temp[m, y, x]), 1) for m in range(12)],
                "monthly_precip_mm": [round(float(monthly_rain[m, y, x]), 1) for m in range(12)],
                "slope": round(float(slope[y, x]), 4),
                "river": bool(polity_river[y, x] and not lake),
                "drainage_area_km2": int(basin[y, x] * V2_CELL_AREA_KM2),
                "downstream": None,
                "hazards": {key: round(float(hazards[key][y, x]), 3) for key in hazards},
                "owner_id": str(ownership[y, x]) or None,
            })
            if polity_river[y, x] and not lake:
                info = river_meta[(x, y)]
                ratio = min(1.0, info["basin"] / max(1, max_river_basin))
                depth = max(0.3, min(12.0, 0.3 + 9.6 * ratio ** 0.55))
                river_cells.append({
                    "id": f"RV{x:03d}{y:03d}",
                    "network_id": None,
                    "tile": {"col": x, "row": y},
                    "depth_m": round(depth, 3),
                    "coverage": round(min(1.0, info["coverage"]) or .15, 3),
                    "flow_m3_per_year": round(info["flow"], 1),
                    "drainage_area_km2": int(info["basin"] * V2_CELL_AREA_KM2),
                    "kind": info["kind"],
                    "terminal_lake_id": info["terminal_lake_id"],
                })
    river_cells = _label_river_networks(river_cells)
    for tile in tiles:
        x, y = tile["col"], tile["row"]
        px, py = hydro_parent[y, x]
        tile["downstream"] = {"col": int(px), "row": int(py)} if tile["land"] and px >= 0 else None

    weather_samples, events = worldgen.demo_weather_hazards(
        seed, polity_land, monthly_rain, monthly_temp, hazards, polities, V2_WIDTH, V2_HEIGHT,
    )
    world = {
        "metadata": {
            "project": "Project Eos",
            "version": "0.3.0",
            "schema_version": 3,
            "generator": "mapgen_v3_hexfirst",
            "terrain_mode": "hex_fill",
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
            "fairness": fairness,
            "core_tiles_per_country": mapgen.CORE_TILES,
            "terrain_generation": "hex-first: fields sampled and classified per hex",
            "river_depth_model": "basin_area_proxy_v3; depth is an estimate, not a hydraulic measurement",
            "hydrology_model": "meandering hex reaches + terminal endorheic lakes; closed basins stop at the shore",
        },
        "world_summary": {
            "land_hexes": int(polity_land.sum()),
            "ocean_hexes": int((~land & ~lake_mask).sum()),
            "lake_hexes": int(lake_mask.sum()),
            "lake_count": len(lakes),
            "land_area_km2": round(float(polity_land.sum() * V2_CELL_AREA_KM2)),
            "lake_area_km2": round(float(lake_mask.sum() * V2_CELL_AREA_KM2)),
            "endorheic_catchment_km2": round(float(sum(len(c) for c in by_lake.values()) * V2_CELL_AREA_KM2)),
            "maximum_elevation_m": round(float(polity_elev.max())),
            "river_hexes": len(river_cells),
            "river_cell_count": len(river_cells),
            "endorheic_river_hexes": sum(1 for cell in river_cells if cell["kind"] == "endorheic"),
            "endorheic_network_count": len({
                cell["network_id"] for cell in river_cells if cell["kind"] == "endorheic"
            }),
            "road_cell_count": len(road_cells),
            "unclaimed_land_hexes": int(np.count_nonzero(polity_land & (ownership == ""))),
        },
        "terrain": {
            "kind": "hex_fill",
            "width": V2_WIDTH,
            "height": V2_HEIGHT,
            "resolution_km": V2_RADIUS_KM,
        },
        "rendering": {
            "river_depth_stops": DEPTH_STOPS,
            "water_color": WATER_COLOR,
            "lake_depth_stops": [
                [1.0, "#93e4e8"],
                [4.0, "#5bc6d1"],
                [8.0, "#319fb2"],
                [12.0, "#1c6b80"],
            ],
            "lake_color": WATER_COLOR,
            "endorheic_tint": WATER_COLOR,
            "road_color": "#a56245",
            "road_strong_color": "#c07a55",
            "bridge_color": "#6f7f86",
        },
        "polities": polities,
        "tiles": tiles,
        "river_cells": river_cells,
        "lake_cells": _lake_cells(lakes, polity_elev),
        "road_cells": road_cells,
        "weather_samples": weather_samples,
        "illustrative_hazard_events": events,
    }
    validate_v2(world)
    return world


def generate_fair_world_v3(
    countries: list[dict[str, Any]] | None = None,
    base_seed: int | None = None,
    attempts: int = 8,
    output_dir: str | Path | None = None,
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
        water_values = [row["water"] for row in world["metadata"]["fairness"]["countries"].values()]
        if water_values and min(water_values) < 1:
            score -= .12
        if best is None or score > best[0]:
            best = (score, world)
        if score >= .72:
            break
    if best is None:
        raise RuntimeError("could not generate a playable fair v3 map")
    world = best[1]
    world["metadata"]["generation"] = {
        "base_seed": base,
        "selected_seed": world["metadata"]["seed"],
        "attempts": min(attempts, world["metadata"]["seed"] - base + 1),
        "fairness_floor": .72,
    }
    directory = Path(output_dir) if output_dir is not None else BASE_DIR / "runs" / "worlds"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"world_v3_custom_{world['metadata']['seed']}.json"
    path.write_text(
        json.dumps(world, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return world, path
