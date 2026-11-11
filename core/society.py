"""Derived city-society values shared by rules, AI observations, and the dashboard."""
from __future__ import annotations

from collections import Counter
import math
from typing import Any

from core.state import tile_key

FOOD_BUILDINGS = {"FARM", "GRANARY", "IRRIGATION", "GREAT_GRANARY"}
MINING_BUILDINGS = {"MINE", "WORKSHOP", "GREAT_FORGE"}
TRADE_BUILDINGS = {"ROAD", "MARKET"}
SCHOLAR_BUILDINGS = {"LIBRARY", "TEMPLE", "GREAT_LIBRARY"}
SPECIALIZATION_NAMES = {
    "agriculture": "农业聚落",
    "mining": "矿业城邦",
    "trade": "商贸枢纽",
    "scholar": "学术祭祀中心",
    "balanced": "综合聚落",
}


def building_counts(country) -> Counter:
    return Counter(country.buildings.values())


def housing_capacity(country, config: dict[str, Any]) -> float:
    housing = config["housing"]
    total = housing["base_capacity"] + len(country.tiles) * housing["territory_per_tile"]
    counts = building_counts(country)
    total += counts.get("ROAD", 0) * housing["road_bonus"]
    for building, bonus in housing["per_building_bonus"].items():
        total += counts.get(building, 0) * bonus
    return round(total, 2)


def food_capacity(country, config: dict[str, Any]) -> float:
    storage = config["food_storage"]
    counts = building_counts(country)
    total = (
        storage["base_capacity"]
        + country.population / 1000.0 * storage["per_1000_population"]
        + counts.get("GRANARY", 0) * storage["granary_bonus"]
        + counts.get("IRRIGATION", 0) * storage["irrigation_bonus"]
        + counts.get("GREAT_GRANARY", 0) * storage["great_granary_bonus"]
    )
    return round(total, 2)


def default_zone(center: tuple[int, int], coord: tuple[int, int], tile: dict[str, Any]) -> str:
    if coord == center:
        return "residential"
    if tile["elevation_m"] >= 800 or tile["biome"] in {"alpine", "tundra"}:
        return "industry"
    if tile["biome"] in {"forest", "rainforest"}:
        return "farm"
    if tile["biome"] == "desert":
        return "commerce"
    if tile["biome"] == "steppe":
        return "industry"
    return "farm"


def city_housing(city, country, config: dict[str, Any]) -> float:
    housing = config["housing"]
    total = housing["base_capacity"] + len(city.tiles) * housing["territory_per_tile"]
    counts = Counter(
        country.buildings[coord] for coord in city.tiles if coord in country.buildings
    )
    total += counts.get("ROAD", 0) * housing["road_bonus"]
    for building, bonus in housing["per_building_bonus"].items():
        total += counts.get(building, 0) * bonus
    zones = Counter(city.zones.get(coord, "unzoned") for coord in city.tiles)
    total += zones.get("residential", 0) * config["city_zones"]["residential"]["housing"]
    return round(total, 2)


def zone_adjacency(city, coord: tuple[int, int], world=None) -> dict[str, float]:
    """Local spatial bonus: clustered industry, central commerce, residential-supported scholars."""
    from worldgen import neighbors

    zone = city.zones.get(coord, "unzoned")
    if world is not None:
        adjacent = world.neighbors(*coord)
    else:
        adjacent = neighbors(*coord)
    neighbor_zones = Counter(
        city.zones.get(neighbor, "unzoned") for neighbor in adjacent
    )
    food = 1.0
    mining = 1.0
    tax = 1.0
    research = 1.0
    if zone == "farm":
        food += min(0.30, neighbor_zones.get("farm", 0) * 0.05)
    elif zone == "industry":
        mining += min(0.36, neighbor_zones.get("industry", 0) * 0.10)
    elif zone == "commerce":
        if city.center in adjacent:
            tax += 0.15
        tax += min(0.20, neighbor_zones.get("commerce", 0) * 0.05)
    elif zone == "scholar":
        research += min(0.24, neighbor_zones.get("residential", 0) * 0.08)
    return {"food": food, "mining": mining, "tax": tax, "research": research}


