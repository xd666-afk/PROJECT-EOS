import numpy as np
import pytest

from worldgen import neighbors


def build(tile, building="FARM"):
    return {"type": "BUILD", "tile": tile, "building": building}


def test_build_success_completion_and_real_production_bonus(engine):
    state = engine.state
    country = state.countries["ELAR"]
    before_treasury = country.treasury
    result = engine.apply_action("ELAR", build({"col": 13, "row": 10}))
    assert result.accepted, result
    assert country.treasury == before_treasury - 18
    assert len(country.projects) == 1

    weather = {
        "rain": np.full((54, 72), 3.0),
        "temperature": np.full((54, 72), 18.0),
    }
    baseline = engine.economy.settle_country(country, weather)["food_production"]
    country.projects[0]["remaining_days"] = 0.1
    engine.construction.advance_all()
    assert country.buildings[(13, 10)] == "FARM"
    improved = engine.economy.settle_country(country, weather)["food_production"]
    assert improved > baseline


def test_build_rejects_foreign_tile_conflict_and_insufficient_funds(engine):
    country = engine.state.countries["ELAR"]
    treasury = country.treasury
    foreign = engine.apply_action("ELAR", build({"col": 56, "row": 18}))
    assert not foreign.accepted and foreign.reason_code == "TILE_NOT_OWNED"
    assert country.treasury == treasury

    assert engine.apply_action("ELAR", build({"col": 13, "row": 10})).accepted
    conflict = engine.apply_action("ELAR", build({"col": 13, "row": 10}, "MINE"))
    assert not conflict.accepted and conflict.reason_code == "BUILDING_CONFLICT"

    other = engine.state.countries["MARIS"]
    other.treasury = 0
    poor = engine.apply_action("MARIS", build({"col": 56, "row": 18}, "ROAD"))
    assert not poor.accepted and poor.reason_code == "INSUFFICIENT_TREASURY"


def test_advanced_building_requires_technology_and_raises_housing(engine):
    state = engine.state
    country = state.countries["ELAR"]
    before = state.summary()["countries"]["ELAR"]["housing"]
    locked = engine.apply_action("ELAR", build({"col": 13, "row": 10}, "GRANARY"))
    assert not locked.accepted and locked.reason_code == "TECHNOLOGY_REQUIRED"
    country.technology["agriculture"] = 2
    accepted = engine.apply_action("ELAR", build({"col": 13, "row": 10}, "GRANARY"))
    assert accepted.accepted
    country.projects[0]["remaining_days"] = 0.1
    engine.construction.advance_all()
    after = state.summary()["countries"]["ELAR"]["housing"]
    assert after == before + 8
    duplicate = engine.apply_action("ELAR", build({"col": 13, "row": 8}, "GRANARY"))
    assert not duplicate.accepted and duplicate.reason_code == "BUILDING_UNIQUE_LIMIT"


def test_low_stability_reduces_production_without_changing_weather(engine):
    country = engine.state.countries["ELAR"]
    weather = {"rain": np.full((54, 72), 3.0), "temperature": np.full((54, 72), 18.0)}
    country.stability = 80
    high = engine.economy.settle_country(country, weather)["food_production"]
    country.food = 160
    country.treasury = 100
    country.stability = 20
    low = engine.economy.settle_country(country, weather)["food_production"]
    assert high > low


def test_settle_requires_adjacent_unclaimed_land_and_expands_territory(engine):
    state = engine.state
    country = state.countries["ELAR"]
    owned = {coord for entity in state.countries.values() for coord in entity.tiles}
    target = next(
        coord for origin in country.tiles for coord in neighbors(*origin)
        if coord not in owned and state.world.tile(coord)["land"]
    )
    before = len(country.tiles)
    result = engine.apply_action("ELAR", {
        "type": "SETTLE", "tile": {"col": target[0], "row": target[1]},
    })
    assert result.accepted
    assert len(country.tiles) >= before + 1
    assert target in country.outposts
    assert len(country.cities) == 2
    assert len(country.cities[-1].tiles) >= 2
    assert len(country.cities[-1].tiles) <= engine.state.config["expansion"]["city_tiles"]
    assert sum(city.population for city in country.cities) == country.population
    duplicate = engine.apply_action("ELAR", {
        "type": "SETTLE", "tile": {"col": target[0], "row": target[1]},
    })
    assert not duplicate.accepted and duplicate.reason_code == "TILE_ALREADY_OWNED"

    distant = next(
        coord for coord in [(30, 30), (40, 30), (30, 40)]
        if coord not in owned and state.world.tile(coord)["land"]
    )
    rejected = engine.apply_action("ELAR", {
        "type": "SETTLE", "tile": {"col": distant[0], "row": distant[1]},
    })
    assert not rejected.accepted and rejected.reason_code == "NOT_ADJACENT"


