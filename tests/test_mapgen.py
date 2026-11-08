from mapgen import CORE_TILES, generate_fair_world
from worldgen import validate


def test_custom_fair_world_has_equal_connected_cores_and_metadata():
    countries = [
        {"name": "赤河国", "color": "#cc5544", "archetype": "river_valley", "population": 30000},
        {"name": "蓝港国", "color": "#4488cc", "archetype": "maritime", "population": 24000},
        {"name": "云山国", "color": "#88aa66", "archetype": "highland", "population": 18000},
        {"name": "沙丘国", "color": "#ccaa55", "archetype": "semiarid", "population": 26000},
    ]
    world, path = generate_fair_world(countries, base_seed=32100, attempts=1)
    assert path.exists()
    assert validate(world)
    assert all(len(p["initial_tiles"]) == CORE_TILES for p in world["polities"])
    assert [p["name"] for p in world["polities"]] == [c["name"] for c in countries]
    assert len({p["color"] for p in world["polities"]}) == 4
    fairness = world["metadata"]["fairness"]
    assert fairness["equal_core_tiles"] is True
    assert 0 <= fairness["score"] <= 1
    assert fairness["score"] >= 0.5