def city_service_targets(city, country, config: dict[str, Any]) -> dict[str, float]:
    settings = config["city_services"]
    counts = Counter(
        country.buildings[coord] for coord in city.tiles if coord in country.buildings
    )
    zones = Counter(city.zones.values())
    crowding = max(
        0.0, city.population / 1000.0 - city_housing(city, country, config)
    )
    industry = zones.get("industry", 0)
    security = (
        settings["base"]
        + counts.get("TEMPLE", 0) * settings["temple_security"]
        + counts.get("MARKET", 0) * settings["market_security"]
        + counts.get("ROAD", 0) * settings["road_security"]
        - industry * settings["industry_security_penalty"]
        - crowding * settings["crowding_security_penalty"]
        + settings["budget_security"].get(city.budget, 0.0)
    )
    food_deficit = (
        settings["food_deficit_health_penalty"]
        if city.food_need > 1e-9 and city.food_balance < 0
        else 0.0
    )
    health = (
        settings["base"]
        + counts.get("GRANARY", 0) * settings["granary_health"]
        + counts.get("IRRIGATION", 0) * settings["irrigation_health"]
        + counts.get("TEMPLE", 0) * settings["temple_health"]
        + counts.get("MARKET", 0) * settings["market_health"]
        - industry * settings["industry_health_penalty"]
        - crowding * settings["crowding_health_penalty"]
        - food_deficit
        + settings["budget_health"].get(city.budget, 0.0)
    )
    return {
        "security": round(max(5.0, min(95.0, security)), 2),
        "health": round(max(5.0, min(95.0, health)), 2),
    }


def service_status(value: float, config: dict[str, Any]) -> str:
    settings = config["city_services"]
    if value < settings["critical_threshold"]:
        return "危机"
    if value < settings["low_threshold"]:
        return "紧张"
    return "良好"


def city_livability_target(city, country, config: dict[str, Any]) -> float:
    zones = Counter(city.zones.values())
    counts = Counter(
        country.buildings[coord] for coord in city.tiles if coord in country.buildings
    )
    target = 52.0
    target += zones.get("residential", 0) * 2.5
    target += zones.get("commerce", 0) * 1.2
    target += zones.get("scholar", 0) * 1.5
    target -= zones.get("industry", 0) * 1.8
    target += counts.get("TEMPLE", 0) * 7
    target += counts.get("MARKET", 0) * 2
    target += counts.get("GRANARY", 0) * 2
    budget = config["city_budgets"].get(city.budget, config["city_budgets"]["balanced"])
    target += budget["livability"]
    service_base = config["city_services"]["base"]
    target += (city.security - service_base) * 0.08
    target += (city.health - service_base) * 0.08
    target -= max(0.0, city.population / 1000.0 - city_housing(city, country, config)) * 2
    return max(10.0, min(95.0, target))


def city_static_metrics(city, country, world, config: dict[str, Any]) -> dict[str, Any]:
    city_need = city.food_need
    city_ratio = city.food_output / city_need if city_need > 1e-9 else 0.0
    if city_need <= 1e-9:
        food_status = "待统计"
    elif city.food_balance >= 0:
        food_status = "盈余"
    else:
        food_status = "缺口"
    service_targets = city_service_targets(city, country, config)
    settings = config["city_services"]
    governance_note = ""
    if city.managed_by == "ai" and city_need > 1e-9:
        focus_label = config["city_focuses"].get(city.focus, {}).get(
            "label", city.focus
        )
        if city_ratio < 0.95:
            governance_note = (
                f"粮食自给仅 {city_ratio:.0%}，优先扩张农业区并转入增长方针"
            )
        elif city.security < settings["low_threshold"]:
            governance_note = (
                f"治安仅 {city.security:.0f}，提高服务预算并等待神庙/道路覆盖"
            )
        elif city.health < settings["low_threshold"]:
            governance_note = (
                f"卫生仅 {city.health:.0f}，提高服务预算并等待粮仓/灌溉覆盖"
            )
        else:
            governance_note = f"粮食自给 {city_ratio:.0%}，按{focus_label}方向继续规划"
    food = 0.0
    mining = 0.0
    biomes = Counter()
    building_counts_for_city = Counter()
    for coord in city.tiles:
        tile = world.tile(coord)
        biome = tile["biome"]
        biomes[biome] += 1
        food += config["biome_food_yield"].get(biome, 0.4) * (
            1.1 if tile["river"] else 1.0
        )
        mining += 1 + min(max(tile["elevation_m"], 0) / 1500, 1.5)
        if coord in country.buildings:
            building_counts_for_city[country.buildings[coord]] += 1
    dominant = biomes.most_common(1)[0][0] if biomes else "unknown"
    return {
        "city_id": city.city_id,
        "name": city.name,
        "center": list(city.center),
        "population": city.population,
        "population_share": round(city.population / max(country.population, 1), 4),
        "focus": city.focus,
        "focus_label": config["city_focuses"][city.focus]["label"],
        "housing": city_housing(city, country, config),
        "tiles": len(city.tiles),
        "food_potential": round(food, 2),
        "food_output": round(city.food_output, 3),
        "food_need": round(city.food_need, 3),
        "food_balance": round(city.food_balance, 3),
        "food_loss": round(city.food_loss, 3),
        "food_self_sufficiency": round(city_ratio, 3),
        "food_status": food_status,
        "governance_note": governance_note,
        "budget": city.budget,
        "budget_label": config["city_budgets"].get(
            city.budget, config["city_budgets"]["balanced"]
        )["label"],
        "local_revenue": round(city.local_revenue, 4),
        "local_upkeep": round(city.local_upkeep, 4),
        "local_net": round(city.local_net, 4),
        "security": round(city.security, 2),
        "health": round(city.health, 2),
        "security_target": service_targets["security"],
        "health_target": service_targets["health"],
        "security_status": service_status(city.security, config),
        "health_status": service_status(city.health, config),
        "mining_potential": round(mining, 2),
        "dominant_biome": dominant,
        "buildings": dict(building_counts_for_city),
        "building_tiles": {
            tile_key(coord): country.buildings[coord]
            for coord in city.tiles if coord in country.buildings
        },
        "founded_day": city.founded_day,
        "managed_by": city.managed_by,
        "livability": round(city.livability, 2),
        "livability_factor": round(0.8 + max(0, min(100, city.livability)) / 200.0, 4),
        "tiles_detail": [
            {
                "coord": list(coord),
                "biome": world.tile(coord)["biome"],
                "zone": city.zones.get(coord, "unzoned"),
                "adjacency": {
                    key: round(value, 3)
                    for key, value in zone_adjacency(city, coord, world).items()
                },
            }
            for coord in city.tiles
        ],
        "zones": {
            tile_key(coord): city.zones.get(coord, "unzoned") for coord in city.tiles
        },
    }