def test_diplomatic_gifts_pacts_and_relation_threshold(engine):
    state = engine.state
    sender = state.countries["ELAR"]
    target = state.countries["MARIS"]
    target_before = target.treasury
    assert engine.apply_action("ELAR", {
        "type": "DIPLOMACY", "operation": "GIFT", "target": "MARIS", "amount": 10,
    }).accepted
    assert sender.treasury == 90 and target.treasury == target_before + 10
    assert engine.diplomacy.relation("ELAR", "MARIS") == 5
    blocked = engine.apply_action("ELAR", {
        "type": "DIPLOMACY", "operation": "PROPOSE_PACT", "target": "MARIS", "pact": "TRADE",
    })
    assert not blocked.accepted and blocked.reason_code == "RELATION_TOO_LOW"
    assert engine.apply_action("ELAR", {
        "type": "DIPLOMACY", "operation": "GIFT", "target": "MARIS", "amount": 20,
    }).accepted
    proposal = engine.apply_action("ELAR", {
        "type": "DIPLOMACY", "operation": "PROPOSE_PACT", "target": "MARIS", "pact": "TRADE",
    })
    assert proposal.accepted
    proposal_id = proposal.effects["proposal_id"]
    assert not engine.apply_action("ELAR", {
        "type": "DIPLOMACY", "operation": "ACCEPT_PACT", "proposal_id": proposal_id,
    }).accepted
    accepted = engine.apply_action("MARIS", {
        "type": "DIPLOMACY", "operation": "ACCEPT_PACT", "proposal_id": proposal_id,
    })
    assert accepted.accepted
    assert state.pacts[proposal_id]["status"] == "ACTIVE"
    assert engine.diplomacy.relation("ELAR", "MARIS") == 25


def test_military_recruitment_march_war_battle_and_peace(engine):
    from worldgen import neighbors
    state = engine.state
    elar = state.countries["ELAR"]
    maris = state.countries["MARIS"]
    before_treasury = elar.treasury
    assert engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "RECRUIT", "strength": 2,
    }).accepted
    assert elar.army_strength == 2
    assert elar.treasury == before_treasury - 50
    own_target = next(
        coord for coord in neighbors(*elar.army_position)
        if coord in elar.tiles
    )
    assert engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "MARCH",
        "tile": {"col": own_target[0], "row": own_target[1]},
    }).accepted
    assert elar.army_position == own_target

    war = engine.apply_action("ELAR", {
        "type": "DIPLOMACY", "operation": "DECLARE_WAR", "target": "MARIS",
    })
    assert war.accepted
    assert "MARIS" in elar.at_war_with and "ELAR" in maris.at_war_with

    border_tile = maris.tiles[0]
    staging = next(
        coord for coord in neighbors(*border_tile)
        if state.world.tile(coord)["land"] and coord not in maris.tiles
    )
    elar.army_position = staging
    battle = engine.apply_action("ELAR", {
        "type": "MILITARY", "operation": "ATTACK", "target": "MARIS",
    })
    assert battle.accepted
    assert battle.effects["battle"] is True
    captured_tile = battle.effects["tile"]
    if battle.effects["captured"]:
        coord = (captured_tile["col"], captured_tile["row"])
        assert coord not in maris.tiles
        assert not any(coord in city.tiles for city in maris.cities)
        assert any(coord in city.tiles for city in elar.cities)

    peace = engine.apply_action("MARIS", {
        "type": "DIPLOMACY", "operation": "PROPOSE_PEACE", "target": "ELAR",
    })
    assert peace.accepted
    accepted = engine.apply_action("ELAR", {
        "type": "DIPLOMACY", "operation": "ACCEPT_PACT",
        "proposal_id": peace.effects["proposal_id"],
    })
    assert accepted.accepted
    assert "MARIS" not in elar.at_war_with and "ELAR" not in maris.at_war_with


