from core.state import CountryState, barracks_report
from live_server import LiveSession


def deploy(engine, country, city, tile, units, target=None):
    return engine.apply_action(country.country_id, {
        "type": "MILITARY", "operation": "DEPLOY", "city_id": city.city_id,
        "tile": {"col": tile[0], "row": tile[1]}, "units": units, "target": target,
    })


def test_training_stock_and_save_round_trip(engine):
    state, military = engine.state, engine.military
    country = state.countries["ELAR"]
    city = country.cities[0]
    country.buildings[city.center] = "BARRACKS"
    military.sync_barracks()
    camp = next(army for army in country.armies if army.tile == city.center)
    camp.recruiting = True
    camp.progress = 259
    military.barracks_daily()
    assert camp.units == {}
    assert country.city_reserves == {city.city_id: {"MILITIA": 1}}
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
    dead_end = deploy(engine, country, city, (-1, -1), {"MILITIA": 100})
    assert not dead_end.accepted and stock["MILITIA"] == 201
    first = deploy(engine, country, city, cells[0], {"MILITIA": 100})
    assert first.accepted, first.reason_text
    denied = deploy(engine, country, city, cells[1], {"MILITIA": 1})
    assert denied.reason_code == "DEPLOYMENT_LIMIT"
    assert stock["MILITIA"] == 101
    for level, cap in [(3, 2), (5, 3)]:
        country.technology["bronze_metallurgy"] = level
        assert country.deployment_status(state.config)["limit"] == cap
        assert deploy(engine, country, city, cells[cap - 1], {"MILITIA": 1}).accepted
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


def test_live_preview_picks_same_route_as_dispatch(monkeypatch, tmp_path):
    monkeypatch.setattr("live_server.SAVE_DIR", tmp_path)
    session = LiveSession(paused=True)
    session.player_country = "ELAR"
    state = session.simulation.state
    country = state.countries["ELAR"]
    city = country.cities[0]
    tile = next(tile for tile in state.world.neighbors(*city.center) if tile in country.tiles)
    country.city_reserves[city.city_id] = {"MILITIA": 150}
    snapshot = session.snapshot(lightweight=True)
    assert session.snapshot(lightweight=True, since=snapshot["revision"])["unchanged"]
    preview = session.deployment_preview(city.city_id, *tile, None)
    assert preview["ok"], preview
    action = {"type": "MILITARY", "operation": "DEPLOY", "city_id": city.city_id,
              "tile": {"col": tile[0], "row": tile[1]}, "units": {"MILITIA": 100}}
    result = session.player_action("ELAR", action)
    assert result["ok"], result
    assert result["result"]["effects"]["days"] == preview["days"]
    fresh = session.snapshot(lightweight=True, since=snapshot["revision"])
    assert fresh["countries"]["ELAR"]["cities"][0]["reserve_units"] == {"MILITIA": 50}
