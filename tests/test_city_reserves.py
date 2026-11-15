import json
from dataclasses import replace

from core.state import CountryState, GameState, barracks_report
from live_server import LiveSession


def deploy(engine, country, city, tile, units, target=None, **extra):
    return engine.apply_action(country.country_id, {
        "type": "MILITARY", "operation": "DEPLOY", "city_id": city.city_id,
        "tile": {"col": tile[0], "row": tile[1]}, "units": units, "target": target, **extra,
    })


def test_training_stock_and_save_round_trip(engine):
    state, military = engine.state, engine.military
    country = state.countries["ELAR"]
    city = country.cities[0]
    country.buildings[city.center] = "BARRACKS"
    military.sync_barracks()
    camp = next(army for army in country.armies if army.tile == city.center)
    country.buildings[next(tile for tile in country.tiles if tile != city.center)] = "BARRACKS"
    military.sync_barracks()
    assert all(not army.recruiting for army in country.armies)
    toggle = {"type": "MILITARY", "operation": "SET_RECRUITING",
              "army_id": camp.army_id, "recruiting": True}
    treasury = country.treasury
    assert engine.apply_action("ELAR", toggle).reason_code == "RECRUIT_UNIT_REQUIRED"
    military.barracks_daily()
    assert country.treasury == treasury and camp.progress == 0

    selected = engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "SET_RECRUIT_UNIT", "army_id": camp.army_id,
        "unit": "MILITIA",
    })
    assert selected.accepted and not camp.recruiting
    military.barracks_daily()
    assert country.treasury == treasury and camp.progress == 0
    assert engine.apply_action("ELAR", toggle).accepted
    military.barracks_daily()
    assert camp.progress == 1.0 and country.treasury < treasury
    assert engine.apply_action("ELAR", {**toggle, "recruiting": False}).accepted
    treasury = country.treasury
    military.barracks_daily()
    assert camp.progress == 1.0 and country.treasury == treasury
    assert engine.apply_action("ELAR", toggle).accepted
    camp.progress = 259
    military.barracks_daily()
    assert camp.units == {}
    assert country.city_reserves == {city.city_id: {"MILITIA": 10}}
    assert barracks_report(country, city.center, state.config)["reserve_city"] == city.name
    assert country.deployment_status(state.config)["used"] == 0
    restored = CountryState.from_dict(country.to_dict(), state.config)
    assert restored.city_reserves == country.city_reserves
    assert restored.military_food(state.config) > 0


def test_slots_cover_stationed_and_marching_armies_and_return(engine):
    state, military = engine.state, engine.military
    country = state.countries["ELAR"]
    city = country.cities[0]
    cells = [tile for tile in state.world.neighbors(*city.center) if tile in country.tiles]
    assert len(cells) >= 3
    stock = country.city_reserves[city.city_id] = {"MILITIA": 201}
    assert deploy(engine, country, city, cells[0], {"MILITIA": 1}, slot=2).reason_code == "DEPLOYMENT_LOCKED"
    dead_end = deploy(engine, country, city, (-1, -1), {"MILITIA": 100})
    assert not dead_end.accepted and stock["MILITIA"] == 201
    first = deploy(engine, country, city, cells[0], {"MILITIA": 100}, slot=1)
    assert first.accepted, first.reason_text
    denied = deploy(engine, country, city, cells[1], {"MILITIA": 1})
    assert denied.reason_code == "DEPLOYMENT_LIMIT"
    assert stock["MILITIA"] == 101
    for level, cap in [(3, 2), (5, 3)]:
        country.technology["bronze_metallurgy"] = level
        assert country.deployment_status(state.config)["limit"] == cap
        assert deploy(engine, country, city, cells[cap - 1], {"MILITIA": 1}, slot=1).reason_code == "DEPLOYMENT_OCCUPIED"
        assert deploy(engine, country, city, cells[cap - 1], {"MILITIA": 1}, slot=cap).accepted
    military.movement_config["daily_budget"] = 100
    military.march_daily()
    assert country.deployment_status(state.config)["used"] == 3
    army_id = first.effects["army_id"]
    returned = engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "RETURN", "army_id": army_id,
    })
    assert returned.accepted, returned.reason_text
    military.march_daily()
    assert stock["MILITIA"] == 199
    assert country.deployment_status(state.config)["used"] == 2
    slots = country.deployment_status(state.config)["slots"]
    assert slots[0]["army_id"] is None and all(row["army_id"] for row in slots[1:])
    assert army_id in country.army_tombstones