def test_city_focus_changes_only_own_city_and_affects_output(engine):
    state = engine.state
    country = state.countries["ELAR"]
    city = country.cities[0]
    weather = {"rain": np.full((54, 72), 3.0), "temperature": np.full((54, 72), 18.0)}
    baseline = engine.economy.settle_country(country, weather)["food_production"]
    result = engine.apply_action("ELAR", {
        "type": "SET_CITY_FOCUS", "city_id": city.city_id, "focus": "growth",
    })
    assert result.accepted
    assert city.focus == "growth"
    focused = engine.economy.settle_country(country, weather)["food_production"]
    assert focused > baseline
    rejected = engine.apply_action("ELAR", {
        "type": "SET_CITY_FOCUS", "city_id": "MARIS-C1", "focus": "industry",
    })
    assert not rejected.accepted and rejected.reason_code == "UNKNOWN_CITY"


def test_city_zoning_changes_tile_output_and_rejects_foreign_city(engine):
    state = engine.state
    country = state.countries["ELAR"]
    city = country.cities[0]
    coord = next(coord for coord in city.tiles if coord != city.center)
    assert engine.apply_action("ELAR", {
        "type": "SET_CITY_ZONE", "city_id": city.city_id,
        "tile": {"col": coord[0], "row": coord[1]}, "zone": "farm",
    }).accepted
    assert city.zones[coord] == "farm"
    assert engine.apply_action("ELAR", {
        "type": "SET_CITY_ZONE", "city_id": city.city_id,
        "tile": {"col": coord[0], "row": coord[1]}, "zone": "commerce",
    }).accepted
    assert city.zones[coord] == "commerce"
    rejected = engine.apply_action("ELAR", {
        "type": "SET_CITY_ZONE", "city_id": "MARIS-C1",
        "tile": {"col": coord[0], "row": coord[1]}, "zone": "farm",
    })
    assert not rejected.accepted and rejected.reason_code == "UNKNOWN_CITY"


def test_city_food_ledger_and_logistics_loss(engine):
    state = engine.state
    country = state.countries["ELAR"]
    weather = {"rain": np.full((54, 72), 3.0), "temperature": np.full((54, 72), 18.0)}
    metrics = engine.economy.settle_country(country, weather)
    total_output = sum(city.food_output for city in country.cities)
    assert total_output > 0
    assert metrics["food_production"] == pytest.approx(
        total_output + metrics["rural_food_output"]
    )
    for city in country.cities:
        assert city.food_need > 0
        assert city.food_balance == pytest.approx(city.food_output - city.food_need)
    assert metrics["food_logistics_loss"] > 0
    assert metrics["food_logistics_loss"] == pytest.approx(
        sum(city.food_loss for city in country.cities)
    )


def test_famine_hits_deficit_city_before_self_sufficient_city(engine):
    state = engine.state
    country = state.countries["ELAR"]
    capital = country.cities[0]
    capital.food_output = capital.food_need = 10.0
    frontier = type(capital).from_dict(capital.to_dict())
    frontier.city_id = "ELAR-C9"
    frontier.name = "缺粮城"
    frontier.food_output = 1.0
    frontier.food_need = 10.0
    frontier.population = 20_000
    country.cities.append(frontier)
    country.population += frontier.population
    country.population -= 1_000
    capital_before = capital.population
    engine.economy._distribute_famine(country, 1_000)
    assert frontier.population < 20_000
    assert capital.population == capital_before
    assert sum(city.population for city in country.cities) == country.population


def test_city_ai_manager_only_changes_delegated_cities(engine):
    from core.city_governance import CityManager
    country = engine.state.countries["ELAR"]
    city = country.cities[0]
    city.managed_by = "ai"
    CityManager(engine.state).plan(engine)
    assert city.focus == "growth"
    assert "farm" in city.zones.values()

    city.managed_by = "manual"
    focus = city.focus
    zones = dict(city.zones)
    CityManager(engine.state).plan(engine)
    assert city.focus == focus
    assert city.zones == zones
    assert engine.apply_action("ELAR", {
        "type": "SET_CITY_GOVERNANCE", "city_id": city.city_id, "managed_by": "ai",
    }).accepted
    assert city.managed_by == "ai"

    assert engine.apply_action("ELAR", {
        "type": "SET_CITY_GOVERNANCE", "city_id": city.city_id, "managed_by": "llm",
    }).accepted
    assert city.managed_by == "llm"
    focus = city.focus
    zones = dict(city.zones)
    CityManager(engine.state).plan(engine)
    assert city.focus == focus
    assert city.zones == zones


