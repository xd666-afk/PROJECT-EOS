"""Road permissions, atomic queues, independent layers, and research graph contracts."""
from copy import deepcopy
from dataclasses import replace
import math

import pytest

from core.actions import ActionRejected
from core.content import ContentError, validate_content
from core.road import road_permit, river_width
from core.road_planner import plan
from core.state import GameState
from core.technology import advance, available, initialize, select


@pytest.fixture
def corridor(engine):
    state = engine.state
    country = state.countries["ELAR"]
    tiles = {(x, y): {"col": x, "row": y, "land": True, "river": False,
                      "biome": "grassland", "elevation_m": 0, "annual_precip_mm": 500}
             for x in range(12) for y in range(9)}
    data = deepcopy(state.world.data)
    data["metadata"].update(grid_width=12, grid_height=9)
    data["road_cells"] = []
    state.world = replace(state.world, tiles=tiles, data=data)
    state.countries = {"ELAR": country}
    country.tiles = list(tiles)
    country.cities = country.cities[:1]
    country.cities[0].center = (1, 4)
    country.cities[0].tiles = list(tiles)
    country.cities[0].zones = {}
    country.projects = []
    country.buildings = {}
    country.roads = set()
    country.treasury = 10000
    return engine, country


def road_action(p):
    return {"type": "BUILD", "building": "ROAD", "tile": {"col": p[0], "row": p[1]}}


def route_action(start=(1, 4), end=(8, 4)):
    return {"type": "BUILD_ROAD_ROUTE", "from": dict(col=start[0], row=start[1]),
            "to": dict(col=end[0], row=end[1])}


@pytest.mark.parametrize("biome", ["alpine", "desert", "tundra"])
def test_ancient_roads_cannot_cross_extreme_terrain(corridor, biome):
    engine, country = corridor
    engine.state.world.tiles[(2, 4)]["biome"] = biome
    before = country.treasury
    denied = engine.apply_action("ELAR", road_action((2, 4)))
    assert not denied.accepted and denied.reason_code == "ROAD_TERRAIN_TECH_REQUIRED"
    assert country.treasury == before and not country.projects
    country.known_techs.append("modern_engineering")
    accepted = engine.apply_action("ELAR", road_action((2, 4)))
    assert accepted.accepted and accepted.effects["cost"] > 15


@pytest.mark.parametrize("biome,tech", [("wetland", "drainage")])
def test_special_terrain_needs_its_specific_engineering(corridor, biome, tech):
    engine, country = corridor
    engine.state.world.tiles[(2, 4)]["biome"] = biome
    assert road_permit(engine.state, country, (2, 4))
    country.known_techs.append(tech)
    assert road_permit(engine.state, country, (2, 4)) is None


