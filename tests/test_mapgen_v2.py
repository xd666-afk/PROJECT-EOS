from pathlib import Path

import numpy as np
from PIL import Image

from core.state import GameState
from mapgen import generate_fair_world
from mapgen_v2 import V2_HEIGHT, V2_WIDTH, _meander_reach, validate_v2
from worldgen import hex_distance

COUNTRIES = [
    {"name": "赤河国", "color": "#cc5544", "archetype": "river_valley", "population": 30000},
    {"name": "蓝港国", "color": "#4488cc", "archetype": "maritime", "population": 24000},
    {"name": "云山国", "color": "#88aa66", "archetype": "highland", "population": 18000},
    {"name": "沙丘国", "color": "#ccaa55", "archetype": "semiarid", "population": 26000},
]


def test_v2_world_has_continuous_terrain_and_cell_entities(tmp_path):
    world, world_path = generate_fair_world(
        COUNTRIES, base_seed=32100, attempts=1, generation_version="v2"
    )
    assert validate_v2(world)
    assert world["metadata"]["schema_version"] == 2
    assert world["metadata"]["generator"] == "mapgen_v2"
    assert world["metadata"]["grid_width"] == V2_WIDTH
    assert world["metadata"]["grid_height"] == V2_HEIGHT
    assert len(world["tiles"]) == V2_WIDTH * V2_HEIGHT
    assert world["terrain"]["width"] > V2_WIDTH
    assert world["terrain"]["height"] > V2_HEIGHT
    assert len(world["river_cells"]) > 100
    assert len(world["road_cells"]) > 20
    assert world["world_summary"]["river_hexes"] == len(world["river_cells"])
    assert world["world_summary"]["river_cell_count"] == len(world["river_cells"])
    assert world["lake_cells"], "v2 should contain inland lakes"
    assert world["world_summary"]["lake_hexes"] == len(world["lake_cells"])
    assert world["world_summary"]["lake_count"] == len({
        cell["lake_id"] for cell in world["lake_cells"]
    })
    assert world["world_summary"]["endorheic_river_hexes"] > 0
    assert any(cell["kind"] == "endorheic" for cell in world["river_cells"])
    terminal_ids = {cell["lake_id"] for cell in world["lake_cells"]}
    assert all(
        cell["terminal_lake_id"] in terminal_ids
        for cell in world["river_cells"]
        if cell["kind"] == "endorheic"
    )
    assert all(
        not next(
            tile for tile in world["tiles"]
            if tile["col"] == polity["capital"]["col"]
            and tile["row"] == polity["capital"]["row"]
        )["river"]
        for polity in world["polities"]
    )
    assert all(cell["depth_m"] > 0 for cell in world["river_cells"])
    assert {cell["kind"] for cell in world["road_cells"]} <= {"road", "bridge"}
    assert len({cell["id"] for cell in world["river_cells"]}) == len(world["river_cells"])
    assert len({cell["id"] for cell in world["road_cells"]}) == len(world["road_cells"])

    texture = Path(world["metadata"]["terrain_texture"])
    assert texture.is_file()
    image = Image.open(texture)
    assert image.size == (
        world["terrain"]["width"] * 2,
        world["terrain"]["height"] * 2,
    )

    state = GameState.new(world_path=world_path, seed=world["metadata"]["seed"])
    assert set(state.countries) == {"A", "B", "C", "D"}
    assert state.weather.land.shape == (V2_HEIGHT, V2_WIDTH)
    assert len(list(state.world.neighbors(0, 0))) > 0
    save_path = tmp_path / "v2_save.json"
    state.save(save_path)
    restored = GameState.load(save_path)
    assert restored.fingerprint() == state.fingerprint()
    assert restored.countries["A"].tiles


def test_v2_has_fine_hexes_but_keeps_old_tile_contract():
    world, _ = generate_fair_world(
        COUNTRIES, base_seed=32101, attempts=1, generation_version="v2"
    )
    tile = world["tiles"][0]
    required = {
        "col", "row", "q", "r", "land", "elevation_m", "biome",
        "monthly_temp_c", "monthly_precip_mm", "river", "downstream",
        "hazards", "owner_id",
    }
    assert required <= set(tile)
    assert sum(tile["river"] for tile in world["tiles"]) == len(world["river_cells"])
    assert world["metadata"]["cell_area_km2"] < 1000


def test_meander_reach_bends_a_straight_channel():
    elev = np.full((12, 40), 120.0)
    reach = [(x, 6) for x in range(6, 26)]
    curved = _meander_reach(reach, elev, lambda x, y: True, 2.0, 10.0, 1.1)
    assert curved is not None
    assert curved[0] == reach[0] and curved[-1] == reach[-1]
    assert max(abs(y - 6) for x, y in curved) >= 1
    assert all(hex_distance(a, b) == 1 for a, b in zip(curved, curved[1:]))
    assert len(set(curved)) == len(curved)