def test_allocate_workers_success_and_rejection_is_atomic(engine):
    country = engine.state.countries["ELAR"]
    result = engine.apply_action("ELAR", {
        "type": "ALLOCATE_WORKERS", "agriculture": 0.7, "mining": 0.1, "construction": 0.2,
    })
    assert result.accepted and country.workers["agriculture"] == 0.7
    previous = dict(country.workers)
    rejected = engine.apply_action("ELAR", {
        "type": "ALLOCATE_WORKERS", "agriculture": 0.8, "mining": 0.3, "construction": 0.2,
    })
    assert not rejected.accepted and rejected.reason_code == "INVALID_ALLOCATION"
    assert country.workers == previous


def test_set_tax_success_range_and_nonfinite_rejection(engine):
    country = engine.state.countries["ELAR"]
    assert engine.apply_action("ELAR", {"type": "SET_TAX", "rate": 0.12}).accepted
    assert country.tax_rate == 0.12
    for value in (0.5, float("nan"), True):
        result = engine.apply_action("ELAR", {"type": "SET_TAX", "rate": value})
        assert not result.accepted
        assert country.tax_rate == 0.12


def test_set_research_and_policy_have_state_effects_and_reject_unknowns(engine):
    country = engine.state.countries["VAYR"]
    assert engine.apply_action("VAYR", {"type": "SET_RESEARCH", "field": "bronze_metallurgy"}).accepted
    assert country.research_field == "bronze_metallurgy"
    assert engine.apply_action("VAYR", {"type": "SET_POLICY", "priority": "INDUSTRY"}).accepted
    assert country.policy == "INDUSTRY"
    assert not engine.apply_action("VAYR", {"type": "SET_RESEARCH", "field": "steam_engine"}).accepted
    assert not engine.apply_action("VAYR", {"type": "SET_POLICY", "priority": "UTOPIA"}).accepted


def test_trade_requires_target_acceptance_and_settles_conservatively(engine):
    sender = engine.state.countries["ELAR"]
    target = engine.state.countries["MARIS"]
    sender.food, target.food = 100.0, 50.0
    sender.treasury, target.treasury = 20.0, 10.0
    proposed = engine.apply_action("ELAR", {
        "type": "TRADE", "target": "MARIS", "offer_food": 5, "request_treasury": 3,
    })
    assert proposed.accepted
    proposal_id = proposed.effects["proposal_id"]
    assert sender.food == 95 and target.food == 50 and target.treasury == 10
    assert engine.state.trades[proposal_id]["status"] == "PENDING"

    wrong_actor = engine.apply_action("VAYR", {
        "type": "TRADE", "operation": "ACCEPT", "proposal_id": proposal_id,
    })
    assert not wrong_actor.accepted and wrong_actor.reason_code == "PERMISSION_DENIED"
    accepted = engine.apply_action("MARIS", {
        "type": "TRADE", "operation": "ACCEPT", "proposal_id": proposal_id,
    })
    assert accepted.accepted
    assert sender.food == 95 and target.food == 55
    assert sender.treasury == 23 and target.treasury == 7
    assert sender.food + target.food == 150
    assert sender.treasury + target.treasury == 30

    balances = (sender.food, target.food, sender.treasury, target.treasury)
    duplicate = engine.apply_action("MARIS", {
        "type": "TRADE", "operation": "ACCEPT", "proposal_id": proposal_id,
    })
    assert not duplicate.accepted
    assert balances == (sender.food, target.food, sender.treasury, target.treasury)


def test_trade_reject_and_expiry_refund_escrow(engine):
    sender = engine.state.countries["ELAR"]
    sender.food = 100
    first = engine.apply_action("ELAR", {
        "type": "TRADE", "target": "SAHAR", "offer_food": 5, "request_treasury": 3,
    })
    rejected = engine.apply_action("SAHAR", {
        "type": "TRADE", "operation": "REJECT",
        "proposal_id": first.effects["proposal_id"],
    })
    assert rejected.accepted and sender.food == 100

    second = engine.apply_action("ELAR", {
        "type": "TRADE", "target": "SAHAR", "offer_food": 5, "request_treasury": 3,
    })
    trade = engine.state.trades[second.effects["proposal_id"]]
    engine.state.day_index = trade["expires_day"]
    engine.diplomacy.expire_due()
    assert trade["status"] == "EXPIRED" and sender.food == 100


