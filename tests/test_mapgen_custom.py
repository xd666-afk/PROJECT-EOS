"""Hand-drawn maps: draft validation, derived worlds, and the live march timing the painter shows.

The painter promises one number: the days it prints while hovering are the days the engine
will spend once the map is in play. Every pricing test here compares `march_preview` against
the engine's own `Movement`, so a change to the cost table cannot silently desync the two.
"""
import json
import math

import pytest

import mapgen_custom
import worldgen
from core.simulation import Simulation
from mapgen_custom import (
    DRAFT_HEIGHT, DRAFT_WIDTH, build_world_from_draft, draft_report, march_preview,
    normalize_draft, write_draft_world,
)
from worldgen import hex_distance

RULES = json.loads((mapgen_custom.BASE_DIR / "config" / "rules.json").read_text(encoding="utf-8"))


def blank(char="g"):
    return [char * DRAFT_WIDTH for _ in range(DRAFT_HEIGHT)]


def landmass(char="g", rim=2):
    """Land with an ocean rim: the sea every drawn river has to drain into."""
    grid = []
    for row in range(DRAFT_HEIGHT):
        line = []
        for col in range(DRAFT_WIDTH):
            edge = min(col, row, DRAFT_WIDTH - 1 - col, DRAFT_HEIGHT - 1 - row)
            line.append(char if edge >= rim else "o")
        grid.append("".join(line))
    return grid


LAND_TILES = (DRAFT_WIDTH - 4) * (DRAFT_HEIGHT - 4)


def draft(grid=None, rivers=(), roads=(), polities=None, **extra):
    payload = {
        "grid": grid if grid is not None else landmass(),
        "rivers": [list(coord) for coord in rivers],
        "roads": [list(coord) for coord in roads],
        "polities": polities if polities is not None else [
            {"name": "甲国", "color": "#cc5544", "archetype": "river_valley",
             "population": 30000, "capital": [8, 20]},
            {"name": "乙国", "color": "#4488cc", "archetype": "maritime",
             "population": 24000, "capital": [58, 30]},
        ],
        "seed": 4242,
        "name": "测试图",
    }
    payload.update(extra)
    return payload


def two_islands():
    """Left and right landmasses separated by a full-height ocean column."""
    grid = []
    for row in range(DRAFT_HEIGHT):
        line = []
        for col in range(DRAFT_WIDTH):
            if col == 36:
                line.append("o")
            elif col < 36:
                line.append("g")
            else:
                line.append("t")
        grid.append("".join(line))
    return grid


def islands(*blobs):
    """Sea with grassland rectangles, so a capital can be starved of core tiles."""
    grid = blank("o")
    for col0, row0, col1, row1 in blobs:
        for row in range(row0, row1):
            line = grid[row]
            for col in range(col0, col1):
                line = line[:col] + "g" + line[col + 1:]
            grid[row] = line
    return grid


def paint_ocean(payload, col, row):
    line = payload["grid"][row]
    payload["grid"][row] = line[:col] + "o" + line[col + 1:]


def march_days(payload, start, target, cap=None):
    """The engine's own routing model over the same drafted tiles."""
    drafted = normalize_draft(payload)
    if cap is None:
        config = RULES
    else:
        config = {**RULES, "movement": {**RULES["movement"], "maximum_order_cost": cap}}
    return mapgen_custom.movement(drafted, config).plan(tuple(start), tuple(target))


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p.update(grid=blank()[:40]), "地图高度固定"),
    (lambda p: p.update(grid=[line[:-1] for line in blank()]), "应为"),
    (lambda p: p.update(grid=[line.replace("g", "z", 1) for line in blank()]), "未知地形字符"),
    (lambda p: p.update(grid=blank("o")), "全海地图"),
    (lambda p: (paint_ocean(p, 36, 10), p.update(rivers=[[36, 10]])), "河流只能画在陆地上"),
    (lambda p: (paint_ocean(p, 36, 10), p.update(roads=[[36, 10]])), "道路只能画在陆地上"),
    (lambda p: p.update(polities=[]), "标出至少一个国家"),
    (lambda p: p.update(polities=[p["polities"][0]]), "2-12"),
    (lambda p: p["polities"][1].update(capital=[8, 20]), "都城与其他国家重叠"),
    (lambda p: p["polities"][1].update(capital=[9, 20]), "至少相隔"),
    (lambda p: (paint_ocean(p, 36, 10), p["polities"][1].update(capital=[36, 10])),
     "都城必须位于陆地"),
    (lambda p: p["polities"][0].update(color="#cc5545cc"), "#RRGGBB"),
    (lambda p: p["polities"][0].update(archetype="sky_dwellers"), "archetype"),
    (lambda p: p["polities"][0].update(population=7000), "starting population"),
])
def test_draft_rejects_unpaintable_input(mutate, needle):
    payload = draft()
    mutate(payload)
    with pytest.raises(ValueError) as error:
        normalize_draft(payload)
    assert needle in str(error.value)


