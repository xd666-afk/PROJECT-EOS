"""Fair random-map and custom-nation generator built on the restored world model."""
from __future__ import annotations

from collections import deque
import json
import math
from pathlib import Path
import secrets
from typing import Any

import numpy as np

import worldgen
from worldgen import (
    CELL_AREA_KM2, H, W, demo_weather_hazards, gen_base, gen_climate,
    gen_hazards, gen_hydrology, hex_distance, neighbors, package_world, validate,
)

BASE_DIR = Path(__file__).resolve().parent
COUNTRY_IDS = ["A", "B", "C", "D"]
COUNTRY_PALETTE = [
    "#e7b45f", "#63b1c9", "#d97f75", "#b98bcb",
    "#8fbf7f", "#d6a36f", "#7f9ed6", "#c98fae",
    "#9fc9b4", "#c4b56f", "#aa8fd1", "#d68a8a",
]
ARCHETYPES = {
    "river_valley": "河谷文明",
    "maritime": "海洋城邦",
    "highland": "山麓诸侯",
    "semiarid": "河岸王权",
}
DEFAULT_COUNTRIES = [
    {"name": "国家A", "color": "#e7b45f", "archetype": "river_valley", "population": 37000},
    {"name": "国家B", "color": "#63b1c9", "archetype": "maritime", "population": 21000},
    {"name": "国家C", "color": "#d97f75", "archetype": "highland", "population": 15500},
    {"name": "国家D", "color": "#b98bcb", "archetype": "semiarid", "population": 28000},
]
CORE_TILES = 16


def country_ids(count: int) -> list[str]:
    """Stable generic IDs A, B, C, ... for any supported country count."""
    if count < 1:
        raise ValueError("at least one country is required")
    return [chr(ord("A") + index) for index in range(count)]