def test_reserve_engages_only_at_its_city(engine):
    state, military = engine.state, engine.military
    defender, attacker = (state.countries[key] for key in ("ELAR", "MARIS"))
    city = defender.cities[0]
    tile = next(tile for tile in state.world.neighbors(*city.center) if tile in defender.tiles)
    stock = defender.city_reserves[city.city_id] = {"MILITIA": 30}
    column = attacker.new_army(tile, {"MILITIA": 2})
    military._battle(attacker, defender, column, tile, False, capture_ground=False)
    assert stock["MILITIA"] == 30
    assert column.strength == 2
    result = military._begin_siege(attacker, defender, column, city)
    assert result["battle"] and not result["won"]
    assert column.strength == 1
    assert city.siege is None
    column.units["MILITIA"] = 500
    result = military._begin_siege(attacker, defender, column, city)
    assert result["siege"]["reserve_strength"] < 30
    assert stock["MILITIA"] < 30


def test_new_rendezvous_orders_are_refused(engine):
    result = engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "RENDEZVOUS",
        "army_id": "a", "host_id": "b", "units": {"MILITIA": 1},
    })
    assert result.reason_code == "RENDEZVOUS_REMOVED"


def test_live_preview_picks_same_route_as_dispatch(monkeypatch, tmp_path, request):
    monkeypatch.setattr("live_server.SAVE_DIR", tmp_path)
    session = LiveSession(paused=True)
    request.addfinalizer(session._stop.set)
    session.player_country = "ELAR"
    state = session.simulation.state
    country = state.countries["ELAR"]
    city = country.cities[0]
    tile = next(tile for tile in state.world.neighbors(*city.center) if tile in country.tiles)
    snapshot = session.snapshot(lightweight=True)
    assert session.snapshot(lightweight=True, since=snapshot["revision"])["unchanged"]
    blocked = session.player_action("ELAR", {
        "type": "MILITARY", "operation": "RECRUIT", "unit": "MILITIA", "strength": 1,
    })
    assert not blocked["ok"] and not country.reserve_roster()
    camp = country.find_army(country.armies[0].army_id)
    country.buildings[city.center] = "BARRACKS"
    camp.preferred_unit = "MILITIA"
    camp.recruiting = True
    camp.progress = 259
    session.simulation.engine.military.barracks_daily()
    fresh = session.snapshot(lightweight=True, since=snapshot["revision"])
    assert fresh["day"] == snapshot["day"]
    assert fresh["countries"]["ELAR"]["cities"][0]["reserve_units"] == {"MILITIA": 10}
    assert fresh["countries"]["ELAR"]["reserve_units"] == {"MILITIA": 10}
    preview = session.deployment_preview(city.city_id, *tile, None)
    assert preview["ok"], preview
    action = {"type": "MILITARY", "operation": "DEPLOY", "city_id": city.city_id,
              "tile": {"col": tile[0], "row": tile[1]}, "units": {"MILITIA": 7}}
    result = session.player_action("ELAR", action)
    assert result["ok"], result
    assert result["result"]["effects"]["days"] == preview["days"]
    assert result["result"]["effects"]["cost"] == preview["cost"]
    fresh = session.snapshot(lightweight=True, since=snapshot["revision"])
    assert fresh["countries"]["ELAR"]["cities"][0]["reserve_units"] == {"MILITIA": 3}


def test_old_reserves_and_deployed_armies_convert_only_once(state, tmp_path):
    realm = state.countries["ELAR"]
    city = realm.cities[0]
    realm.city_reserves[city.city_id] = {"MILITIA": 2}
    army = realm.new_army(city.center, {"ARCHER": 3})
    payload = state.to_dict()
    payload["rules"]["military"].pop("soldiers_per_unit")
    path = tmp_path / "old.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = GameState.load(path)
    new_realm = loaded.countries["ELAR"]
    assert new_realm.city_reserves[city.city_id] == {"MILITIA": 20}
    assert new_realm.find_army(army.army_id).units == {"ARCHER": 30}
    assert new_realm.find_army(army.army_id).deployment_slot == 1
    loaded.save(path)
    assert GameState.load(path).fingerprint() == loaded.fingerprint()