def test_capital_out_of_range_is_reported_with_coordinates():
    payload = draft()
    payload["polities"][0]["capital"] = [DRAFT_WIDTH, 3]
    with pytest.raises(ValueError, match="超出地图范围"):
        normalize_draft(payload)


def test_normalize_expands_grid_into_tile_table():
    drafted = normalize_draft(draft(rivers=[[8, 20]], roads=[[8, 21]]))
    assert drafted["width"] == DRAFT_WIDTH and drafted["height"] == DRAFT_HEIGHT
    assert len(drafted["tiles"]) == DRAFT_WIDTH * DRAFT_HEIGHT
    assert drafted["tiles"][(8, 20)] == {"biome": "grassland", "land": True,
                                         "river": True, "road": False}
    assert drafted["tiles"][(8, 21)]["road"] is True
    assert drafted["capitals"] == [(8, 20), (58, 30)]


def test_land_without_any_sea_cannot_drain():
    with pytest.raises(ValueError, match="入海口"):
        normalize_draft(draft(grid=blank()))


# ---------------------------------------------------------------- world building

def test_draft_becomes_a_valid_world_document():
    world = build_world_from_draft(draft(rivers=[[8, 20], [9, 20]]))
    worldgen.validate(world)
    metadata = world["metadata"]
    assert metadata["generator"] == "mapgen_custom"
    assert metadata["fairness"]["mode"] == "hand_drawn"
    assert len(world["tiles"]) == DRAFT_WIDTH * DRAFT_HEIGHT
    assert [tile["row"] for tile in world["tiles"][:DRAFT_WIDTH]] == [0] * DRAFT_WIDTH
    assert world["rendering"]["river_depth_stops"], "renderer needs depth stops"
    assert len(world["polities"]) == 2
    assert all(len(polity["initial_tiles"]) == mapgen_custom.mapgen.CORE_TILES
               for polity in world["polities"])


def test_same_draft_and_seed_rebuild_identically():
    payload = draft(rivers=[[8, 20], [9, 21]], roads=[[58, 30]])
    first = build_world_from_draft(payload, seed=777)
    second = build_world_from_draft(payload, seed=777)
    assert first["metadata"]["draft_digest"] == second["metadata"]["draft_digest"]
    assert json.dumps(first["tiles"]) == json.dumps(second["tiles"])
    assert json.dumps(first["polities"]) == json.dumps(second["polities"])


def test_different_drafts_get_different_digests():
    left = build_world_from_draft(draft(), seed=777)
    right = build_world_from_draft(draft(roads=[[10, 10]]), seed=777)
    assert left["metadata"]["draft_digest"] != right["metadata"]["draft_digest"]


def test_capital_on_a_small_island_cannot_open():
    payload = draft(grid=islands((10, 10, 13, 13), (40, 20, 60, 40)), polities=[
        {"name": "礁国", "color": "#cc5544", "archetype": "river_valley",
         "population": 30000, "capital": [11, 11]},
        {"name": "陆国", "color": "#4488cc", "archetype": "maritime",
         "population": 24000, "capital": [50, 30]},
    ])
    with pytest.raises(ValueError, match="连通陆地"):
        build_world_from_draft(payload)


def test_draft_world_runs_in_the_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen_custom, "BASE_DIR", tmp_path)
    world = build_world_from_draft(draft(rivers=[[8, 20]]), seed=2024)
    path = write_draft_world(world)
    assert path.name.startswith("world_draft_2024_")
    simulation = Simulation.new(world_path=path, seed=2024)
    simulation.step(20)
    state = simulation.state
    assert state.day_index == 20
    assert set(state.countries) == {"A", "B"}
    assert all(country.armies for country in state.countries.values())


