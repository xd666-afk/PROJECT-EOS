from pathlib import Path

from core.state import GameState, relation_key
from core.simulation import Simulation
from mapgen import generate_fair_world
from mapgen_v2 import V2_HEIGHT, V2_WIDTH, validate_v2

COUNTRIES = [
    {"name": "赤河国", "color": "#cc5544", "archetype": "river_valley", "population": 30000},
    {"name": "蓝港国", "color": "#4488cc", "archetype": "maritime", "population": 24000},
    {"name": "云山国", "color": "#88aa66", "archetype": "highland", "population": 18000},
    {"name": "沙丘国", "color": "#ccaa55", "archetype": "semiarid", "population": 26000},
]


def test_v3_hex_first_world_has_clean_tile_terrain(tmp_path):
    world, world_path = generate_fair_world(
        COUNTRIES, base_seed=50002, attempts=1, generation_version="v3", output_dir=tmp_path
    )
    assert world_path.parent == tmp_path
    assert validate_v2(world)
    metadata = world["metadata"]
    assert metadata["schema_version"] == 3
    assert metadata["generator"] == "mapgen_v3_hexfirst"
    assert metadata["terrain_mode"] == "hex_fill"
    assert "terrain_texture" not in metadata
    assert metadata["grid_width"] == V2_WIDTH
    assert metadata["grid_height"] == V2_HEIGHT
    assert len(world["tiles"]) == V2_WIDTH * V2_HEIGHT
    assert world["terrain"]["kind"] == "hex_fill"
    assert world["terrain"]["width"] == V2_WIDTH
    assert "elevation_m" not in world["terrain"]
    assert len(world["river_cells"]) > 100
    assert len(world["road_cells"]) > 20
    by_coord = {(t["col"], t["row"]): t for t in world["tiles"]}
    from core.road import river_width
    from types import SimpleNamespace
    road_world = SimpleNamespace(tiles=by_coord)
    for cell in world["road_cells"]:
        coord = cell["tile"]["col"], cell["tile"]["row"]
        tile = by_coord[coord]
        assert tile["biome"] not in {"alpine", "tundra", "desert"}
        if tile["river"]:
            assert 1 <= river_width(road_world, coord) <= 2
    assert world["lake_cells"]
    assert all(cell["depth_m"] > 0 for cell in world["river_cells"])
    assert all(
        not next(
            tile for tile in world["tiles"]
            if tile["col"] == polity["capital"]["col"]
            and tile["row"] == polity["capital"]["row"]
        )["river"]
        for polity in world["polities"]
    )
    state = GameState.new(world_path=world_path, seed=metadata["seed"])
    assert state.diplomatic_level("A", "B") == 2
    state.relations[relation_key("A", "B")] = 25
    assert state.diplomatic_level("A", "B") == 3
    state.countries["A"].at_war_with.append("B")
    assert state.diplomatic_level("A", "B") == 0
    state.countries["A"].at_war_with.remove("B")
    assert state.road_connection_level() == 3
    country = state.countries[next(iter(state.countries))]
    initial_roads = {
        (int(cell["tile"]["col"]), int(cell["tile"]["row"]))
        for cell in state.world.road_cells()
    }
    assert initial_roads
    nodes = state.world.road_nodes(country)
    assert country.cities[0].center in nodes
    assert initial_roads <= nodes
    assert state.world.is_road_cell(next(iter(initial_roads)))
    save_path = tmp_path / "v3_save.json"
    state.save(save_path)
    restored = GameState.load(save_path)
    assert restored.fingerprint() == state.fingerprint()

    simulation = Simulation.load(save_path)
    live = simulation.state
    road_country = next(
        entity for entity in live.countries.values()
        if any(live.world.is_road_cell(coord) for coord in entity.tiles)
    )
    road_coord = next(
        coord for coord in road_country.tiles if live.world.is_road_cell(coord)
    )
    rejected = simulation.engine.apply_action(
        road_country.country_id,
        {"type": "BUILD", "tile": {"col": road_coord[0], "row": road_coord[1]}, "building": "FARM"},
    )
    assert rejected.accepted
    assert live.world.is_road_cell(road_coord)
    assert any(tuple(p["tile"]) == road_coord and p["building"] == "FARM" for p in road_country.projects)


def test_v3_no_continuous_texture_is_requested_by_the_dashboard():
    source = (Path(__file__).resolve().parents[1] / "dashboard.html").read_text(encoding="utf-8")
    assert "terrain_mode==='hex_fill'" in source
    assert "satelliteColor" in source
    assert "waterColor" in source
    assert "coastal" in source