def city_tier(population: int) -> str:
    if population >= 50000:
        return "大都会"
    if population >= 35000:
        return "都城"
    if population >= 20000:
        return "城邑"
    return "聚落"


def specialization(country) -> str:
    counts = building_counts(country)
    scores = {
        "agriculture": sum(counts[name] for name in FOOD_BUILDINGS),
        "mining": sum(counts[name] for name in MINING_BUILDINGS),
        "trade": sum(counts[name] for name in TRADE_BUILDINGS),
        "scholar": sum(counts[name] for name in SCHOLAR_BUILDINGS),
    }
    best = max(scores, key=scores.get)
    return SPECIALIZATION_NAMES[best if scores[best] > 0 else "balanced"]


def stability_factor(stability: float, config: dict[str, Any]) -> float:
    settings = config["stability"]
    low = settings["minimum_production_factor"]
    high = settings["maximum_production_factor"]
    return low + (high - low) * max(0.0, min(100.0, stability)) / 100.0


VICTORY_NAMES = {
    "prosperity": "繁荣",
    "knowledge": "知识",
    "dominion": "疆域",
    "harmony": "安定",
}


def score_country(country, config: dict[str, Any]) -> dict[str, Any]:
    """Composite score with four different viable strengths, not one resource race."""
    counts = building_counts(country)
    food_room = food_capacity(country, config)
    housing = housing_capacity(country, config)
    technology_total = sum(country.technology.values())
    wonders = sum(
        counts.get(name, 0)
        for name in ("GREAT_GRANARY", "GREAT_FORGE", "GREAT_LIBRARY")
    )
    scores = {
        "prosperity": round(
            country.population / 1000 * 1.5
            + min(country.food, food_room) / 30
            + counts.get("MARKET", 0) * 4
            + counts.get("WORKSHOP", 0) * 2,
            2,
        ),
        "knowledge": round(
            technology_total * 9
            + counts.get("LIBRARY", 0) * 10
            + counts.get("GREAT_LIBRARY", 0) * 20,
            2,
        ),
        "dominion": round(
            len(country.tiles) * 2.5
            + len(country.outposts) * 10
            + wonders * 20,
            2,
        ),
        "harmony": round(
            country.stability * 0.45
            + max(0.0, housing - country.population / 1000) * 1.1
            + counts.get("TEMPLE", 0) * 3,
            2,
        ),
    }
    total = round(
        scores["prosperity"] * 0.27
        + scores["knowledge"] * 0.28
        + scores["dominion"] * 0.24
        + scores["harmony"] * 0.21,
        1,
    )
    ranked_paths = sorted(scores, key=scores.get, reverse=True)
    path = ranked_paths[0]
    if scores[path] < scores[ranked_paths[1]] * 1.12:
        path = "balanced"
    labels = {**VICTORY_NAMES, "balanced": "均衡"}
    return {
        "total": total,
        "breakdown": scores,
        "victory_path": path,
        "victory_label": labels[path],
    }


