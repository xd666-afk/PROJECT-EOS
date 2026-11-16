from mapgen import CORE_TILES, generate_fair_world
from worldgen import validate


def test_custom_fair_world_has_equal_connected_cores_and_metadata(tmp_path):
    countries = [
        {"name": "赤河国", "color": "#cc5544", "archetype": "river_valley", "population": 30000},
        {"name": "蓝港国", "color": "#4488cc", "archetype": "maritime", "population": 24000},
        {"name": "云山国", "color": "#88aa66", "archetype": "highland", "population": 18000},
        {"name": "沙丘国", "color": "#ccaa55", "archetype": "semiarid", "population": 26000},
    ]
    world, path = generate_fair_world(countries, base_seed=32100, attempts=1, output_dir=tmp_path)
    assert path.exists()
    assert validate(world)
    assert all(len(p["initial_tiles"]) == CORE_TILES for p in world["polities"])
    assert [p["name"] for p in world["polities"]] == [c["name"] for c in countries]
    assert len({p["color"] for p in world["polities"]}) == 4
    fairness = world["metadata"]["fairness"]
    assert fairness["equal_core_tiles"] is True
    assert 0 <= fairness["score"] <= 1
    assert fairness["score"] >= 0.5


def test_six_country_world_and_engine_are_dynamic(tmp_path):
    countries = [
        {"name": "甲国", "color": "#cc5544", "archetype": "river_valley", "population": 30000},
        {"name": "乙国", "color": "#4488cc", "archetype": "maritime", "population": 24000},
        {"name": "丙国", "color": "#88aa66", "archetype": "highland", "population": 18000},
        {"name": "丁国", "color": "#ccaa55", "archetype": "semiarid", "population": 26000},
        {"name": "戊国", "color": "#aa66cc", "archetype": "river_valley", "population": 22000},
        {"name": "己国", "color": "#66ccaa", "archetype": "maritime", "population": 20000},
    ]
    world, path = generate_fair_world(countries, base_seed=44100, attempts=2, output_dir=tmp_path)
    assert len(world["polities"]) == 6
    assert [p["id"] for p in world["polities"]] == ["A", "B", "C", "D", "E", "F"]
    assert all(len(p["initial_tiles"]) == CORE_TILES for p in world["polities"])
    assert set(world["metadata"]["fairness"]["countries"]) == {
        "A", "B", "C", "D", "E", "F"
    }

    from core.state import GameState
    state = GameState.new(world_path=path, seed=world["metadata"]["seed"])
    assert set(state.countries) == {"A", "B", "C", "D", "E", "F"}
    assert len(state.summary()["countries"]) == 6
    from agents.heuristic import HeuristicAgent
    assert HeuristicAgent("E").preference["policy"] in {
        "AGRICULTURE", "TRADE", "INDUSTRY", "BALANCED"
    }
