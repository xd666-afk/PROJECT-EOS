import json
from pathlib import Path
import numpy as np
from worldgen import W,H,hex_distance,validate

DIR=Path(__file__).resolve().parents[1]
WORLD=json.loads((DIR/'output/world_2000BCE.json').read_text(encoding='utf8'))
WEATHER=json.loads((DIR/'output/first_year_weather.json').read_text(encoding='utf8'))

def test_world_integrity():
    assert validate(WORLD)
    assert len(WORLD['polities'])==4
    assert 1500<WORLD['world_summary']['land_hexes']<3400
    assert WORLD['metadata']['world_year_bce']==2000
    assert WORLD['metadata']['astronomical_year']==-1999

def test_seasonality_risk_and_terrain():
    t=WORLD['tiles']
    assert len(t)==W*H
    assert all(len(x['monthly_temp_c'])==len(x['monthly_precip_mm'])==12 for x in t)
    assert all(0<=v<=1 for x in t for v in x['hazards'].values())
    assert all(abs(sum(x['monthly_precip_mm'])-x['annual_precip_mm'])<=2 for x in t)
    assert all(abs(sum(x['monthly_temp_c'])/12-x['annual_mean_temp_c'])<=.5 for x in t)
    assert any(x['biome']=='alpine' for x in t)
    assert any(x['biome']=='desert' for x in t)
    assert any(x['biome']=='forest' for x in t)

def test_polities_are_land_connected():
    t={(v['col'],v['row']):v for v in WORLD['tiles']}
    for p in WORLD['polities']:
        coords={tuple(x) for x in p['initial_tiles']}
        cp=(p['capital']['col'],p['capital']['row'])
        assert cp in coords and len(coords)>=8
        assert all(t[c]['land'] for c in coords)
        seen={cp}
        while True:
            nxt={x for x in coords if x not in seen and any(hex_distance(x,y)==1 for y in seen)}
            if not nxt: break
            seen|=nxt
        assert seen==coords, (p['id'],'non-contiguous polity core')

def test_year_2000_bce_weather():
    assert WEATHER['days']==365
    assert len(WEATHER['monthly'])==12
    assert WEATHER['monthly'][-1]['sim_day']==365
    for event in WEATHER['events']:
        assert 0<=event['hex']['col']<W
        assert 0<=event['hex']['row']<H
        assert 0<=event['risk_index']<=1