VICTORY_CONDITION_NAMES = {
    "knowledge": "知识胜利",
    "prosperity": "繁荣胜利",
    "dominion": "疆域胜利",
    "harmony": "安定胜利",
}


def _clamp_progress(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def victory_progress(country, state) -> dict[str, Any]:
    """Four explicit win conditions with visible progress, not just a score race."""
    settings = state.config["victory_conditions"]
    knowledge = settings["knowledge"]
    min_tech = min(country.technology.values()) if country.technology else 0
    knowledge_progress = _clamp_progress(min_tech / max(1, knowledge["min_tech_level"]))

    prosperity = settings["prosperity"]
    capacity = max(food_capacity(country, state.config), 1e-9)
    food_ratio = country.food / capacity
    prosperity_progress = _clamp_progress(
        min(
            country.population / prosperity["population"],
            country.treasury / prosperity["treasury"],
            food_ratio / prosperity["food_ratio"],
        )
    )

    dominion = settings["dominion"]
    rivals = [
        entity for entity in state.countries.values()
        if entity.country_id != country.country_id
    ]
    rival_average = (
        sum(len(entity.tiles) for entity in rivals) / len(rivals) if rivals else 0.0
    )
    required_tiles = max(
        dominion["min_tiles"], math.ceil(rival_average * dominion["lead_ratio"])
    )
    dominion_progress = _clamp_progress(
        min(
            len(country.tiles) / max(1, required_tiles),
            len(country.cities) / max(1, dominion["min_cities"]),
        )
    )

    harmony = settings["harmony"]
    livability = (
        sum(city.livability for city in country.cities) / len(country.cities)
        if country.cities else 0.0
    )
    harmony_progress = _clamp_progress(
        min(
            country.stability / harmony["stability"],
            livability / harmony["livability"],
            country.population / harmony["population"],
        )
    )

    conditions = {
        "knowledge": {
            "label": VICTORY_CONDITION_NAMES["knowledge"],
            "progress": knowledge_progress,
            "achieved": knowledge_progress >= 1.0,
            "detail": f"科技线最低 {min_tech}/{knowledge['min_tech_level']}",
        },
        "prosperity": {
            "label": VICTORY_CONDITION_NAMES["prosperity"],
            "progress": prosperity_progress,
            "achieved": prosperity_progress >= 1.0,
            "detail": (
                f"人口 {country.population / 1000:.1f}k/{prosperity['population'] / 1000:.0f}k"
                f" · 财政 {country.treasury:.0f}/{prosperity['treasury']:.0f}"
                f" · 存粮 {food_ratio:.0%}"
            ),
        },
        "dominion": {
            "label": VICTORY_CONDITION_NAMES["dominion"],
            "progress": dominion_progress,
            "achieved": dominion_progress >= 1.0,
            "detail": (
                f"领土 {len(country.tiles)}/{required_tiles}"
                f" · 城市 {len(country.cities)}/{dominion['min_cities']}"
            ),
        },
        "harmony": {
            "label": VICTORY_CONDITION_NAMES["harmony"],
            "progress": harmony_progress,
            "achieved": harmony_progress >= 1.0,
            "detail": (
                f"稳定 {country.stability:.0f}/{harmony['stability']:.0f}"
                f" · 均宜居 {livability:.0f}/{harmony['livability']:.0f}"
                f" · 人口 {country.population / 1000:.1f}k"
            ),
        },
    }
    achieved = [key for key, value in conditions.items() if value["achieved"]]
    primary = (
        max(achieved, key=lambda key: conditions[key]["progress"]) if achieved else None
    )
    return {
        "any": bool(achieved),
        "achieved": achieved,
        "primary": primary,
        "label": VICTORY_CONDITION_NAMES[primary] if primary else "",
        "conditions": conditions,
    }


def starting_era_for_year(config: dict[str, Any], astronomical_year: int) -> dict[str, Any]:
    for era in config["eras"]:
        maximum = era.get("max_astronomical_year")
        if maximum is None or astronomical_year <= maximum:
            return dict(era)
    return dict(config["eras"][-1])


def era_info(
    config: dict[str, Any], minimum_technology_level: int, start_era_index: int = 1
) -> dict[str, Any]:
    current = config["eras"][0]
    for era in config["eras"]:
        if era["index"] <= start_era_index or minimum_technology_level >= era["min_tech_level"]:
            current = era
    return dict(current)