@pytest.mark.parametrize("width", [1, 2, 3, 6, 7])
def test_river_width_uses_cross_section_and_enforces_bridge_limit(corridor, width):
    engine, country = corridor
    world = engine.state.world
    for (x, y), tile in world.tiles.items():
        tile["river"] = 3 <= x < 3 + width
    country.known_techs.append("masonry_bridges")
    assert river_width(world, (3 + width // 2, 4)) == width
    permit = road_permit(engine.state, country, (3 + width // 2, 4))
    assert (permit is None) == (width <= 2)
    country.known_techs.append("modern_engineering")
    permit = road_permit(engine.state, country, (3 + width // 2, 4))
    assert (permit is None) == (width <= 6)


def test_river_length_is_not_width_and_water_is_never_a_bank(corridor):
    engine, country = corridor
    world = engine.state.world
    for (x, y), tile in world.tiles.items():
        tile["river"] = x == 4
    assert river_width(world, (4, 4)) == 1
    for tile in world.tiles.values():
        tile["land"] = False
    world.tiles[(4, 4)].update(land=True, river=True)
    assert river_width(world, (4, 4)) is None
    world.tiles[(2, 4)].update(land=False, biome="lake", river=False)
    country.known_techs.append("modern_engineering")
    assert not engine.apply_action("ELAR", road_action((2, 4))).accepted


def test_bridge_requires_research_and_complete_bank_to_bank_plan(corridor):
    engine, country = corridor
    for (x, y), tile in engine.state.world.tiles.items():
        tile["river"] = x in (4, 5)
    assert not engine.apply_action("ELAR", route_action()).accepted
    country.known_techs.append("masonry_bridges")
    quote = plan(engine.state, country, (1, 4), (8, 4))
    assert any(engine.state.world.tile(tuple(p))["river"] for p in quote["path"])
    assert engine.apply_action("ELAR", route_action()).accepted
    with pytest.raises(ActionRejected, match="两侧|一侧"):
        plan(engine.state, country, (1, 4), (4, 4))


def test_route_preview_is_pure_and_failed_purchase_is_atomic(corridor):
    engine, country = corridor
    before = engine.state.fingerprint()
    quote = plan(engine.state, country, (1, 4), (8, 4))
    assert engine.state.fingerprint() == before
    country.treasury = quote["cost"] - .1
    number = engine.state.next_project_number
    refused = engine.apply_action("ELAR", route_action())
    assert refused.reason_code == "INSUFFICIENT_TREASURY"
    assert not country.projects and engine.state.next_project_number == number
    assert country.treasury == quote["cost"] - .1


def test_auto_route_avoids_mountain_and_cannot_tunnel_through_wall(corridor):
    engine, country = corridor
    world = engine.state.world
    world.tiles[(4, 4)]["biome"] = "alpine"
    quote = plan(engine.state, country, (1, 4), (8, 4))
    assert [4, 4] not in quote["path"]
    for p, tile in world.tiles.items():
        if p[0] == 4:
            tile["biome"] = "desert"
    refused = engine.apply_action("ELAR", route_action())
    assert refused.reason_code == "ROAD_NO_ROUTE" and not country.projects
    country.known_techs.append("modern_engineering")
    assert engine.apply_action("ELAR", route_action()).accepted


def test_queued_roads_are_sequential_and_coexist_with_farms(corridor):
    engine, country = corridor
    country.buildings[(2, 4)] = "FARM"
    result = engine.apply_action("ELAR", route_action(end=(4, 4)))
    assert result.accepted
    projects = country.projects
    assert len(projects) == 3
    assert [p.get("depends_on") for p in projects] == [None, projects[0]["project_id"], projects[1]["project_id"]]
    for _ in range(30):
        engine.construction.advance_all()
    assert len(country.roads) == 1 and len(country.projects) == 2
    assert country.buildings[(2, 4)] == "FARM"
    assert country.projects[0]["remaining_days"] == 30
    for _ in range(60):
        engine.construction.advance_all()
    assert len(country.roads) == 3 and not country.projects
    target = (3, 4)
    build = {"type": "BUILD", "building": "FARM", "tile": dict(col=3, row=4)}
    assert engine.apply_action("ELAR", build).accepted
    for _ in range(45):
        engine.construction.advance_all()
    assert target in country.roads and country.buildings[target] == "FARM"


def test_lost_anchor_pauses_the_next_segment(corridor):
    engine, country = corridor
    engine.apply_action("ELAR", route_action(end=(4, 4)))
    for _ in range(30):
        engine.construction.advance_all()
    country.roads.clear()
    engine.construction.advance_all()
    assert country.projects[0]["remaining_days"] == 30
    assert "接入点" in country.projects[0]["blocked_reason"]


def test_new_road_can_be_attached_to_a_pending_project(corridor):
    engine, country = corridor
    assert engine.apply_action("ELAR", road_action((2, 4))).accepted
    assert engine.apply_action("ELAR", road_action((3, 4))).accepted
    assert country.projects[1]["depends_on"] == country.projects[0]["project_id"]


def test_two_cell_bridge_cannot_be_smuggled_in_as_single_tile_build(corridor):
    engine, country = corridor
    country.known_techs.append("masonry_bridges")
    for (x, y), tile in engine.state.world.tiles.items():
        tile["river"] = x in (2, 3)
    result = engine.apply_action("ELAR", road_action((2, 4)))
    assert result.reason_code == "ROAD_BRIDGE_PLAN_REQUIRED" and not country.projects


def test_engineering_discount_changes_real_cost_and_work(corridor):
    engine, country = corridor
    base = plan(engine.state, country, (1, 4), (4, 4))
    country.known_techs.append("surveying")
    improved = plan(engine.state, country, (1, 4), (4, 4))
    assert improved["cost"] == pytest.approx(base["cost"] * .85)
    assert improved["work_days"] == pytest.approx(base["work_days"] * .85)
    before = country.treasury
    accepted = engine.apply_action("ELAR", route_action(end=(4, 4)))
    assert accepted.accepted
    assert before - country.treasury == pytest.approx(improved["cost"])


def test_legacy_max_level_is_not_a_modern_engineering_license(corridor):
    engine, country = corridor
    country.technology = {field: 6 for field in country.technology}
    initialize(country, engine.state.config, reset=True)
    engine.state.world.tiles[(2, 4)]["biome"] = "desert"
    assert "modern_engineering" not in country.known_techs
    assert engine.apply_action("ELAR", road_action((2, 4))).reason_code == "ROAD_TERRAIN_TECH_REQUIRED"


def test_saved_route_preserves_dependencies_and_research_progress(tmp_path):
    from core.rules import RuleEngine
    state = GameState.load("examples/civil_networks/save.json")
    engine = RuleEngine(state)
    country = state.countries["A"]
    select(country, state.config, "masonry_bridges")
    advance(state, country, 7.5)
    assert engine.apply_action("A", route_action(start=(14, 22), end=(13, 20))).accepted
    engine.construction.advance_all()
    saved = tmp_path / "road-queue.json"
    state.save(saved)
    restored = GameState.load(saved)
    assert restored.fingerprint() == state.fingerprint()
    assert restored.countries["A"].projects == country.projects
    assert restored.countries["A"].research_node == "masonry_bridges"
    assert restored.countries["A"].tech_progress["masonry_bridges"] == 7.5


def test_legacy_migration_grants_consistent_foundations(engine):
    country = engine.state.countries["ELAR"]
    country.technology.update(agriculture=3, bronze_metallurgy=1, writing=1)
    initialize(country, engine.state.config, reset=True)
    assert "bronze" in country.known_techs
    assert country.technology["bronze_metallurgy"] >= 2


def test_old_research_points_survive_a_new_cross_branch_prerequisite(engine):
    country = engine.state.countries["ELAR"]
    country.technology.update(agriculture=2, bronze_metallurgy=1, writing=1)
    country.research_field = "agriculture"
    country.research_progress["agriculture"] = 9.5
    country.research_initialized = False
    initialize(country, engine.state.config)
    assert "irrigation" not in available(country, engine.state.config)
    assert country.research_node == "bronze"
    assert country.tech_progress["irrigation"] == 9.5
    initialize(country, engine.state.config)
    assert country.tech_progress["irrigation"] == 9.5
    advance(engine.state, country, 20)
    assert "irrigation" in available(country, engine.state.config)
    select(country, engine.state.config, "irrigation")
    assert country.tech_progress["irrigation"] == 9.5


def test_graph_prerequisites_and_distinct_national_strategies(engine):
    country = engine.state.countries["ELAR"]
    config = engine.state.config
    initialize(country, config, reset=True)
    ready = available(country, config)
    assert len(ready) >= 3
    denied = engine.apply_action("ELAR", {"type": "SET_RESEARCH", "node": "modern_engineering"})
    assert denied.reason_code == "RESEARCH_PREREQUISITES"
    assert len(config["research_tree"]["modern_engineering"]["requires"]) >= 3
    country.known_techs = ["farming", "tools", "symbols", "bronze", "storage", "script"]
    ready = available(country, config)
    assert {"terracing", "masonry_bridges", "surveying", "irrigation", "laws", "iron"} <= set(ready)


def test_research_switching_preserves_progress_and_completes_only_chosen_node(engine):
    state = engine.state
    country = state.countries["ELAR"]
    country.known_techs = ["farming", "tools", "symbols", "storage", "bronze"]
    select(country, state.config, "terracing")
    advance(state, country, 10)
    select(country, state.config, "masonry_bridges")
    advance(state, country, 10)
    assert country.tech_progress["terracing"] == 10
    select(country, state.config, "terracing")
    advance(state, country, 25)
    assert "terracing" in country.known_techs and "masonry_bridges" not in country.known_techs
    assert country.tech_progress["masonry_bridges"] == 10 and country.research_node is None
    assert state.event_log[-1]["node"] == "terracing"


def test_optional_agronomy_changes_real_daily_production(engine):
    country = engine.state.countries["ELAR"]
    weather = engine.state.weather.sample(engine.state.day_index)
    # The model's own settlement gives the same weather and starting economy.
    original = deepcopy(country)
    engine.economy.settle_country(country, weather)
    baseline = country.last_economy["food_production"]
    engine.state.countries["ELAR"] = country = original
    country.known_techs.append("terracing")
    engine.economy.settle_country(country, weather)
    assert country.last_economy["food_production"] == pytest.approx(baseline * 1.12)


def test_old_save_migration_and_new_roundtrip_are_deterministic(tmp_path):
    state = GameState.load("examples/hexfirst/save.json")
    country = next(iter(state.countries.values()))
    coord = country.tiles[0]
    country.roads.add(coord)
    country.buildings[coord] = "FARM"
    country.tech_progress["surveying"] = 7.25
    save = tmp_path / "updated.json"
    state.save(save)
    restored = GameState.load(save)
    assert restored.fingerprint() == state.fingerprint()
    assert coord in restored.countries[country.country_id].roads
    assert restored.countries[country.country_id].buildings[coord] == "FARM"
    country.research_initialized = False
    country.buildings[coord] = "ROAD"
    country.roads.clear()
    state.save(save)
    migrated = GameState.load(save).countries[country.country_id]
    assert coord in migrated.roads and coord not in migrated.buildings
    assert migrated.research_initialized
    assert "modern_engineering" not in migrated.known_techs


@pytest.mark.parametrize("corruption", ["cycle", "missing", "negative", "nan"])
def test_content_validation_rejects_broken_graphs(state, corruption):
    config = deepcopy(state.config)
    if corruption == "cycle":
        config["research_tree"]["farming"]["requires"] = ["storage"]
    elif corruption == "missing":
        config["research_tree"]["storage"]["requires"] = ["missing"]
    else:
        config["research_tree"]["storage"]["cost"] = -1 if corruption == "negative" else math.nan
    with pytest.raises(ContentError):
        validate_content(config)
