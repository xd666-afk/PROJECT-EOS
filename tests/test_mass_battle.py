"""Barracks scale and battle mass: fixed garrisons, open camp counts, converging strikes.

The content question this file pins is `每座兵营招固定的兵，兵营数量不封顶`, and the
tactical question is what those garrisons are worth once they leave their camp. Both are
settlement behaviour, so the tests read the engine's own numbers instead of a parallel
formula: `field_cap` for the ceiling, `_mass` for the weight a battle is fought at.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from agents.heuristic import HeuristicAgent
from agents.personality import PERSONALITIES
from core.content import ContentError, field_cap, validate_content
from core.rules import RuleEngine
from core.state import GameState, MarchOrder
from worldgen import hex_distance

ROOT = Path(__file__).resolve().parents[1]


def recruit(unit_id, strength):
    return {"type": "MILITARY", "operation": "RECRUIT", "unit": unit_id, "strength": strength}


def last_event(state, kind):
    return next(event for event in reversed(state.event_log) if event["type"] == kind)


def engine_of(seed=2000):
    """A bare settlement: no planners, so nothing but these actions touches the state."""
    return RuleEngine(
        GameState.new(seed=seed), planner=None,
        enable_city_manager=False, enable_frontier_ai=False,
    )


def stamp_camps(country, count, skip=None):
    """Mark owned tiles as finished barracks: the ceiling counts what actually stands."""
    avoid = set(skip or ())
    stamped = 0
    for coord in country.tiles:
        if stamped >= count:
            break
        if coord in country.buildings or coord in avoid:
            continue
        country.buildings[coord] = "BARRACKS"
        stamped += 1
    assert stamped == count, f"{country.country_id} holds too few free tiles for {count} camps"
    return stamped


def clear_armies(country):
    country.armies = []
    country.army_serial = 0
    return country


def declare(engine, actor, rival):
    return engine.apply_action(actor, {
        "type": "DIPLOMACY", "operation": "DECLARE_WAR", "target": rival,
    })


def approach(engine, actor, rival):
    """(camp tile, enemy gate) taken from the quote the engine would honour."""
    quote = engine.military.strike_options(actor, [rival])[rival]
    staging = (quote["march_target"]["col"], quote["march_target"]["row"])
    gate = (quote["objective"]["col"], quote["objective"]["row"])
    assert hex_distance(staging, gate) == 1
    return staging, gate


def two_armies_at_home(engine, elar, units=3):
    home = elar.army_position or elar.tiles[0]
    clear_armies(elar)
    first = elar.new_army(tile=home, units={"MILITIA": units})
    second = elar.new_army(tile=home, units={"MILITIA": units})
    return home, first, second


def army_at_home(elar, units=3):
    home = elar.army_position or elar.tiles[0]
    clear_armies(elar)
    return home, elar.new_army(tile=home, units={"MILITIA": units})


# --- the ceiling: one fixed garrison per camp, camps uncapped -------------------------

def test_the_field_ceiling_is_the_camps_a_realm_actually_holds():
    config = engine_of().state.config
    military = config["military"]
    floor = military["maximum_strength"]
    garrison = military["barracks"]["garrison_capacity"]
    assert field_cap([], config) == floor, "no camp yet: the standing army is the floor"
    assert field_cap(["BARRACKS"], config) == floor, "one camp is still below that floor"
    assert field_cap(["BARRACKS"] * 4, config) == 4 * garrison
    assert field_cap(["BARRACKS"] * 9, config) == 9 * garrison, "the ceiling keeps climbing"
    # The rest of the building table is not a troop house.
    assert field_cap(["BARRACKS"] * 4 + ["FARM"] * 6, config) == 4 * garrison


def test_barracks_are_no_longer_a_one_off_building():
    """Five camps on five tiles: nothing caps the count any more, capped types still refuse."""
    engine = engine_of()
    state = engine.state
    elar = state.countries["ELAR"]
    elar.treasury = 10_000.0
    elar.technology = {field: 5 for field in state.config["tech_tree"]}
    assert "max_per_country" not in state.config["buildings"]["BARRACKS"]

    def build(building, coord):
        return engine.apply_action("ELAR", {
            "type": "BUILD", "building": building,
            "tile": {"col": coord[0], "row": coord[1]},
        })

    built = [build("BARRACKS", coord) for coord in elar.tiles[:5]]
    assert all(result.accepted for result in built), [result.reason_code for result in built]
    assert sum(project["building"] == "BARRACKS" for project in elar.projects) == 5

    assert build("WORKSHOP", elar.tiles[5]).accepted
    refused = build("WORKSHOP", elar.tiles[6])
    assert not refused.accepted and refused.reason_code == "BUILDING_UNIQUE_LIMIT"


def test_recruiting_past_the_standing_floor_needs_camps_and_is_then_allowed():
    engine = engine_of()
    state = engine.state
    elar = state.countries["ELAR"]
    elar.treasury = elar.food = 10_000.0
    elar.technology = {field: 5 for field in state.config["tech_tree"]}
    military = state.config["military"]
    garrison = military["barracks"]["garrison_capacity"]
    # The camps go on tiles the army does not stand on: a merged field army is allowed to be
    # bigger than one camp's garrison, which is the whole point of massing several camps.
    army = clear_armies(elar).new_army(tile=elar.tiles[0], units={"MILITIA": 8, "ARCHER": 4})
    assert army.strength == military["maximum_strength"]

    blocked = engine.apply_action("ELAR", recruit("ARCHER", 1))
    assert not blocked.accepted and blocked.reason_code == "ARMY_LIMIT"

    stamp_camps(elar, 4, skip={elar.tiles[0]})
    grown = engine.apply_action("ELAR", recruit("ARCHER", 1))
    assert grown.accepted, grown.reason_code
    assert elar.army_strength == military["maximum_strength"] + 1

    assert engine.apply_action("ELAR", recruit("HEAVY_INFANTRY", 3)).accepted
    assert elar.army_strength == field_cap(elar.buildings.values(), state.config) == 4 * garrison
    full = engine.apply_action("ELAR", recruit("HEAVY_INFANTRY", 1))
    assert not full.accepted and full.reason_code == "ARMY_LIMIT"


def test_camps_train_their_garrisons_and_the_realm_grows_past_the_standing_floor():
    engine = engine_of()
    state = engine.state
    elar = state.countries["ELAR"]
    elar.treasury = elar.food = 100_000.0
    elar.technology = {field: 5 for field in state.config["tech_tree"]}
    military = state.config["military"]
    garrison = military["barracks"]["garrison_capacity"]
    camps = elar.tiles[:4]
    for coord in camps:
        elar.buildings[coord] = "BARRACKS"
    clear_armies(elar)
    armies = [
        elar.new_army(tile=coord, recruiting=True, preferred_unit=unit)
        for coord, unit in zip(camps, ("ARCHER", "HEAVY_INFANTRY", "CHARIOT", "CAVALRY"))
    ]
    for _ in range(400):
        engine.military.barracks_daily()

    assert [army.strength for army in armies] == [garrison] * 4
    assert elar.army_strength == 4 * garrison > military["maximum_strength"]
    # Every camp is full, so the ceiling the settlement now hits is the realm-wide one.
    assert engine.military._raise_block(elar, armies[0], "ARCHER") == "ARMY_LIMIT"


def test_a_camp_that_filled_its_garrison_stops_while_the_realm_still_has_room():
    engine = engine_of()
    state = engine.state
    elar = state.countries["ELAR"]
    elar.treasury = elar.food = 100_000.0
    elar.technology = {field: 5 for field in state.config["tech_tree"]}
    military = state.config["military"]
    garrison = military["barracks"]["garrison_capacity"]
    camps = elar.tiles[:2]
    for coord in camps:
        elar.buildings[coord] = "BARRACKS"
    clear_armies(elar)
    armies = [elar.new_army(tile=coord, recruiting=True, preferred_unit=unit)
              for coord, unit in zip(camps, ("ARCHER", "CAVALRY"))]
    for _ in range(400):
        engine.military.barracks_daily()

    assert [army.strength for army in armies] == [garrison, garrison]
    assert elar.army_strength < military["maximum_strength"], "the realm is not at its ceiling"
    assert engine.military._raise_block(elar, armies[0], "ARCHER") == "GARRISON_LIMIT"
    price = state.config["units"]["ARCHER"]["cost"]["treasury"]
    # A stalled camp keeps the wage it already paid, capped instead of refunded.
    assert armies[0].progress == pytest.approx(price * military["barracks"]["progress_cap_ratio"])


# --- the weight of a battle: only the armies standing around the gate -----------------

def test_mass_is_the_share_of_the_roster_standing_around_the_gate():
    engine = engine_of()
    elar = engine.state.countries["ELAR"]
    declare(engine, "ELAR", "VAYR")
    _home, first, second = two_armies_at_home(engine, elar)
    staging, gate = approach(engine, "ELAR", "VAYR")
    floor = engine.state.config["military"]["minimum_mass_share"]

    present, share = engine.military._mass(elar, gate, first)
    assert [army.army_id for army in present] == [first.army_id]
    assert share == pytest.approx(floor + (1 - floor) * 0.5), "half the roster at one gate"

    first.tile = second.tile = staging
    both, share = engine.military._mass(elar, gate, first)
    assert {army.army_id for army in both} == {first.army_id, second.army_id}
    assert share == pytest.approx(1.0), "the whole roster at one gate fights at full weight"

    second.march = MarchOrder(purpose="MARCH", route=[second.tile, elar.tiles[-1]],
                              cumulative=[0.0, 1.0])
    present, share = engine.military._mass(elar, gate, first)
    assert [army.army_id for army in present] == [first.army_id]
    assert share == pytest.approx(floor + (1 - floor) * 0.5), "an army still marching is not there"

    second.march = None
    second.units = {}
    present, share = engine.military._mass(elar, gate, first)
    assert [army.army_id for army in present] == [first.army_id]
    assert share == pytest.approx(1.0), "a wrecked camp is not in the roster the share measures"


def test_a_side_with_nobody_at_the_gate_fights_at_the_floor():
    engine = engine_of()
    state = engine.state
    elar, vayr = state.countries["ELAR"], state.countries["VAYR"]
    clear_armies(vayr)
    declare(engine, "ELAR", "VAYR")
    _home, raider = army_at_home(elar, units=4)
    staging, gate = approach(engine, "ELAR", "VAYR")
    floor = state.config["military"]["minimum_mass_share"]

    raider.tile = staging
    present, share = engine.military._mass(elar, gate, raider)
    assert len(present) == 1 and share == pytest.approx(1.0), "one army is the whole roster"
    _present, empty = engine.military._mass(vayr, gate)
    assert empty == pytest.approx(floor), "nothing stands there: the floor is what defends"


def test_a_battle_records_who_arrived_and_bleeds_them_before_the_rest():
    engine = engine_of()
    state = engine.state
    elar, vayr = state.countries["ELAR"], state.countries["VAYR"]
    elar.treasury = elar.food = 10_000.0
    military = state.config["military"]
    declare(engine, "ELAR", "VAYR")
    home, first, second = two_armies_at_home(engine, elar, units=3)
    staging, _gate = approach(engine, "ELAR", "VAYR")
    first.tile = second.tile = staging
    # A camp left at home with men in it: it must not lose the battle it did not fight.
    reserve = elar.new_army(tile=home, units={"MILITIA": 2})
    floor = military["minimum_mass_share"]
    expected = floor + (1 - floor) * (6 / 8)

    battle = engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "ATTACK", "target": "VAYR", "army_id": first.army_id,
    })
    assert battle.accepted, battle.reason_code
    effects = battle.effects

    assert effects["attacker_mass"] == [first.army_id, second.army_id]
    assert effects["attacker_share"] == pytest.approx(round(expected, 3)), \
        "the gate holds three quarters of the realm's men"
    assert floor <= effects["defender_share"] <= 1.0
    assert effects["attacker_loss"] == sum(effects["attacker_units"].values())

    event = last_event(state, "battle")
    assert (event["attacker_mass"], event["attacker_share"]) == (
        effects["attacker_mass"], effects["attacker_share"])

    assert reserve.strength == 2, "casualties fall on the gate first"
    assert first.strength + second.strength == 6 - effects["attacker_loss"]


def test_a_defender_garrison_far_from_the_gate_counts_as_little_as_attacker_one():
    engine = engine_of()
    state = engine.state
    elar, vayr = state.countries["ELAR"], state.countries["VAYR"]
    elar.treasury = elar.food = 10_000.0
    clear_armies(vayr)
    declare(engine, "ELAR", "VAYR")
    _home, first, second = two_armies_at_home(engine, elar, units=3)
    staging, gate = approach(engine, "ELAR", "VAYR")
    first.tile = second.tile = staging
    guard = vayr.new_army(tile=gate, units={"MILITIA": 3})
    remote_tile = max(vayr.tiles, key=lambda coord: hex_distance(coord, gate))
    remote = vayr.new_army(tile=remote_tile, units={"MILITIA": 3})
    assert hex_distance(remote_tile, gate) > state.config["military"]["mass_radius"]

    expected_share = engine.military._mass(vayr, gate)[1]
    battle = engine.military._battle(elar, vayr, first, gate, expedition=False)
    assert battle["attacker_mass"] == [first.army_id, second.army_id]
    assert battle["attacker_share"] == pytest.approx(1.0)
    assert battle["defender_mass"] == [guard.army_id]
    assert battle["defender_share"] == pytest.approx(round(expected_share, 3))
    assert battle["defender_share"] > state.config["military"]["minimum_mass_share"]
    assert remote.march is None and remote.strength == 3


def test_quotes_price_the_mass_they_would_fight_with():
    engine = engine_of()
    state = engine.state
    elar = state.countries["ELAR"]
    declare(engine, "ELAR", "VAYR")
    home, first, second = two_armies_at_home(engine, elar, units=3)
    staging, gate = approach(engine, "ELAR", "VAYR")
    third = elar.new_army(tile=home, units={"MILITIA": 3})

    spread = {item["army_id"]: item for item in
              engine.military.strike_options("ELAR", ["VAYR"])["VAYR"]["options"]}
    assert spread[first.army_id]["mass"] == 1
    assert spread[first.army_id]["mass_share"] == pytest.approx(
        round(engine.military._mass(elar, gate, first)[1], 4))

    for army in (second, third):
        army.tile = staging
    options = engine.military.strike_options("ELAR", ["VAYR"])["VAYR"]["options"]
    by_army = {item["army_id"]: item for item in options}
    assert by_army[first.army_id]["mass"] == 3, "an army marching in joins two already camped"
    assert by_army[first.army_id]["mass_share"] == pytest.approx(
        round(engine.military._mass(elar, gate, first)[1], 4))
    assert by_army[second.army_id]["can_attack"] and by_army[third.army_id]["can_attack"]
    assert options == sorted(
        options, key=lambda item: (item["days"], -item["mass"], item["army_id"])
    ), "a gate already holding garrisons outranks an equal march with fewer men"
    assert options[0]["army_id"] == second.army_id


def test_an_unreachable_realm_reports_no_mass_rather_than_a_fake_one():
    engine = engine_of()
    elar = engine.state.countries["ELAR"]
    declare(engine, "ELAR", "VAYR")
    home = elar.army_position or elar.tiles[0]
    clear_armies(elar)
    elar.new_army(tile=home, units={"MILITIA": 2})
    engine.state.config["movement"]["maximum_order_cost"] = 0.01
    quote = engine.military.strike_options("ELAR", ["VAYR"])["VAYR"]
    assert not quote["reachable"]
    assert quote["mass"] == 0 and quote["mass_share"] is None and quote["options"] == []


# --- the AI reads the same numbers ----------------------------------------------------

def town(country_overrides=None):
    country = {
        "personality": "conservative", "technology": {"bronze_metallurgy": 2},
        "buildings": {}, "projects": [], "cities": [{"health": 100, "security": 100}],
        "stability": 90.0, "population": 20000.0, "housing": 100.0,
        "food": 240.0, "food_capacity": 400.0, "treasury": 100.0,
    }
    return {**country, **(country_overrides or {})}


def test_the_mock_agent_wants_a_camp_for_every_city_it_holds():
    rules = engine_of().state.config
    agent = HeuristicAgent("ELAR")
    profile = PERSONALITIES["conservative"]["mock"]
    home_camps = profile["barracks"]

    assert agent._building_choice(town(), rules) == "BARRACKS"
    assert agent._building_choice(
        town({"buildings": {f"T{i}": "BARRACKS" for i in range(home_camps)}}), rules
    ) != "BARRACKS", "the home appetite is filled"

    grown = town({"cities": [{"health": 100, "security": 100}] * (home_camps + 3)})
    assert agent._building_choice(grown, rules) == "BARRACKS", "each new city asks for a camp"
    filled_outward = {**grown,
                      "buildings": {f"T{i}": "BARRACKS" for i in range(home_camps + 3)}}
    assert agent._building_choice(filled_outward, rules) != "BARRACKS"

    broke = town({"treasury": rules["buildings"]["BARRACKS"]["cost"] - 0.1})
    assert agent._building_choice(broke, rules) != "BARRACKS", "a camp nobody can wage waits"


def camp_observation(strength, recruiting, army_cap):
    country = {
        "treasury": 1_000.0, "army_strength": strength, "army_cap": army_cap,
        "army_units": {"MILITIA": strength}, "technology": {"bronze_metallurgy": 2},
        "armies": [{
            "army_id": "ELAR-A1", "barracks": True, "strength": strength,
            "recruiting": recruiting, "preferred_unit": "MILITIA",
        }],
    }
    return country


def test_the_mock_agent_stops_a_camp_that_filled_its_garrison():
    rules = engine_of().state.config
    agent = HeuristicAgent("ELAR")
    garrison = rules["military"]["barracks"]["garrison_capacity"]

    filled = agent._barracks_orders({}, {}, rules, camp_observation(garrison, True, 12))
    assert filled == [{"type": "MILITARY", "operation": "SET_RECRUITING",
                       "army_id": "ELAR-A1", "recruiting": False}], \
        "a filled camp comes off the wage book instead of stalling"

    room = agent._barracks_orders({}, {}, rules, camp_observation(1, False, 12))
    assert room == [{"type": "MILITARY", "operation": "SET_RECRUITING",
                     "army_id": "ELAR-A1", "recruiting": True}]

    ceiling = agent._barracks_orders({}, {}, rules, camp_observation(1, True, 1))
    assert ceiling[0]["recruiting"] is False, "a realm at its field ceiling stops paying wages"


def test_the_mock_agent_recruits_to_the_live_ceiling_not_the_flat_floor():
    rules = engine_of().state.config
    military = rules["military"]
    profile = PERSONALITIES["neutral"]["mock"]
    agent = HeuristicAgent("ELAR")
    floor = military["maximum_strength"]

    def observation(strength, cap):
        return {
            "rules": rules,
            "country": {
                "technology": {field: 5 for field in rules["tech_tree"]},
                "army_units": {}, "army_strength": strength, "army_cap": cap,
                "treasury": 10_000.0, "food": 10_000.0,
            },
        }

    assert agent._recruit_choice(observation(floor - 1, floor), profile, 1)
    assert agent._recruit_choice(observation(floor, floor), profile, 1) is None
    assert agent._recruit_choice(observation(floor, floor + 4), profile, 1), \
        "finished camps raise the ceiling and the agent has to see it"


# --- the UI leg: the same numbers reach the panel -------------------------------------

def test_the_snapshot_carries_the_ceiling_the_panel_shows():
    engine = engine_of()
    state = engine.state
    elar = state.countries["ELAR"]
    military = state.config["military"]
    assert state.summary()["countries"]["ELAR"]["army_cap"] == field_cap(
        elar.buildings.values(), state.config)
    stamp_camps(elar, 5)
    assert state.summary()["countries"]["ELAR"]["army_cap"] == \
        5 * military["barracks"]["garrison_capacity"]


def test_the_panel_shows_camps_mass_and_the_convergence_button():
    dashboard = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    for contract in (
        "const armyCap=c.army_cap||milRules.maximum_strength||0;",
        "到场 ${o.mass||1} 支 · 战力系数 ${fmtNum(o.mass_share||1,2)}",
        'data-mass="${esc(gate)}"',
        "兵营 / 全国编制上限",
        "其余向此集结",
    ):
        assert contract in dashboard, contract
    for key in ("mass_radius", "minimum_mass_share", "strike_columns", "garrison_capacity"):
        assert key in dashboard, key


def test_the_content_gate_still_demands_the_mass_parameters():
    content = engine_of().state.config
    for key in ("mass_radius", "minimum_mass_share"):
        missing = deepcopy(content)
        del missing["military"][key]
        with pytest.raises(ContentError):
            validate_content(missing)
    for key, value in (("minimum_mass_share", 0.0), ("minimum_mass_share", 1.5),
                       ("mass_radius", 0)):
        weak = deepcopy(content)
        weak["military"][key] = value
        with pytest.raises(ContentError):
            validate_content(weak)