def test_fragmented_map_still_opens_and_steps(tmp_path, monkeypatch):
    """Two islands: every country can start, but no army can cross the water."""
    monkeypatch.setattr(mapgen_custom, "BASE_DIR", tmp_path)
    payload = draft(grid=two_islands(), polities=[
        {"name": "西国", "color": "#cc5544", "archetype": "river_valley",
         "population": 30000, "capital": [8, 20]},
        {"name": "东国", "color": "#4488cc", "archetype": "highland",
         "population": 24000, "capital": [58, 30]},
    ])
    world = build_world_from_draft(payload, seed=31337)
    path = write_draft_world(world)
    simulation = Simulation.new(world_path=path, seed=31337)
    simulation.step(30)
    assert simulation.state.day_index == 30
    preview = march_preview(payload, RULES, [8, 20], [58, 30])
    assert preview["ok"] is False
    assert "没有连通陆路" in preview["reason"]


# ---------------------------------------------------------------- live timing

@pytest.mark.parametrize("start,target", [
    ([8, 20], [20, 20]),
    ([8, 20], [18, 28]),
    ([58, 30], [50, 24]),
    ([30, 45], [42, 45]),
])
def test_preview_days_equal_engine_days(start, target):
    payload = draft()
    preview = march_preview(payload, RULES, start, target)
    plan = march_days(payload, start, target)
    assert plan["cost"] <= RULES["movement"]["maximum_order_cost"]
    assert preview["ok"] is True
    assert preview["single_order"] is True
    assert preview["cost"] == plan["cost"]
    assert preview["days"] == plan["days"]
    assert preview["route"] == [list(coord) for coord in plan["route"]]


def test_road_speeds_the_march_the_painter_sees():
    payload = draft()
    plain = march_preview(payload, RULES, [8, 20], [40, 20])
    paved = march_preview(draft(roads=[[col, 20] for col in range(9, 40)]),
                          RULES, [8, 20], [40, 20])
    assert paved["days"] < plain["days"]
    assert paved["road_share"] > 0.9
    assert plain["road_share"] == 0


def test_slow_terrain_costs_more_days_than_grass():
    bog = draft(grid=[line.replace("g", "j") for line in landmass()])
    open_land = draft()
    start, target = [8, 20], [40, 20]
    assert march_preview(bog, RULES, start, target)["days"] > \
        march_preview(open_land, RULES, start, target)["days"]


def test_long_route_reports_segments_instead_of_unreachable():
    payload = draft()
    preview = march_preview(payload, RULES, [2, 2], [68, 50])
    cap = RULES["movement"]["maximum_order_cost"]
    plan = march_days(payload, [2, 2], [68, 50], cap=cap * 100)
    assert march_days(payload, [2, 2], [68, 50]) is None
    assert preview["ok"] is True
    assert preview["single_order"] is False
    assert preview["cost"] == plan["cost"]
    assert preview["days"] == plan["days"]
    assert preview["segments"] == math.ceil(preview["cost"] / cap)
    assert "段下令" in preview["hint"]


def test_same_tile_march_costs_nothing():
    preview = march_preview(draft(), RULES, [8, 20], [8, 20])
    assert preview == {**preview, "ok": True, "days": 0, "cost": 0.0,
                       "single_order": True, "route": [[8, 20]]}


@pytest.mark.parametrize("start,target,side", [
    ([36, 10], [40, 10], "起点"),
    ([40, 10], [36, 10], "终点"),
])
def test_ocean_endpoint_is_refused_not_crashed(start, target, side):
    preview = march_preview(draft(grid=two_islands()), RULES, start, target)
    assert preview["ok"] is False
    assert preview["days"] is None
    assert side in preview["reason"]


