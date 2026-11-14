"""Conservation, bottlenecks, diplomatic access and old-save interoperability."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from core.access import access_rights
from core.content import ContentError, validate_content
from core.logistics import Logistics, reconcile_stocks
from core.rules import RuleEngine
from core.simulation import Simulation
from core.state import CityState, GameState, relation_key
from live_server import LiveSession

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def corridor():
    state = GameState.new()
    country = state.countries["ELAR"]
    country.population = 2000
    country.cities = [
        CityState("C1", "粮仓城", (0, 1), 1000, "balanced", [(0, 1)], food_stock=100),
        CityState("C2", "缺粮城", (6, 1), 1000, "balanced", [(6, 1)], food_stock=0),
    ]
    country.cities[1].food_need = 5
    country.food = 100
    country.tiles = [(0, 1), (6, 1)]
    country.buildings = {}
    country.armies = []
    state.countries = {"ELAR": country}
    tiles = {(x, 1): {"land": True, "river": False, "biome": "grassland"} for x in range(7)}
    state.world = SimpleNamespace(tiles=tiles, road_cells=lambda: [],
        tile=lambda coord: tiles[coord],
        neighbors=lambda x, y: [(n, 1) for n in (x-1, x+1) if 0 <= n < 7])
    return state, country, Logistics(state)


def test_flow_conserves_food_and_shared_national_total(corridor):
    state, country, network = corridor
    result = network.settle(country, {"C1": 2}, 0)
    consumed = 5 - result["shortage"]
    assert country.food == pytest.approx(100 + 2 - consumed - result["loss"] - result["overflow"])
    assert country.food == pytest.approx(sum(c.food_stock for c in country.cities))
    assert country.cities[0].food_exported <= state.config["transport"]["land_capacity"]
    assert result["shortage"] > 0 and result["loss"] > 0
    assert country.cities[1].food_imported > 0


def test_continuous_roads_increase_capacity_and_reduce_losses(corridor):
    state, country, network = corridor
    old = network.routes(country)[0]
    country.buildings = {coord: "ROAD" for coord in state.world.tiles}
    road = network.routes(country)[0]
    assert road["capacity"] > old["capacity"]
    assert road["loss_rate"] < old["loss_rate"]
    result = network.settle(country, {}, 0)
    assert result["shortage"] == 0


def test_bridge_cut_really_interrupts_supply(corridor):
    state, country, network = corridor
    state.world.tiles[(3, 1)]["river"] = True
    assert network.routes(country)[0]["status"] == "blocked"
    country.buildings[(3, 1)] = "ROAD"
    assert network.routes(country)[0]["status"] == "connected"
    del country.buildings[(3, 1)]
    assert network.routes(country)[0]["status"] == "blocked"
    result = network.settle(country, {}, 0)
    assert result["shortage"] == 5
    assert country.food > 0, "a distant full granary cannot feed a disconnected city"
    assert country.cities[1].logistics_status == "运输中断：本地缺粮"


def test_civil_route_requires_open_borders_and_revocation_invalidates_cache(corridor):
    state, country, network = corridor
    other = deepcopy(country)
    other.country_id, other.tiles, other.cities, other.buildings = "MARIS", [(3, 1)], [], {}
    state.countries["MARIS"] = other
    assert network.routes(country)[0]["status"] == "blocked"
    assert network.routes(country)[0]["blocked_by"] == ["MARIS"]
    state.relations[relation_key("ELAR", "MARIS")] = 60
    # Friendship alone is not legal access.
    assert network.routes(country)[0]["status"] == "blocked"
    state.pacts["P1"] = {"proposal_id": "P1", "sender": "ELAR", "target": "MARIS", "pact": "OPEN_BORDERS", "status": "ACTIVE"}
    assert network.routes(country)[0]["status"] == "connected"
    assert not access_rights(state, "ELAR", "MARIS")["military"]
    state.pacts["P1"]["status"] = "BROKEN"
    assert network.routes(country)[0]["status"] == "blocked"


def test_shared_edges_do_not_multiply_transport_capacity(corridor):
    state, country, network = corridor
    country.cities.append(CityState("C3", "下游城", (4, 1), 1000, "balanced", [(4, 1)], food_stock=0))
    country.cities[-1].food_need = 5
    country.population += 1000
    country.tiles.append((4, 1))
    network.settle(country, {}, 0)
    assert country.cities[0].food_exported <= state.config["transport"]["land_capacity"] + 1e-9


def test_inventory_reconciliation_does_not_duplicate_legacy_or_trade_grain(corridor):
    state, country, network = corridor
    for c in country.cities:
        c.food_stock = None
    reconcile_stocks(country, state.config)
    assert sum(c.food_stock for c in country.cities) == 100
    country.food -= 20
    reconcile_stocks(country, state.config)
    assert sum(c.food_stock for c in country.cities) == pytest.approx(80)
    country.food += 7
    reconcile_stocks(country, state.config)
    assert sum(c.food_stock for c in country.cities) == pytest.approx(87)


def test_granary_capacity_is_local_to_its_city(corridor):
    state, country, network = corridor
    reconcile_stocks(country, state.config)
    before = [c.food_capacity for c in country.cities]
    country.buildings[(6, 1)] = "GRANARY"
    reconcile_stocks(country, state.config)
    assert country.cities[0].food_capacity == pytest.approx(before[0])
    assert country.cities[1].food_capacity == pytest.approx(before[1] + state.config["food_storage"]["granary_bonus"])


@pytest.mark.parametrize("kind,threshold", [("OPEN_BORDERS",25),("MILITARY_ACCESS",40),("ALLIANCE",60)])
def test_access_pacts_need_acceptance_and_can_be_revoked(engine, kind, threshold):
    state = engine.state
    action = {"type":"DIPLOMACY", "operation":"PROPOSE_PACT", "target":"MARIS", "pact":kind}
    assert not engine.apply_action("ELAR", action).accepted
    state.relations[relation_key("ELAR","MARIS")] = threshold
    proposed = engine.apply_action("ELAR", action)
    assert proposed.accepted
    pid = proposed.effects["proposal_id"]
    assert not access_rights(state,"ELAR","MARIS")["civil"]
    assert not engine.apply_action("VAYR", {"type":"DIPLOMACY","operation":"ACCEPT_PACT","proposal_id":pid}).accepted
    assert engine.apply_action("MARIS", {"type":"DIPLOMACY","operation":"ACCEPT_PACT","proposal_id":pid}).accepted
    rights = access_rights(state,"ELAR","MARIS")
    assert rights["civil"] == (kind in {"OPEN_BORDERS","ALLIANCE"})
    assert rights["military"] == (kind in {"MILITARY_ACCESS","ALLIANCE"})
    assert engine.apply_action("ELAR", {"type":"DIPLOMACY","operation":"REVOKE_PACT","proposal_id":pid}).accepted
    assert not access_rights(state,"ELAR","MARIS")["civil"]
    assert not access_rights(state,"ELAR","MARIS")["military"]


def test_war_breaks_active_and_pending_access_pacts(engine):
    s=engine.state
    s.relations[relation_key("ELAR","MARIS")]=60
    p=engine.apply_action("ELAR",{"type":"DIPLOMACY","operation":"PROPOSE_PACT","target":"MARIS","pact":"ALLIANCE"})
    pid=p.effects["proposal_id"]
    assert engine.apply_action("MARIS",{"type":"DIPLOMACY","operation":"ACCEPT_PACT","proposal_id":pid}).accepted
    pending=engine.apply_action("ELAR",{"type":"DIPLOMACY","operation":"PROPOSE_PACT","target":"MARIS","pact":"TRADE"}).effects["proposal_id"]
    assert engine.apply_action("ELAR",{"type":"DIPLOMACY","operation":"DECLARE_WAR","target":"MARIS"}).accepted
    assert not access_rights(s,"ELAR","MARIS")["civil"]
    assert s.diplomatic_proposals[pending]["status"]=="BROKEN"
    assert not engine.apply_action("MARIS",{"type":"DIPLOMACY","operation":"ACCEPT_PACT","proposal_id":pending}).accepted


def test_military_adapter_honors_access_without_changing_base_costs(engine):
    s=engine.state
    left,right=s.countries["ELAR"],s.countries["MARIS"]
    target=right.cities[0].center
    before=engine.military.movement("ELAR").cost(target)
    s.pacts["P1"]={"proposal_id":"P1","sender":"ELAR","target":"MARIS","pact":"MILITARY_ACCESS","status":"ACTIVE"}
    after=engine.military.movement("ELAR").cost(target)
    assert before-after==pytest.approx(s.config["movement"]["hostile_cost"])
    assert engine.military._marchable("ELAR",target,engine.military._owners())


def test_real_crossing_records_one_incident_and_persists_across_load(engine,tmp_path):
    s=engine.state
    from core.state import MarchOrder
    c=s.countries["ELAR"]
    start=c.cities[0].center
    road=[start]
    for _ in range(4):
        road.append(next(n for n in s.world.neighbors(*road[-1]) if s.world.tile(n)["land"] and n not in road))
    for other in s.countries.values():
        other.tiles=[p for p in other.tiles if p not in road[1:]]
    s.countries["MARIS"].tiles.extend(road[1:])
    c.armies=[]
    army=c.new_army(tile=start,units={"MILITIA":4})
    army.march=MarchOrder("MARCH",road,[0,3,6,9,12])
    assert not any(e["type"]=="border_trespass" for e in s.event_log)
    engine.military.march_daily()
    assert len([e for e in s.event_log if e["type"]=="border_trespass"])==1
    restored=Simulation.load(s.save(tmp_path/'crossing.json'),use_mock_agents=False)
    restored.engine.military.march_daily()
    assert len([e for e in restored.state.event_log if e["type"]=="border_trespass"])==1


def test_inventory_and_network_resume_deterministically(tmp_path):
    sim=Simulation.load(ROOT/'examples/hexfirst/save.json')
    sim.step(40)
    for c in sim.state.countries.values():
        assert c.food==pytest.approx(sum(city.food_stock for city in c.cities))
    restored=Simulation.load(sim.state.save(tmp_path/'stocks.json'))
    assert restored.state.fingerprint()==sim.state.fingerprint()
    sim.step(10);restored.step(10)
    assert restored.state.fingerprint()==sim.state.fingerprint()


def test_monthly_events_and_recruitment_preserve_city_aggregate(tmp_path):
    sim=Simulation.load(ROOT/'examples/hexfirst/save.json')
    assert sim.engine.apply_action('A', {'type':'MILITARY','operation':'RECRUIT',
        'unit':'MILITIA','strength':2}).accepted
    assert sim.state.countries['A'].food == pytest.approx(
        sum(city.food_stock for city in sim.state.countries['A'].cities))
    sim.state.config['weather']['flood_monthly_rate']=1000
    sim.state.config['weather']['drought_monthly_rate']=1000
    for day in range(65):
        sim.step(1)
        for country in sim.state.countries.values():
            assert country.food==pytest.approx(sum(city.food_stock for city in country.cities))
    saved=sim.state.save(tmp_path/'monthly.json')
    assert Simulation.load(saved).state.fingerprint()==sim.state.fingerprint()


def test_transport_rejects_non_finite_or_invalid_rules(state):
    for key,value in [("land_capacity",0),("max_loss",1),("road_cost",float('nan'))]:
        config=deepcopy(state.config)
        config["transport"][key]=value
        with pytest.raises(ContentError):
            validate_content(config)
