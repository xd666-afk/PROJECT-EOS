"""Exercise the military branch against the shipped v0.35 hex-first world/save."""
import json
from pathlib import Path

import pytest

from core.rules import RuleEngine
from core.simulation import Simulation
from core.state import GameState, relation_key
from core.road import road_node_owners
from live_server import LiveSession, project_world

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples/hexfirst/save.json"


@pytest.fixture
def integrated():
    return Simulation.load(DEMO, use_mock_agents=False)


def test_legacy_hexfirst_save_migrates_and_resumes_without_changing_source(integrated, tmp_path):
    original = DEMO.read_bytes()
    state = integrated.state
    assert list(state.countries) == ["A", "B", "C", "D"]
    assert state.config["movement"]["hostile_cost"] == 1.25
    assert state.road_connection_level() == 3
    assert integrated.step(3) == 3
    saved = state.save(tmp_path / "upgraded.json")
    restored = Simulation.load(saved, use_mock_agents=False)
    assert restored.state.fingerprint() == state.fingerprint()
    integrated.step(2)
    restored.step(2)
    assert restored.state.fingerprint() == state.fingerprint()
    assert DEMO.read_bytes() == original


def test_legacy_scalar_army_is_preserved_on_hexfirst_migration(tmp_path):
    payload = json.loads(DEMO.read_text(encoding="utf-8"))
    payload["countries"]["A"]["army_strength"] = 5
    path = tmp_path / "legacy-army.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    state = GameState.load(path)
    assert state.countries["A"].army_strength == 5
    assert state.countries["A"].army_units == {"MILITIA": 5}


def test_hexfirst_lakes_are_water_and_initial_roads_price_marches(integrated):
    state = integrated.state
    model = integrated.engine.military.movement()
    for coord, tile in state.world.tiles.items():
        if tile.get("lake"):
            assert model.cost(coord) is None
    road = state.world.road_cells()[0]["tile"]
    assert model.cost((road["col"], road["row"])) == state.config["movement"]["road_cost"]


def test_shared_map_projection_preserves_hexfirst_water_and_rendering(integrated):
    world = integrated.state.world.data
    payload = project_world(world)
    assert payload["metadata"]["terrain_mode"] == "hex_fill"
    assert payload["metadata"]["terrain_texture_url"] is None
    assert payload["lake_cells"] == world["lake_cells"]
    assert payload["world_summary"] == world["world_summary"]
    assert sum(row[11] for row in payload["tiles"]) == len(world["lake_cells"])


def test_server_opens_bundled_save_with_military_and_water_snapshot(monkeypatch, tmp_path):
    import live_server
    monkeypatch.setattr(live_server, "SAVE_DIR", tmp_path)
    session = LiveSession(paused=True, load_path=DEMO)
    try:
        snapshot = session.snapshot()
        assert snapshot["day"] == 0
        assert len(snapshot["countries"]) == 4
        assert len(snapshot["unit_specs"]) == 6
        assert snapshot["road_connection_level"] == 3
        assert session.world_payload()["metadata"]["terrain_mode"] == "hex_fill"
    finally:
        session.stop()


def test_foreign_built_road_obeys_diplomacy_at_action_boundary(engine):
    state = engine.state
    left, right = state.countries["ELAR"], state.countries["MARIS"]
    owned = {coord for country in state.countries.values() for coord in country.tiles}
    target, foreign = next(
        (coord, neighbor)
        for coord in left.tiles if coord not in left.buildings
        and state.world.tile(coord)["biome"] in state.config["buildings"]["ROAD"]["allowed_biomes"]
        for neighbor in state.world.neighbors(*coord)
        if neighbor not in owned and state.world.tile(neighbor)["land"]
    )
    right.tiles.append(foreign)
    right.buildings[foreign] = "ROAD"
    action = {"type": "BUILD", "building": "ROAD", "tile": {"col": target[0], "row": target[1]}}
    money, projects = left.treasury, list(left.projects)
    refused = engine.apply_action(left.country_id, action)
    assert not refused.accepted and refused.reason_code == "ROAD_DIPLOMACY_REQUIRED"
    assert left.treasury == money and left.projects == projects
    state.relations[relation_key(left.country_id, right.country_id)] = 30
    assert engine.apply_action(left.country_id, action).accepted


def test_initial_road_gate_follows_conquest_and_forgets_eliminated_sponsor(engine):
    state = engine.state
    left = state.countries["ELAR"]
    target = left.cities[0].center
    road = next(iter(state.world.neighbors(*target)))
    state.world.data["road_cells"] = [{"tile": {"col": road[0], "row": road[1]}, "owner_id": "MARIS"}]
    # This road belonged to MARIS at generation time; its ground is now ELAR's.
    if road not in left.tiles:
        left.tiles.append(road)
    assert road_node_owners(state, left, target) == {"ELAR"}
    left.tiles.remove(road)
    del state.countries["MARIS"]
    assert road_node_owners(state, left, target) == {"ELAR"}


def test_hexfirst_march_quote_matches_arrival_and_survives_reload(integrated, tmp_path):
    state, military = integrated.state, integrated.engine.military
    country = state.countries["A"]
    army = country.new_army(tile=country.cities[0].center, units={"MILITIA": 4})
    model = military.movement("A")
    costs, previous = model.search(army.tile)
    owners = military._owners()
    target = next(coord for coord, cost in sorted(costs.items(), key=lambda x: -x[1])
                  if cost > 6 and owners.get(coord) in (None, "A"))
    quote = military.tile_strikes("A", target)["march"]
    row = next(item for item in quote["rows"] if item["army_id"] == army.army_id)
    order = integrated.engine.apply_action("A", {"type": "MILITARY", "operation": "MARCH",
        "army_id": army.army_id, "tile": {"col": target[0], "row": target[1]}})
    assert order.accepted
    integrated.step(1)
    path = state.save(tmp_path / "march.json")
    restored = Simulation.load(path, use_mock_agents=False)
    restored.step(row["days"] - 1)
    arrived = next(a for a in restored.state.countries["A"].armies if a.army_id == army.army_id)
    assert arrived.tile == target and arrived.march is None


def test_hexfirst_siege_annexation_and_save_round_trip(integrated, tmp_path):
    state = integrated.state
    engine = RuleEngine(state, planner=None, enable_city_manager=False, enable_frontier_ai=False)
    attacker, defender = state.countries["A"], state.countries["B"]
    city = defender.cities[0]
    ring = next(coord for coord in state.world.neighbors(*city.center) if state.world.tile(coord)["land"])
    attacker.armies = []
    defender.armies = []
    army = attacker.new_army(tile=ring, units={"MILITIA": 8})
    assert engine.apply_action("A", {"type": "DIPLOMACY", "operation": "DECLARE_WAR", "target": "B"}).accepted
    result = engine.apply_action("A", {"type": "MILITARY", "operation": "ATTACK", "target": "B",
        "army_id": army.army_id, "tile": {"col": city.center[0], "row": city.center[1]}})
    assert result.accepted
    days = result.effects["siege"]["days_left"]
    for _ in range(days):
        engine.step_day(force=True)
    assert "B" not in state.countries and "B" in state.eliminated
    assert city in attacker.cities
    assert sum(c.population for c in attacker.cities) == attacker.population
    assert GameState.load(state.save(tmp_path / "conquered.json")).fingerprint() == state.fingerprint()
    assert project_world(state.world.data)["lake_cells"]