def test_preview_reports_crossed_territory_and_terrain_mix():
    payload = draft(grid=landmass(), polities=[
        {"name": "西国", "color": "#cc5544", "archetype": "river_valley",
         "population": 30000, "capital": [8, 20]},
        {"name": "东国", "color": "#4488cc", "archetype": "highland",
         "population": 24000, "capital": [58, 20]},
    ])
    preview = march_preview(payload, RULES, [8, 20], [58, 20])
    assert preview["terrain_mix"], preview
    assert sum(preview["terrain_mix"].values()) == preview["steps"]
    assert {item["country_id"] for item in preview["crossings"]} <= {"A", "B"}
    assert preview["from_info"]["biome"] == "grassland"
    assert preview["straight_km"] == pytest.approx(
        preview["hex_distance"] * worldgen.R_KM * math.sqrt(3.0), abs=0.2)


def test_preview_names_the_biomes_it_walks_over():
    grid = landmass()
    for row in range(DRAFT_HEIGHT):
        line = grid[row]
        for col in range(30, 45):
            if line[col] == "g":
                line = line[:col] + "j" + line[col + 1:]
        grid[row] = line
    preview = march_preview(draft(grid=grid), RULES, [8, 20], [58, 20])
    assert preview["terrain_mix"]["雨林"] >= 1
    assert preview["from_info"]["biome_label"] == "草原"
    assert preview["to_info"]["biome_label"] == "草原"


# ---------------------------------------------------------------- report panel

def test_report_counts_land_and_flags_thin_countries():
    report = draft_report(draft(rivers=[[8, 20]], roads=[[9, 21]]))
    assert report["ok"] is True
    assert report["land_tiles"] == LAND_TILES
    assert report["ocean_tiles"] == DRAFT_WIDTH * DRAFT_HEIGHT - LAND_TILES
    assert report["river_tiles"] == 1 and report["road_tiles"] == 1
    assert report["biomes"]["草原"] == report["land_tiles"]
    assert [country["core_tiles"] for country in report["countries"]] == [16, 16]
    assert report["warnings"] == []


def test_report_warns_when_a_capital_sits_on_a_pocket_of_land():
    payload = draft(grid=islands((10, 30, 13, 33), (40, 10, 60, 30)), polities=[
        {"name": "礁国", "color": "#cc5544", "archetype": "river_valley",
         "population": 30000, "capital": [11, 31]},
        {"name": "陆国", "color": "#4488cc", "archetype": "maritime",
         "population": 24000, "capital": [50, 20]},
    ])
    report = draft_report(payload)
    assert report["ok"] is False
    thin = [country for country in report["countries"] if not country["openable"]]
    assert thin and thin[0]["core_tiles"] < 16
    assert any("连通陆地" in warning for warning in report["warnings"])


def test_report_digest_matches_world_digest():
    payload = draft(roads=[[10, 10]])
    assert draft_report(payload)["digest"] == build_world_from_draft(payload)["metadata"]["draft_digest"]


def test_painted_days_survive_into_the_running_engine(tmp_path, monkeypatch):
    """The number the painter prints is the number the settlement will spend.

    Draft tiles and the built world are two different tables, so this is the seam where a
    cost model could silently drift: same route, same road network, same daily budget.
    """
    monkeypatch.setattr(mapgen_custom, "BASE_DIR", tmp_path)
    payload = draft(rivers=[[8, 20], [9, 20], [10, 20]],
                   roads=[[col, 20] for col in range(9, 40)])
    preview = march_preview(payload, RULES, [8, 20], [40, 20])
    world = build_world_from_draft(payload, seed=90210)
    simulation = Simulation.new(world_path=write_draft_world(world), seed=90210)
    live = simulation.engine.military.movement().plan((8, 20), (40, 20))
    assert preview["cost"] == live["cost"]
    assert preview["days"] == live["days"]
    assert preview["route"] == [list(coord) for coord in live["route"]]


def test_painted_roads_are_reachable_by_the_engine_that_builds_them(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen_custom, "BASE_DIR", tmp_path)
    payload = draft()
    paved = march_preview(draft(roads=[[col, 20] for col in range(9, 40)]),
                          RULES, [8, 20], [40, 20])
    plain = march_preview(payload, RULES, [8, 20], [40, 20])
    world = build_world_from_draft(draft(roads=[[col, 20] for col in range(9, 40)]), seed=5150)
    simulation = Simulation.new(world_path=write_draft_world(world), seed=5150)
    assert len(simulation.state.world.data["road_cells"]) == 31
    assert paved["days"] < plain["days"]