def test_foreign_combat_factor_uses_battlefield_owner(engine):
    state = engine.state
    attacker, defender = (state.countries[key] for key in ("ELAR", "MARIS"))
    attacker.at_war_with = ["MARIS"]
    defender.at_war_with = ["ELAR"]
    target = defender.cities[0].center
    army = attacker.new_army(target, {"MILITIA": 100})
    result = engine.military._battle(attacker, defender, army, target, False, capture_ground=False)
    assert result["attacker_territory_factor"] == 0.8
    assert result["defender_territory_factor"] == 1.0
    home = attacker.cities[0].center
    result = engine.military._battle(attacker, defender, army, home, True, capture_ground=False)
    assert result["attacker_territory_factor"] == 1.0
    assert result["defender_territory_factor"] == 0.8


def test_national_dispatch_draws_multiple_cities_and_locks_roster(engine):
    state = engine.state
    country = state.countries["ELAR"]
    city = country.cities[0]
    cells = [tile for tile in state.world.neighbors(*city.center) if tile in country.tiles]
    country.cities.append(replace(city, city_id="ELAR-C2", center=cells[0]))
    country.city_reserves = {city.city_id: {"MILITIA": 10}, "ELAR-C2": {"MILITIA": 10, "ARCHER": 5}}
    country.technology["bronze_metallurgy"] = 3
    first = deploy(engine, country, city, cells[1], {"MILITIA": 17, "ARCHER": 4}, slot=1, city_id=None)
    assert first.accepted, first.reason_text
    army = country.find_army(first.effects["army_id"])
    assert army.units == {"MILITIA": 17, "ARCHER": 4}
    assert country.reserve_roster() == {"MILITIA": 3, "ARCHER": 1}
    blocked = deploy(engine, country, city, cells[2], {"MILITIA": 4}, slot=2, city_id=None)
    assert blocked.reason_code == "RESERVE_SHORTAGE"
    assert country.reserve_roster() == {"MILITIA": 3, "ARCHER": 1}
    enemy = state.countries["MARIS"]
    country.at_war_with.append("MARIS")
    objective, start = next(
        (land, point) for land in enemy.tiles
        for point in state.world.neighbors(*land)
        if point not in enemy.tiles and point not in country.tiles and state.world.tiles[point]["land"]
    )
    army.tile = start
    revised = engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "RETASK", "slot": 1, "target": "MARIS",
        "tile": {"col": objective[0], "row": objective[1]},
    })
    assert revised.accepted, revised.reason_text
    assert army.march.route[0] == start
    assert army.march.purpose == "ATTACK"
    assert army.units == {"MILITIA": 17, "ARCHER": 4}


def test_reinforcements_merge_at_arrival_and_release_their_number(engine):
    state = engine.state
    country = state.countries["ELAR"]
    country.technology["bronze_metallurgy"] = 3
    city = country.cities[0]
    tile = next(tile for tile in state.world.neighbors(*city.center) if tile in country.tiles)
    host = country.new_army(tile, {"MILITIA": 12})
    host.deployment_slot = 1
    country.city_reserves[city.city_id] = {"ARCHER": 10}
    result = deploy(engine, country, city, tile, {"ARCHER": 7}, slot=2, host_id=host.army_id, city_id=None)
    assert result.accepted, result.reason_text
    assert country.deployment_status(state.config)["used"] == 2
    assert host.units == {"MILITIA": 12}
    for _ in range(result.effects["days"]):
        engine.military.march_daily()
    assert country.find_army(result.effects["army_id"]) is None
    assert host.units == {"MILITIA": 12, "ARCHER": 7}
    assert country.reserve_roster() == {"ARCHER": 3}
    assert country.deployment_status(state.config)["slots"][1]["army_id"] is None