def test_trade_can_be_accepted_before_but_not_on_expiry_day(engine):
    proposal = engine.apply_action("ELAR", {
        "type": "TRADE", "target": "MARIS", "offer_food": 5, "request_treasury": 3,
    })
    trade = engine.state.trades[proposal.effects["proposal_id"]]
    engine.state.day_index = trade["expires_day"] - 1
    assert engine.apply_action("MARIS", {
        "type": "TRADE", "operation": "ACCEPT", "proposal_id": trade["proposal_id"],
    }).accepted

    second = engine.apply_action("ELAR", {
        "type": "TRADE", "target": "MARIS", "offer_food": 5, "request_treasury": 3,
    })
    second_trade = engine.state.trades[second.effects["proposal_id"]]
    engine.state.day_index = second_trade["expires_day"]
    sender_food = engine.state.countries["ELAR"].food
    rejected = engine.apply_action("MARIS", {
        "type": "TRADE", "operation": "ACCEPT", "proposal_id": second_trade["proposal_id"],
    })
    assert not rejected.accepted and rejected.reason_code == "TRADE_EXPIRED"
    assert second_trade["status"] == "EXPIRED"
    assert engine.state.countries["ELAR"].food == sender_food + 5


@pytest.mark.parametrize("raw", [
    {"type": []},
    {"type": "BUILD", "tile": {"col": 13, "row": 10}, "building": []},
    {"type": "SET_RESEARCH", "field": {}},
    {"type": "SET_POLICY", "priority": []},
    {"type": "TRADE", "operation": []},
])
def test_unhashable_json_fields_return_rejections_instead_of_crashing(engine, raw):
    result = engine.apply_action("ELAR", raw)
    assert not result.accepted
    assert result.reason_code in {"UNKNOWN_ACTION", "INVALID_PARAMETER"}


def test_trade_acceptance_insufficient_treasury_is_not_partial(engine):
    sender = engine.state.countries["ELAR"]
    target = engine.state.countries["MARIS"]
    sender.food, target.treasury = 100, 0
    proposal = engine.apply_action("ELAR", {
        "type": "TRADE", "target": "MARIS", "offer_food": 5, "request_treasury": 3,
    })
    result = engine.apply_action("MARIS", {
        "type": "TRADE", "operation": "ACCEPT", "proposal_id": proposal.effects["proposal_id"],
    })
    assert not result.accepted and result.reason_code == "INSUFFICIENT_TREASURY"
    assert target.treasury == 0
    assert engine.state.trades[proposal.effects["proposal_id"]]["status"] == "PENDING"


def test_agent_cannot_impersonate_another_country(engine):
    result = engine.apply_decision("ELAR", {
        "country_id": "MARIS", "world_day": 0,
        "actions": [{"type": "SET_TAX", "rate": 0.3}],
    })[0]
    assert result.action_type == "NO_OP"
    assert engine.state.countries["MARIS"].tax_rate == 0.1
    assert engine.state.event_log[-2]["reason_code"] == "IDENTITY_MISMATCH"


def test_city_budget_changes_service_spend_and_livability(engine):
    from core.society import city_livability_target

    state = engine.state
    country = state.countries["ELAR"]
    city = country.cities[0]
    weather = {"rain": np.full((54, 72), 3.0), "temperature": np.full((54, 72), 18.0)}
    baseline = engine.economy.settle_country(country, weather)
    baseline_target = city_livability_target(city, country, state.config)
    baseline_spend = baseline["city_service_spend"]

    assert engine.apply_action("ELAR", {
        "type": "SET_CITY_BUDGET", "city_id": city.city_id, "budget": "investment",
    }).accepted
    invested = engine.economy.settle_country(country, weather)
    assert city.budget == "investment"
    assert invested["city_service_spend"] > baseline_spend
    assert city.local_upkeep > 0
    assert city_livability_target(city, country, state.config) > baseline_target

    assert engine.apply_action("ELAR", {
        "type": "SET_CITY_BUDGET", "city_id": city.city_id, "budget": "austerity",
    }).accepted
    austere = engine.economy.settle_country(country, weather)
    assert austere["city_service_spend"] < baseline_spend
    assert city_livability_target(city, country, state.config) < baseline_target

    rejected = engine.apply_action("ELAR", {
        "type": "SET_CITY_BUDGET", "city_id": city.city_id, "budget": "lavish",
    })
    assert not rejected.accepted and rejected.reason_code == "INVALID_PARAMETER"
    foreign = engine.apply_action("ELAR", {
        "type": "SET_CITY_BUDGET", "city_id": "MARIS-C1", "budget": "investment",
    })
    assert not foreign.accepted and foreign.reason_code == "UNKNOWN_CITY"


