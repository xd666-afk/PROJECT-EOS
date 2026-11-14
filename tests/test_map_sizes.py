"""Actual grid sizes, independent world files, and simulation/save compatibility."""
from copy import deepcopy
import hashlib

import numpy as np
import pytest

from core.simulation import Simulation
from core.state import GameState
from map_sizes import DEFAULT_MAP_SIZE, MAP_SIZES, map_size_spec
from mapgen import CORE_TILES, DEFAULT_COUNTRIES, generate_fair_world
from mapgen_v2 import validate_v2
from worldgen import gen_hydrology, neighbors


@pytest.fixture(scope="module")
def sized_worlds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("world-sizes")
    worlds, hashes = {}, {}
    for size in MAP_SIZES:
        world, path = generate_fair_world(base_seed=50002, attempts=1,
                                         generation_version="v3", map_size=size, output_dir=directory)
        worlds[size] = world, path
        for existing, digest in hashes.items():
            assert hashlib.sha256(existing.read_bytes()).digest() == digest
        hashes[path] = hashlib.sha256(path.read_bytes()).digest()
    assert len(hashes) == 3
    return worlds


@pytest.mark.parametrize("size,width,height", [("small", 72, 54), ("medium", 108, 81), ("large", 144, 108)])
def test_each_size_builds_a_real_grid_with_valid_water_and_territories(sized_worlds, size, width, height):
    world, path = sized_worlds[size]
    metadata = world["metadata"]
    assert metadata["map_size"] == size
    assert (metadata["grid_width"], metadata["grid_height"]) == (width, height)
    assert len(world["tiles"]) == width * height
    from live_server import project_world
    public = project_world(world)
    assert public["metadata"]["map_size"] == size
    assert len(public["tiles"]) == width * height
    assert (world["terrain"]["width"], world["terrain"]["height"]) == (width, height)
    assert path.name.endswith(f"_{size}.json")
    assert validate_v2(world)
    claimed = [tuple(p) for country in world["polities"] for p in country["initial_tiles"]]
    assert len(claimed) == len(set(claimed)) == len(world["polities"]) * CORE_TILES
    by_coord = {(t["col"], t["row"]): t for t in world["tiles"]}
    for country in world["polities"]:
        capital = country["capital"]["col"], country["capital"]["row"]
        assert by_coord[capital]["land"] and not by_coord[capital]["river"]
        assert len(country["initial_tiles"]) == CORE_TILES
        todo, reached = [capital], {capital}
        core = set(map(tuple, country["initial_tiles"]))
        while todo:
            for n in neighbors(*todo.pop(), width, height):
                if n in core and n not in reached:
                    reached.add(n)
                    todo.append(n)
        assert reached == core


@pytest.mark.parametrize("size", MAP_SIZES)
def test_simulation_weather_and_saved_size_survive_roundtrip(sized_worlds, size, tmp_path):
    world, path = sized_worlds[size]
    simulation = Simulation.new(world_path=path, seed=world["metadata"]["seed"], use_mock_agents=False)
    assert simulation.run(31) == 31
    state = simulation.state
    assert state.weather.anomaly.shape == (MAP_SIZES[size]["height"], MAP_SIZES[size]["width"])
    saved = tmp_path / f"{size}.json"
    state.save(saved)
    restored = GameState.load(saved)
    assert restored.fingerprint() == state.fingerprint()
    assert restored.world.data["metadata"]["map_size"] == size


def test_v3_default_is_small_and_repeatable(sized_worlds, tmp_path):
    assert DEFAULT_MAP_SIZE == "small"
    default, _ = generate_fair_world(base_seed=50002, attempts=1, generation_version="v3", output_dir=tmp_path)
    assert default == sized_worlds["small"][0]


@pytest.mark.parametrize("invalid", ["tiny", "", None, True, {}, []])
def test_invalid_size_is_rejected_before_writing_anything(invalid, tmp_path):
    with pytest.raises(ValueError, match="尺寸"):
        map_size_spec(invalid)
    assert not list(tmp_path.iterdir())


def test_small_map_can_host_twelve_countries_with_equal_cores(tmp_path):
    countries = []
    for i in range(12):
        country = deepcopy(DEFAULT_COUNTRIES[i % len(DEFAULT_COUNTRIES)])
        country.update(name=f"国家{i+1}", color=f"#{i+1:06x}")
        countries.append(country)
    world, _ = generate_fair_world(countries, base_seed=50002, attempts=3,
                                  generation_version="v3", map_size="small", output_dir=tmp_path)
    assert len(world["polities"]) == 12
    assert all(len(p["initial_tiles"]) == CORE_TILES for p in world["polities"])
    assert validate_v2(world)


def test_hydrology_uses_the_requested_dimensions_at_all_edges():
    width, height = 9, 7
    land = np.ones((height, width), dtype=bool)
    land[0, :] = land[-1, :] = False
    land[:, 0] = land[:, -1] = False
    elevation = np.where(land, 100.0, -1.0)
    rain = np.full((height, width), 600.0)
    parent, _, _, _, slope = gen_hydrology(land, elevation, rain, width, height)
    assert parent.shape == (height, width, 2)
    assert np.all(parent[land, 0] >= 0) and np.all(parent[land, 1] >= 0)
    assert slope[height-2, width-2] > 0


def test_unknown_size_does_not_generate_or_write_a_world(tmp_path):
    with pytest.raises(ValueError, match="尺寸"):
        generate_fair_world(generation_version="v3", map_size="huge", output_dir=tmp_path)
    assert not list(tmp_path.iterdir())
