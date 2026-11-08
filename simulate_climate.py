"""Run a reproducible year of daily stochastic weather and hazard sampling.

This is a physically informed weather generator conditioned on seasonal climatology,
NOT a scientific forecasting model; hazards are exposure-weighted scenario events.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from worldgen import H,W,weather_day

MONTH_DAYS=[31,28,31,30,31,30,31,31,30,31,30,31]
MONTH_END=np.cumsum(MONTH_DAYS)

def run(world_path:Path,out:Path,seed:int,days:int=365):
    world=json.loads(world_path.read_text(encoding='utf-8'))
    tiles=world['tiles']
    assert len(tiles)==W*H
    land=np.array([t['land'] for t in tiles]).reshape(H,W)
    temp=np.array([t['monthly_temp_c'] for t in tiles]).reshape(H,W,12).transpose(2,0,1)
    rain_norm=np.array([t['monthly_precip_mm'] for t in tiles]).reshape(H,W,12).transpose(2,0,1)
    hazards={typ:np.array([t['hazards'][typ] for t in tiles]).reshape(H,W) for typ in tiles[0]['hazards']}
    owner=np.array([t['owner_id'] or '' for t in tiles],dtype=object).reshape(H,W)
    capitals={p['id']:(p['capital']['row'],p['capital']['col']) for p in world['polities']}
    rng=np.random.default_rng(seed)
    anom=np.zeros((H,W))
    month_rain=np.zeros((H,W));month_temp=np.zeros((H,W));month_days=0
    monthly_results=[];events=[]
    for day in range(days):
        anom,pr,tc,snow=weather_day(rng,day,rain_norm,temp,land,anom)
        month_rain+=pr;month_temp+=tc;month_days+=1
        doy=(day%365)+1
        if doy not in MONTH_END and day!=days-1:continue
        month=int(np.searchsorted(MONTH_END,doy,side='left'))
        observed=month_rain
        expected=rain_norm[month]*(month_days/MONTH_DAYS[month])
        rratio=observed/np.maximum(expected,1.0)
        tavg=month_temp/max(month_days,1)
        summary={'sim_day':day+1,'month':month+1,
            'average_land_temp_c':round(float(tavg[land].mean()),1),
            'average_land_rain_mm':round(float(observed[land].mean()),1),
            'polities':{k:{'temp_c':round(float(tavg[y,x]),1),
                            'rain_mm':round(float(observed[y,x]),1),
                            'expected_rain_mm':round(float(expected[y,x]),1),
                            'rain_anomaly_ratio':round(float(rratio[y,x]),2)}
                         for k,(y,x) in capitals.items()}}
        monthly_results.append(summary)
        # Each type generates possible continental events. Arbitrary relative
        # rates: for a playable prototype, not calibrated historical return periods.
        specs=[('洪水',.85,'flood'),('干旱',.48,'drought'),('地震',.30,'earthquake'),
               ('野火',.38,'wildfire'),('热带气旋',.24 if month in (5,6,7,8,9) else .015,'cyclone'),
               ('火山活动',.027,'volcano')]
        for label,rate,kind in specs:
            risk=hazards[kind]*land
            # Ignore negligible local exposure when drawing named incidents.
            min_exposure={'flood':.16,'drought':.19,'earthquake':.23,
                          'wildfire':.21,'cyclone':.18,'volcano':.25}[kind]
            risk=np.where(risk>=min_exposure,risk,0.0)
            if kind=='flood':risk=risk*np.clip(rratio-.72,0.06,2.0)
            if kind=='drought':risk=risk*np.clip(1.22-rratio,0.06,2.0)
            if kind=='wildfire':risk=risk*np.clip(1.1-rratio,0.1,2)*np.clip((tavg-10)/20,.05,1)
            if kind=='cyclone':risk=risk*np.clip((tavg-18)/11,0,1)
            flat=risk.ravel()
            if flat.sum()<=0:continue
            n=min(int(rng.poisson(rate)),4)
            for _ in range(n):
                idx=int(rng.choice(flat.size,p=flat/flat.sum()))
                y,x=divmod(idx,W)
                events.append({'sim_day':day+1,'month':month+1,'type':label,
                               'hex':{'col':x,'row':y},
                               'risk_index':round(float(hazards[kind][y,x]),3),
                               'severity':round(float(rng.uniform(.15,.88)),2),
                               'affected_polity_id':str(owner[y,x]) or None})
        month_rain.fill(0);month_temp.fill(0);month_days=0
    result={'model':'EOS stochastic weather + hazard exposure sampler v0.1',
            'seed':seed,'days':days,'starts_at':'公元前2000年1月1日（虚构统一历）',
            'notes':['365-day calendar (non-leap baseline)',
                     'synthetic weather, not reconstructed ancient weather',
                     'event rates are illustrative, not historical return periods',
                     'temperature and rain are climate-conditioned stochastic processes'],
            'monthly':monthly_results,'events':events}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'days':days,'months':len(monthly_results),'events':len(events),
                      'event_types':sorted(set(e['type'] for e in events)),'file':str(out)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--world',type=Path,default=Path('output/world_2000BCE.json'))
    p.add_argument('--out',type=Path,default=Path('output/first_year_weather.json'))
    p.add_argument('--seed',type=int,default=2000)
    p.add_argument('--days',type=int,default=365)
    args=p.parse_args();run(args.world,args.out,args.seed,args.days)
