"""Water surfaces reject facilities and zones, while licensed bridges remain roads."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import pytest

from core.terrain import is_water, repair_water_placements
from core.state import GameState
from core.society import default_zone
from core.replay import replay_saved_actions
from agents.heuristic import HeuristicAgent

ROOT=Path(__file__).resolve().parents[1]
BUILDINGS=[key for key in json.loads((ROOT/'config/rules.json').read_text(encoding='utf-8'))['buildings'] if key!='ROAD']


@pytest.fixture
def dry_map(engine):
    country=engine.state.countries['ELAR']
    tiles={(x,y):dict(col=x,row=y,land=True,river=False,lake=False,biome='grassland',
                      elevation_m=0,annual_precip_mm=500) for y in range(7) for x in range(9)}
    data=deepcopy(engine.state.world.data);data['metadata'].update(grid_width=9,grid_height=7);data['road_cells']=[]
    engine.state.world=replace(engine.state.world,tiles=tiles,data=data)
    engine.state.countries={'ELAR':country};country.tiles=list(tiles)
    country.cities=country.cities[:1];country.cities[0].center=(1,3);country.cities[0].tiles=list(tiles)
    country.cities[0].zones={p:'unzoned' for p in tiles};country.buildings={};country.roads=set();country.projects=[]
    country.treasury=10000;country.technology={k:10 for k in country.technology}
    return engine,country


@pytest.mark.parametrize('water',[{'river':True},{'lake':True},{'biome':'lake'},{'land':False,'biome':'ocean'}])
@pytest.mark.parametrize('building',BUILDINGS)
def test_every_facility_rejects_all_water_representations_without_payment(dry_map,water,building):
    engine,country=dry_map;engine.state.world.tiles[(2,3)].update(water)
    money=country.treasury
    result=engine.apply_action('ELAR',{'type':'BUILD','building':building,'tile':{'col':2,'row':3}})
    assert not result.accepted and result.reason_code in {'WATER_TILE','INVALID_TERRAIN'}
    assert country.treasury==money and not country.projects


def test_irrigation_and_desert_farms_use_dry_river_banks(dry_map):
    engine,country=dry_map
    engine.state.world.tiles[(3,3)]['river']=True
    result=engine.apply_action('ELAR',{'type':'BUILD','building':'IRRIGATION','tile':{'col':2,'row':3}})
    assert result.accepted
    denied=engine.apply_action('ELAR',{'type':'BUILD','building':'IRRIGATION','tile':{'col':7,'row':3}})
    assert not denied.accepted and denied.reason_code=='REQUIRES_RIVER'
    engine.state.world.tiles[(3,2)]['biome']='desert'
    assert engine.apply_action('ELAR',{'type':'BUILD','building':'FARM','tile':{'col':3,'row':2}}).accepted


def test_water_cannot_be_zoned_and_pending_facility_cannot_finish(dry_map):
    engine,country=dry_map;tile=engine.state.world.tiles[(2,3)];tile['river']=True
    assert default_zone((1,3),(2,3),tile)=='unzoned'
    for zone in ('farm','industry','residential','commerce','scholar'):
        result=engine.apply_action('ELAR',{'type':'SET_CITY_ZONE','city_id':country.cities[0].city_id,
                    'tile':{'col':2,'row':3},'zone':zone})
        assert not result.accepted and result.reason_code=='WATER_TILE'
    country.projects=[dict(project_id='P-WATER',tile=(2,3),building='GRANARY',remaining_days=.1)]
    engine.construction.advance_all()
    assert (2,3) not in country.buildings and country.projects[0]['remaining_days']==.1
    assert '水面' in country.projects[0]['blocked_reason']


def test_legacy_repair_relocates_or_refunds_without_changing_water_or_progress(dry_map):
    engine,country=dry_map;world=engine.state.world
    for y in range(7):world.tiles[(3,y)]['river']=True
    country.buildings[(3,2)]='GRANARY';country.roads.add((3,3))
    country.projects=[dict(project_id='P-WATER',tile=(3,4),building='FARM',remaining_days=7,cost=18)]
    country.cities[0].zones[(3,5)]='residential'
    before=country.treasury;changes=repair_water_placements(engine.state)
    assert len(changes)==3 and country.treasury==before
    assert all(not is_water(world.tile(p)) for p in country.buildings)
    assert not is_water(world.tile(tuple(country.projects[0]['tile']))) and country.projects[0]['remaining_days']==7
    assert world.tiles[(3,2)]['river'] and (3,3) in country.roads
    assert country.cities[0].zones[(3,5)]=='unzoned'
    assert repair_water_placements(engine.state)==[]
    country.buildings={(3,2):'GRANARY'};country.projects=[];country.tiles=[(3,2)]
    repair_water_placements(engine.state)
    assert not country.buildings and country.treasury==before+engine.state.config['buildings']['GRANARY']['cost']


def test_loading_a_legacy_save_repairs_water_and_resumes_replay(tmp_path):
    from core.simulation import Simulation
    source=ROOT/'examples/civil_networks/save.json'
    original=source.read_bytes();sim=Simulation.load(source)
    assert all(not is_water(sim.state.world.tile(p)) for c in sim.state.countries.values() for p,b in c.buildings.items() if b!='ROAD')
    assert all(not is_water(sim.state.world.tile(p)) for c in sim.state.countries.values() for city in c.cities for p,z in city.zones.items() if z!='unzoned')
    sim.step_months();path=sim.state.save(tmp_path/'repaired.json')
    assert GameState.load(path).fingerprint()==sim.state.fingerprint()
    assert replay_saved_actions(path).fingerprint()==sim.state.fingerprint()
    assert source.read_bytes()==original


def test_ai_does_not_choose_water_for_facilities():
    wet=dict(col=1,row=1,biome='grassland',river=True,water=True,elevation_m=0,building=None,project=None)
    dry=dict(wet,col=2,river=False,water=False)
    assert HeuristicAgent._choose_tile([wet,dry],'FARM')==dry


def test_lake_flags_cannot_be_used_as_bridge_tiles_or_banks(dry_map):
    from core.road import road_permit,river_width
    engine,country=dry_map;country.known_techs+=['modern_engineering','masonry_bridges']
    engine.state.world.tiles[(2,3)]['lake']=True
    assert road_permit(engine.state,country,(2,3))[0]=='INVALID_TERRAIN'
    for p,tile in engine.state.world.tiles.items():tile.update(lake=True,river=False)
    engine.state.world.tiles[(3,3)].update(lake=False,river=True)
    assert river_width(engine.state.world,(3,3)) is None


def test_legacy_water_city_and_wall_move_together_to_dry_land(dry_map):
    engine,country=dry_map;city=country.cities[0]
    city.center=(3,2);engine.state.world.tiles[(3,2)]['river']=True
    country.buildings[(3,2)]='WALL'
    repair_water_placements(engine.state)
    assert not is_water(engine.state.world.tile(city.center))
    assert country.buildings[city.center]=='WALL'


def test_legacy_capital_marker_uses_repaired_city_center(tmp_path,monkeypatch):
    import live_server
    monkeypatch.setattr(live_server,'SAVE_DIR',tmp_path/'saves')
    session=live_server.LiveSession(paused=True)
    try:
        state=session.simulation.state
        for polity in session.world_payload()['polities']:
            p=(polity['capital']['col'],polity['capital']['row'])
            assert not is_water(state.world.tile(p))
            assert p==state.capital_center(polity['id'])
            assert state.is_capital(state.countries[polity['id']],state.countries[polity['id']].cities[0])
    finally:session.stop()