def test_city_manager_uses_budget_for_livability_and_fiscal_stress(engine):
    from core.city_governance import CityManager

    country = engine.state.countries["ELAR"]
    city = country.cities[0]
    city.managed_by = "ai"
    country.treasury = 100.0
    city.livability = 40.0
    CityManager(engine.state).plan(engine)
    assert city.budget == "investment"

    country.treasury = 2.0
    city.local_net = -1.0
    city.livability = 60.0
    CityManager(engine.state).plan(engine)
    assert city.budget == "austerity"


def test_ai_frontier_expansion_creates_city_and_skips_player(engine):
    from types import SimpleNamespace
    state = engine.state
    state.day_index = 120
    for country in state.countries.values():
        country.treasury = max(country.treasury, 100.0)
        country.population = max(country.population, 12000)
    engine.planner = SimpleNamespace(controlled_by_player={"ELAR"})
    before = {cid: (len(c.outposts), len(c.cities)) for cid, c in state.countries.items()}
    engine.step_day(force=True)
    assert len(state.countries["ELAR"].outposts) == before["ELAR"][0]
    assert any(
        len(country.outposts) > before[cid][0]
        for cid, country in state.countries.items() if cid != "ELAR"
    )
    for cid, country in state.countries.items():
        if cid != "ELAR" and len(country.outposts) > before[cid][0]:
            assert len(country.cities[-1].tiles) == engine.state.config["expansion"]["city_tiles"]
            assert any(
                e["type"] == "ai_frontier_expansion" and e["country_id"] == cid
                for e in state.event_log
            )
            break


def test_settle_rejects_river_water_tile(engine):
    state = engine.state
    country = state.countries["ELAR"]
    owned = {coord for entity in state.countries.values() for coord in entity.tiles}
    river_tile = next(
        tile for tile in state.world.tiles.values()
        if tile["land"] and tile["river"] and (tile["col"], tile["row"]) not in owned
    )
    dry_neighbor = next(
        neighbor for neighbor in state.world.neighbors(river_tile["col"], river_tile["row"])
        if state.world.tile(neighbor)["land"] and not state.world.tile(neighbor)["river"]
    )
    country.tiles.append(dry_neighbor)
    result = engine.apply_action("ELAR", {
        "type": "SETTLE", "tile": {"col": river_tile["col"], "row": river_tile["row"]},
    })
    assert not result.accepted
    assert result.reason_code == "RIVER_TILE"


def test_road_build_must_connect_to_city_or_existing_road(engine):
    from worldgen import hex_distance

    state = engine.state
    country = state.countries["ELAR"]
    capital = country.cities[0].center
    owned = [coord for coord in country.tiles if state.world.tile(coord)["land"]]
    disconnected = next(
        coord for coord in owned
        if hex_distance(coord, capital) >= 2
        and not any(
            hex_distance(coord, city.center) == 1
            for entity in state.countries.values() for city in entity.cities
        )
    )
    rejected = engine.apply_action(
        "ELAR", build({"col": disconnected[0], "row": disconnected[1]}, "ROAD")
    )
    assert not rejected.accepted
    assert rejected.reason_code == "ROAD_NOT_CONNECTED"

    adjacent = next(
        coord for coord in owned
        if hex_distance(coord, capital) == 1
        and coord not in country.buildings
    )
    accepted = engine.apply_action(
        "ELAR", build({"col": adjacent[0], "row": adjacent[1]}, "ROAD")
    )
    assert accepted.accepted, accepted


def test_cross_border_road_requires_diplomatic_level():
    from types import SimpleNamespace
    from core.road import road_connection_status

    country_a = SimpleNamespace(country_id="A", cities=[], buildings={})
    country_b = SimpleNamespace(country_id="B", cities=[], buildings={})
    world = SimpleNamespace(road_cells=lambda: [
        {"tile": {"col": 1, "row": 0}, "owner_id": "B"}
    ])
    level = {"value": 2}

    def diplomatic_level(left, right):
        assert (left, right) == ("A", "B")
        return level["value"]

    state = SimpleNamespace(
        countries={"A": country_a, "B": country_b},
        world=world,
        diplomatic_level=diplomatic_level,
        road_connection_level=lambda: 3,
    )
    connected, denied, owners = road_connection_status(state, country_a, (0, 0))
    assert not connected
    assert denied == ["B"]
    assert owners == {"B"}

    level["value"] = 3
    connected, denied, owners = road_connection_status(state, country_a, (0, 0))
    assert connected
    assert denied == []