def normalize_countries(countries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if countries is None:
        return [dict(item) for item in DEFAULT_COUNTRIES]
    if not 2 <= len(countries) <= 12:
        raise ValueError("2-12 countries are required")
    normalized = []
    seen_colors = set()
    for index, source in enumerate(countries):
        base = DEFAULT_COUNTRIES[index % len(DEFAULT_COUNTRIES)]
        name = str(source.get("name") or f"国家{chr(ord('A') + index)}").strip()
        color = str(source.get("color") or COUNTRY_PALETTE[index % len(COUNTRY_PALETTE)]).strip()
        archetype = source.get("archetype", base["archetype"])
        population = int(source.get("population", base["population"]))
        if not 1 <= len(name) <= 24:
            raise ValueError("country name must contain 1-24 characters")
        if not (len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
            raise ValueError("country color must be a #RRGGBB value")
        if color.lower() in seen_colors:
            raise ValueError("country colors must be unique")
        if archetype not in ARCHETYPES:
            raise ValueError("unknown country archetype")
        if not 8000 <= population <= 60000:
            raise ValueError("starting population must be between 8000 and 60000")
        seen_colors.add(color.lower())
        normalized.append({
            "name": name, "color": color.lower(), "archetype": archetype,
            "population": population,
        })
    return normalized


def _archetype_specs(land, elev, biome, p, tmean, river, basin, slope, dist_ocean, hazards, lat):
    near_river = worldgen.distance_transform_edt(~river)
    soil = np.clip((p - 220) / 950, 0, 1) * np.clip((1900 - p) / 750, .2, 1)
    safe = 1 - .34 * hazards["earthquake"] - .26 * hazards["flood"] - .2 * hazards["drought"]
    arable = np.isin(biome, ["grassland", "forest", "savanna", "steppe", "wetland"])
    base = soil * 2 + safe + 1 / (1 + near_river) + .35 * (1 - slope)
    return {
        "river_valley": (
            land & arable & (elev < 750) & (lat > 19) & (lat < 43) & (near_river < 3) & (dist_ocean > 120),
            base + .65 * np.clip(np.log1p(basin) / 7, 0, 1) + .4 * (p > 650),
        ),
        "maritime": (
            land & (dist_ocean < 100) & (elev < 600) & (p > 480) & (lat > 23) & (lat < 45),
            base + 1.6 * np.clip((100 - dist_ocean) / 100, 0, 1) - hazards["earthquake"],
        ),
        "highland": (
            land & (elev > 650) & (elev < 1800) & (p > 420) & (tmean > 6) & (lat > 25) & (lat < 51),
            base + .8 * np.clip(elev / 1800, 0, 1) + .5 * hazards["earthquake"],
        ),
        "semiarid": (
            land & (p >= 180) & (p < 590) & (lat > 13) & (lat < 41) & (near_river < 3) & (dist_ocean > 110),
            base + 1.1 * np.clip((750 - p) / 600, 0, 1) + .6 * np.log1p(basin) / 7,
        ),
    }


def _place_capitals(countries, land, elev, biome, p, tmean, river, basin, slope, dist_ocean, hazards, lat, w=W, h=H, allow_fallback=False, forbidden=None):
    specs = _archetype_specs(
        land, elev, biome, p, tmean, river, basin, slope, dist_ocean, hazards, lat
    )
    placed = []
    blocked = np.zeros((h, w), bool)
    for country in countries:
        valid, score = specs[country["archetype"]]
        location = None
        for separation in (12, 10, 8, 6):
            candidate_scores = np.where(valid, score, -1e8).copy()
            if forbidden is not None:
                candidate_scores[forbidden] = -1e8
            for capital in placed:
                for y in range(h):
                    for x in range(w):
                        if hex_distance((x, y), capital) < separation:
                            candidate_scores[y, x] = -1e8
            candidate_scores[blocked] = -1e8
            y, x = np.unravel_index(np.argmax(candidate_scores), candidate_scores.shape)
            if candidate_scores[y, x] > -1e6:
                location = (int(x), int(y))
                break
        if location is None and allow_fallback:
            candidate_scores = np.where(land, score, -1e8).copy()
            if forbidden is not None:
                candidate_scores[forbidden] = -1e8
            for capital in placed:
                for y in range(h):
                    for x in range(w):
                        if hex_distance((x, y), capital) < 4:
                            candidate_scores[y, x] = -1e8
            if np.max(candidate_scores) > -1e6:
                y, x = np.unravel_index(np.argmax(candidate_scores), candidate_scores.shape)
                location = (int(x), int(y))
        if location is None:
            raise RuntimeError(f"no fair capital location for {country['name']}")
        placed.append(location)
        blocked[location[1], location[0]] = True
    return placed


def _grow_equal_territories(capitals, land, available, w=W, h=H):
    ownership = np.full((h, w), "", dtype=object)
    territories = []
    ids = country_ids(len(capitals))
    for index, capital in enumerate(capitals):
        country_id = ids[index]
        queue = deque([capital])
        seen = {capital}
        cells = []
        while queue and len(cells) < CORE_TILES:
            x, y = queue.popleft()
            if not land[y, x] or not available[y, x] or ownership[y, x]:
                continue
            ownership[y, x] = country_id
            available[y, x] = False
            cells.append([x, y])
            for nx, ny in neighbors(x, y, w, h):
                if (nx, ny) not in seen:
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        territories.append(cells)
    return ownership, territories


def _fairness(countries, territories, elev, p, biome, river, hazards):
    food_yield = {"grassland": 1.0, "forest": .82, "savanna": .9, "steppe": .72,
                  "wetland": 1.08, "desert": .25, "alpine": .08, "tundra": .12}
    rows = []
    for cells in territories:
        food = sum(food_yield.get(str(biome[y, x]), .4) * (1.1 if river[y, x] else 1.0)
                   for x, y in cells)
        mining = sum(.5 + max(float(elev[y, x]), 0) / 1200 for x, y in cells)
        safety = sum(1 - .4 * (hazards["flood"][y, x] + hazards["drought"][y, x]) / 2 for x, y in cells)
        water = sum(float(river[y, x]) for x, y in cells)
        rows.append({"food": food, "mining": mining, "safety": safety, "water": water})
    variations = []
    for metric in rows[0]:
        values = [row[metric] for row in rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        variations.append(math.sqrt(variance) / max(mean, 1e-9))
    count = len(rows)
    ids = country_ids(count)
    score = max(0.0, min(1.0, 1 - sum(variations) / len(variations)))
    return {
        "score": round(score, 4),
        "coefficient_of_variation": {
            key: round(sum((row[key] - sum(r[key] for r in rows) / count) ** 2 for row in rows) / count, 4) ** .5
            / max(sum(row[key] for row in rows) / count, 1e-9)
            for key in rows[0]
        },
        "countries": {ids[i]: rows[i] for i in range(count)},
        "equal_core_tiles": len({len(cells) for cells in territories}) == 1,
    }


def _generate_candidate(seed: int, countries: list[dict[str, Any]]) -> dict[str, Any]:
    rng, X, Y, lat, land, elev, fault, ridge = gen_base(seed)
    p, tmean, monthly_temp, monthly_rain, biome, dist_ocean = gen_climate(rng, lat, land, elev)
    parent, flow, basin, river, slope = gen_hydrology(land, elev, p)
    hazards = gen_hazards(land, elev, fault, biome, p, tmean, lat, river, basin, slope, dist_ocean)
    capitals = _place_capitals(
        countries, land, elev, biome, p, tmean, river, basin, slope, dist_ocean, hazards, lat
    )
    available = land.copy()
    ownership, territories = _grow_equal_territories(capitals, land, available)
    if any(len(cells) < CORE_TILES for cells in territories):
        raise RuntimeError("map cannot provide equal connected cores")
    fairness = _fairness(countries, territories, elev, p, biome, river, hazards)
    polities = []
    ids = country_ids(len(countries))
    for index, (country, capital, cells) in enumerate(zip(countries, capitals, territories)):
        x0, y0 = capital
        polities.append({
            "id": ids[index], "name": country["name"], "type": country["archetype"],
            "color": country["color"], "government": ARCHETYPES[country["archetype"]],
            "description": f"{ARCHETYPES[country['archetype']]}风格的自定义国家",
            "population": country["population"],
            "capital": {"col": x0, "row": y0, "q": x0 - (y0 - (y0 & 1)) // 2, "r": y0},
            "initial_tiles": cells,
            "territorial_area_km2": round(len(cells) * CELL_AREA_KM2),
            "avg_annual_temp_c": round(float(tmean[y0, x0]), 1),
            "avg_annual_precip_mm": round(float(p[y0, x0])),
            "elevation_m": round(float(elev[y0, x0])),
            "river_distance_tiles": round(float(worldgen.distance_transform_edt(~river)[y0, x0]), 1),
            "dominant_biome": str(biome[y0, x0]),
            "technology": {
                "agriculture": 1,
                "bronze_metallurgy": 2 if country["archetype"] == "highland" else 1,
                "writing": 1 if country["archetype"] in {"river_valley", "semiarid"} else 0,
            },
            "treasury_units": 100, "food_storage_units": 160, "diplomatic_status": "no_contact",
        })
    samples, events = demo_weather_hazards(seed, land, monthly_rain, monthly_temp, hazards, polities)
    world = package_world(
        seed, land, elev, lat, biome, p, tmean, monthly_rain, monthly_temp,
        parent, flow, basin, river, slope, hazards, polities, ownership, samples, events,
    )
    world["metadata"]["custom_game"] = True
    world["metadata"]["fairness"] = fairness
    world["metadata"]["core_tiles_per_country"] = CORE_TILES
    validate(world)
    return world


def generate_fair_world(
    countries: list[dict[str, Any]] | None = None,
    base_seed: int | None = None,
    attempts: int = 8,
    generation_version: str = "v1",
) -> tuple[dict[str, Any], Path]:
    normalized = normalize_countries(countries)
    if generation_version == "v2":
        from mapgen_v2 import generate_fair_world_v2
        return generate_fair_world_v2(normalized, base_seed=base_seed, attempts=attempts)
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
        raise RuntimeError("could not generate a playable fair map")
    world = best[1]
    world["metadata"]["generation"] = {
        "base_seed": base,
        "selected_seed": world["metadata"]["seed"],
        "attempts": min(attempts, world["metadata"]["seed"] - base + 1),
        "fairness_floor": 0.72,
    }
    directory = BASE_DIR / "runs" / "worlds"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"world_custom_{world['metadata']['seed']}.json"
    path.write_text(json.dumps(world, ensure_ascii=False, indent=1), encoding="utf-8")
    return world, path
