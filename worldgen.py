"""Project EOS v0.1: reproducible fictional continent, physically informed climate, hydrology, hazards.

Not a numerical weather prediction / general circulation model.
Requires: numpy, scipy, matplotlib. Run: python worldgen.py --output ./output --seed 2000
"""
from __future__ import annotations
import argparse
import heapq
import json
import math
from collections import deque
from pathlib import Path
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter, distance_transform_edt

W, H = 72, 54
R_KM = 34.0
CELL_AREA_KM2 = (3 * np.sqrt(3) / 2) * R_KM ** 2
DIR_EVEN = [(1,0),(0,-1),(-1,-1),(-1,0),(-1,1),(0,1)]
DIR_ODD = [(1,0),(1,-1),(0,-1),(-1,0),(0,1),(1,1)]
BIOME_COLORS = {
    'ocean':'#286486', 'alpine':'#a5abb6', 'tundra':'#adb6a2',
    'desert':'#ddb777','steppe':'#c7bc83','savanna':'#a5bd70',
    'grassland':'#8db579','forest':'#488b6c','rainforest':'#267559',
    'wetland':'#73a897'
}
POLITIES = [
    {'id':'ELAR','name':'埃兰河谷城邦联盟','type':'river_valley','government':'河谷城邦联盟','description':'依赖季节性河流泛滥与灌溉的粮食核心区；政治组织为若干城邦的盟约','population':37000},
    {'id':'MARIS','name':'玛瑞斯海湾城邦','type':'maritime','government':'沿海港口城邦','description':'依靠海湾贸易、渔业与沿海耕地的商贸聚落','population':21000},
    {'id':'VAYR','name':'维尔山麓诸侯','type':'highland','government':'山麓领主联盟','description':'控制山间谷地和浅层矿脉，冶金发展较快但农田有限','population':15500},
    {'id':'SAHAR','name':'萨赫尔河岸王国','type':'semiarid','government':'河岸灌溉王权','description':'在干旱边缘沿常流河布置灌溉田与聚落，依赖水利管理','population':28000},
]

def neighbors(x,y,w=W,h=H):
    for dx,dy in (DIR_ODD if y & 1 else DIR_EVEN):
        xx,yy=x+dx,y+dy
        if 0<=xx<w and 0<=yy<h:
            yield xx, yy

def hex_distance(a,b):
    x,y=a; x2,y2=b
    q=x-(y-(y&1))//2; q2=x2-(y2-(y2&1))//2
    dq=q-q2; dr=y-y2
    return (abs(dq)+abs(dr)+abs(dq+dr))//2

def smooth_noise(rng,h,w,sy,sx):
    from scipy.ndimage import zoom
    a=rng.normal(size=(sy,sx))
    b=zoom(a,(h/sy,w/sx),order=3)
    b=b[:h,:w]
    return (b-b.mean())/max(b.std(),1e-6)

def gen_base(seed, w=W, h=H):
    rng=np.random.default_rng(seed)
    Y,X=np.mgrid[0:h,0:w].astype(float)
    X=(X+(Y%2)*.5)/(w-.5); Y=Y/(h-1)
    lat=51.0 - Y*43.0
    n1=smooth_noise(rng,h,w,7,9)
    n2=smooth_noise(rng,h,w,15,18)
    n3=smooth_noise(rng,h,w,27,35)
    # Broad cratonic interior with gulfs and irregular coastal peninsulas.
    continental=(1.42*np.exp(-((abs((X-.49)/.45)**3.6)+(abs((Y-.49)/.54)**3.3)))
                +.23*np.exp(-(((X-.69)/.17)**2+((Y-.79)/.17)**2))
                -.30*np.exp(-(((X-.82)/.12)**2+((Y-.44)/.19)**2))
                +.16*n1+.075*n2+.035*n3)
    land=continental>.69
    # Simulated ocean beyond every map edge (no artificial edge-only continents).
    land[0,:]=False; land[-1,:]=False; land[:,0]=False; land[:,-1]=False
    main_ridge_x=.286+.057*np.sin(4.8*Y+0.2)
    west_ridge=np.exp(-((X-main_ridge_x)/.046)**2)*np.exp(-((Y-.47)/.34)**6)
    interior_x=.52+.22*(.56-Y)
    interior_ridge=np.exp(-((X-interior_x)/.035)**2)*np.exp(-((Y-.73)/.21)**4)
    upland=np.exp(-(((X-.53)/.17)**2+((Y-.32)/.18)**2))
    elev=(np.maximum(continental-.69,0)*820 + 2830*west_ridge
          + 1640*interior_ridge + 530*upland+130*np.maximum(n3,0))
    elev=np.where(land,elev,-(100+1400*np.maximum(.69-continental,0)))
    # Crude boundary / fault field; active arc approximates west ridge.
    fault=np.exp(-((X-main_ridge_x)/.065)**2)*np.exp(-((Y-.46)/.37)**6)
    fault=np.where(land,np.clip(fault,0,1),0)
    return rng,X,Y,lat,land,elev,fault,west_ridge

def gen_climate(rng,lat,land,elev,w=W,h=H,r_km=R_KM):
    # Maritime / continental moderation. East-west moisture carriage in simplified
    # Hadley/trade wind and mid-latitude westerly regimes.
    dist_ocean=distance_transform_edt(land)*r_km*1.7
    inland=np.minimum(dist_ocean/1000,1)
    tmean=30.8-.53*lat-.0060*np.maximum(elev,0)+.8*inland
    amp=1.2 + 7.2*lat/51 + 4.2*inland
    mtemp=np.stack([tmean-amp*np.cos(2*np.pi*m/12) for m in range(12)])
    # Broad latitude precipitation: ITCZ, subtropical dry belt, westerly storm belt.
    target=(520+970*np.exp(-((lat-11)/11)**2)
            +660*np.exp(-((lat-47)/12)**2)-390*np.exp(-((lat-28)/9)**2))
    p=np.zeros_like(elev)
    for y in range(h):
        order=range(w) if float(lat[y,0])>=29 else range(w-1,-1,-1)
        humidity=1.0; prev_h=0
        for x in order:
            if not land[y,x]:
                humidity=1.0;prev_h=0
                p[y,x]=max(900,target[y,x])
                continue
            z=max(float(elev[y,x]),0)
            uplift=max(0,z-prev_h)
            precip=(max(130,target[y,x])*(0.24+0.87*humidity)
                    *(1+1.5*min(uplift/1200,1.5)))
            p[y,x]=precip
            humidity=max(.22,humidity*.94-0.12*min(uplift/900,1))
            if z<prev_h-500:
                humidity=max(.22,humidity-.05)
            prev_h=z
    # Smoothed regional precipitation microstructure, including leeward drying.
    p *= np.clip(1+.13*gaussian_filter(rng.normal(size=(h,w)),sigma=max(0.5,2.0*R_KM/r_km)),.7,1.4)
    p=np.clip(p,70,3300)
    # Seasonal rainfall: summer monsoon at low latitudes, winter storms at high latitudes.
    monthly=[]
    for m in range(12):
        if m<12:
            # month 0 January, 6 July
            summer=np.cos(2*np.pi*(m-6)/12)
            lowlat=np.clip((32-lat)/20,0,1)
            winter=1-lowlat
            seas=(1+.59*lowlat*summer-.34*winter*summer)
            monthly.append(p/12*np.maximum(.14,seas))
    monthly=np.stack(monthly)
    monthly*=p/np.maximum(monthly.sum(axis=0),1)
    # Simplified biome classes: water availability, temperature and alpine climate.
    biome=np.full((h,w),'grassland',dtype=object)
    biome[~land]='ocean'
    dry_idx=p/np.maximum(250+18*np.maximum(tmean,0),1)
    biome[land & (dry_idx<.42)]='desert'
    biome[land & (dry_idx>=.42) & (dry_idx<.86)]='steppe'
    biome[land & (dry_idx>=.86) & (p<930)]='grassland'
    biome[land & (dry_idx>=.86) & (p>=930)]='forest'
    biome[land & (tmean>22) & (p>=950) & (p<1550)]='savanna'
    biome[land & (tmean>22) & (p>=1550)]='rainforest'
    biome[land & (tmean<3) & (elev<1800)]='tundra'
    biome[land & ((elev>2650)|(tmean<-4))]='alpine'
    return p,tmean,mtemp,monthly,biome,dist_ocean

def gen_hydrology(land,elev,p,w=W,h=H,r_km=R_KM,cell_area_km2=CELL_AREA_KM2,river_min_basin=17):
    # Priority flood ensures every flow path terminates in ocean; artificially
    # fills local pits to spill elevation. Tracks a parent for each land tile.
    visited=np.zeros((h,w),bool)
    fill=elev.copy(); parent=np.full((h,w,2),-1,int)
    heap=[]; order=[]
    for y in range(h):
        for x in range(w):
            if not land[y,x]:
                visited[y,x]=True
                heapq.heappush(heap,(float(elev[y,x]),y,x))
    while heap:
        level,y,x=heapq.heappop(heap)
        for nx,ny in neighbors(x,y,w,h):
            if visited[ny,nx]:continue
            visited[ny,nx]=True
            fill[ny,nx]=max(float(elev[ny,nx]),level+1e-4)
            parent[ny,nx]=[x,y]
            heapq.heappush(heap,(float(fill[ny,nx]),ny,nx))
            order.append((nx,ny))
    # Approx annual runoff: precipitation minus evapotranspiration and infiltration.
    local=np.where(land,np.maximum(p-310,20)/1000*cell_area_km2*1e6*.36,0)
    flow=local.copy(); basin=np.where(land,1,0).astype(int)
    for x,y in reversed(order):
        px,py=parent[y,x]
        if px<0:continue
        flow[py,px]+=flow[y,x]; basin[py,px]+=basin[y,x]
    # Channel headwater threshold 17 upstream cells; meanders not modeled.
    river=land & (basin>=river_min_basin) & (elev<3300)
    # Slope is max gradient to immediate neighboring tile, in km/km
    slope=np.zeros((h,w))
    for y in range(h):
        for x in range(w):
            slope[y,x]=max([abs(float(elev[y,x])-float(elev[ny,nx]))/(r_km*1.732*1000) for nx,ny in neighbors(x,y,w,h)] or [0])
    return parent,flow,basin,river,slope

def gen_hazards(land,elev,fault,biome,p,tmean,lat,river,basin,slope,dist_ocean,w=W,h=H,r_km=R_KM):
    # The following are relative exposure indices, NOT calibrated return periods.
    wetness=np.clip(p/1500,0,1)
    flat=np.exp(-slope*19)
    flood=np.clip((np.log1p(basin)/np.log(180))*flat*wetness*1.1,0,1)
    flood*=np.where(river,1,0.42)
    flood=np.where(land,flood,0)
    drought=np.where(land,np.clip((950-p)/780,0,1)*np.clip((tmean+2)/30,.2,1),0)
    coast=land & (dist_ocean<r_km*2.5)
    cyclone=np.where(coast & (lat<30) & (lat>8),np.clip((30-lat)/22,0,1)*.72,0)
    wildfire=np.where(land & np.isin(biome,['forest','savanna','grassland','steppe']),
                      np.clip((1100-p)/750,0,1)*np.clip((tmean+5)/33,0,1),0)
    earthquake=np.clip(.06+.86*fault,0,1)*land
    # Volcanic arc along active tectonic belt: deterministic point sources, geological not meteorological.
    eruption=np.zeros((h,w))
    fault_candidates=np.argwhere(land & (fault>.64) & (elev>1200))
    if len(fault_candidates):
        for idx in np.linspace(0,len(fault_candidates)-1,min(5,len(fault_candidates)),dtype=int):
            yy,xx=fault_candidates[idx]
            yyarr,xxarr=np.mgrid[:h,:w]
            sigma=max(1.0,4.3*R_KM/r_km)
            eruption=np.maximum(eruption,np.exp(-(((xxarr-xx)/sigma)**2+((yyarr-yy)/sigma)**2)))
    eruption*=fault*land
    return {'flood':flood,'drought':drought,'earthquake':earthquake,'volcano':eruption,
            'wildfire':wildfire,'cyclone':cyclone}

def pick_polities(land,elev,biome,p,tmean,river,basin,slope,dist_ocean,hazards,lat):
    # Site choices are derived from geographical suitability; distinct ecological
    # niches prevent the four founding states having nearly identical conditions.
    near_river=distance_transform_edt(~river)
    soil=np.clip((p-220)/950,0,1)*np.clip((1900-p)/750,.2,1)
    safe=1-.34*hazards['earthquake']-.26*hazards['flood']-.2*hazards['drought']
    arable=np.isin(biome,['grassland','forest','savanna','steppe','wetland'])
    base=soil*2+safe+1/(1+near_river)+.35*(1-slope)
    specs=[
      (land & arable & (elev<750) & (lat>19)&(lat<43)&(near_river<3)&(dist_ocean>120),
       base+.65*np.clip(np.log1p(basin)/7,0,1)+.4*(p>650)+.2*np.clip(dist_ocean/300,0,1)),
      (land & (dist_ocean<100) & (elev<600) & (p>480)&(lat>23)&(lat<45),
       base+1.6*np.clip((100-dist_ocean)/100,0,1)-hazards['earthquake']),
      (land & (elev>650)&(elev<1800)&(p>420)&(tmean>6)&(lat>25)&(lat<51),
       base+.8*np.clip(elev/1800,0,1)+.5*hazards['earthquake']),
      (land & (p>=180)&(p<590)&(lat>13)&(lat<41)&(near_river<3)&(dist_ocean>110),
       base+1.1*np.clip((750-p)/600,0,1)+.6*np.log1p(basin)/7),
    ]
    placed=[]; used=np.zeros((H,W),bool)
    for i,(valid,score) in enumerate(specs):
        loc=None
        for minimum_sep in (13,10,7,4):
            scores=np.where(valid,score,-1e8).copy()
            for xx,yy in placed:
                for y in range(H):
                    for x in range(W):
                        if hex_distance((x,y),(xx,yy))<minimum_sep:scores[y,x]=-1e8
            scores[used]=-1e8
            y,x=np.unravel_index(np.argmax(scores),scores.shape)
            if scores[y,x]>-1e6:
                loc=(int(x),int(y));break
        if loc is None:raise RuntimeError(f'No usable capital for {POLITIES[i]["id"]}')
        placed.append(loc)
        for y in range(H):
            for x in range(W):
                if hex_distance((x,y),loc)<=3:used[y,x]=True
    # Early Bronze Age states own compact cores, not the entire continent.
    ownership=np.full((H,W),'',dtype=object)
    results=[]
    for i,(capital,info) in enumerate(zip(placed,POLITIES)):
        x0,y0=capital
        area=[]
        for y in range(H):
            for x in range(W):
                d=hex_distance((x,y),capital)
                if land[y,x] and d<=2 and ownership[y,x]=='':
                    ownership[y,x]=info['id'];area.append([x,y])
        row=dict(info)
        row.update(capital={'col':x0,'row':y0,'q':x0-(y0-(y0&1))//2,'r':y0},
                   initial_tiles=area,
                   territorial_area_km2=round(len(area)*CELL_AREA_KM2),
                   avg_annual_temp_c=round(float(tmean[y0,x0]),1),
                   avg_annual_precip_mm=round(float(p[y0,x0])),
                   elevation_m=round(float(elev[y0,x0])),
                   river_distance_tiles=round(float(near_river[y0,x0]),1),
                   dominant_biome=str(biome[y0,x0]),
                   technology={'agriculture':1,'bronze_metallurgy':(2 if i==2 else 1),
                               'writing':int(i in (0,3))},
                   treasury_units=100,food_storage_units=160,
                   diplomatic_status='no_contact')
        results.append(row)
    return results,ownership

def weather_day(rng,day,monthly_rain,monthly_temp,land,weather_anomaly):
    # Spatially-correlated AR(1) synoptic weather proxy, on top of monthly means.
    shape=land.shape
    noise=gaussian_filter(rng.normal(size=shape),sigma=2.0)
    noise=noise/max(noise.std(),1e-6)
    a=.86*weather_anomaly+.14*noise
    # Standard 365-day year, with 31/28/31/... day months.
    mdays=[31,28,31,30,31,30,31,31,30,31,30,31]
    d=day%365
    m=next(m for m,cutoff in enumerate(np.cumsum(mdays)) if d<cutoff)
    rainy_chance=np.clip(.34+monthly_rain[m]/400, .23,.69)
    wet=rng.random(shape)<np.clip(rainy_chance+0.11*a,.10,.87)
    rain=(monthly_rain[m]/30)*wet/np.maximum(rainy_chance,.08)*np.exp(.25*np.clip(a,-2,2))
    temp=monthly_temp[m]+1.8*a+1.2*rng.normal(size=shape)
    snow=land & (temp<0) & (rain>0)
    return a,rain,temp,snow

def demo_weather_hazards(seed,land,monthly_rain,monthly_temp,hazards,polities,w=W,h=H):
    rng=np.random.default_rng(seed+91)
    a=np.zeros((h,w)); samples=[]; events=[]
    capital_lookup={p['id']:(p['capital']['row'],p['capital']['col']) for p in polities}
    recent_dry={k:0 for k in capital_lookup}
    # 360 days is illustrative climate variability, not an observational hindcast.
    mdays=[31,28,31,30,31,30,31,31,30,31,30,31]
    month_start=np.cumsum([0]+mdays)
    for day in range(365):
        a,rain,temp,snow=weather_day(rng,day,monthly_rain,monthly_temp,land,a)
        if day in (0,90,181,273,364):
            month=int(np.searchsorted(month_start,day,side='right'))
            samples.append({'day':day+1,'month':month,'capital_weather':{
                k:{'temperature_c':round(float(temp[y,x]),1),
                   'precipitation_mm':round(float(rain[y,x]),1),
                   'snow':bool(snow[y,x])}
                for k,(y,x) in capital_lookup.items()}})
        if day+1 in month_start[1:]:
            month=int(np.searchsorted(month_start,day,side='right'))
            for k,(y,x) in capital_lookup.items():
                # Weather-sensitive exposure is observed at capitals; event generation
                # avoids mechanically producing a disaster at every high-risk tile.
                dry=float(hazards['drought'][y,x])
                flood=float(hazards['flood'][y,x])
                quake=float(hazards['earthquake'][y,x])
                fire=float(hazards['wildfire'][y,x])
                risk_by_type={'洪涝':.014*flood,'干旱':.012*dry,
                              '地震':.004*quake,'野火':.006*fire}
                for typ,chance in risk_by_type.items():
                    if rng.random()<chance:
                        events.append({'day':day+1,'month':month,'polity_id':k,'type':typ,
                                       'relative_severity':round(float(rng.uniform(.15,.65)),2)})
    return samples,events

def package_world(seed,land,elev,lat,biome,p,tmean,monthly_rain,monthly_temp,parent,flow,basin,river,slope,hazards,polities,ownership,weather_samples,events):
    # Compact self-contained JSON, with a single tile object per hex.
    tiles=[]
    for y in range(H):
        for x in range(W):
            px,py=parent[y,x]
            tiles.append({'q':x-(y-(y&1))//2,'r':y,'col':x,'row':y,
                          'latitude_deg':round(float(lat[y,x]),2),
                          'land':bool(land[y,x]),'elevation_m':int(round(float(elev[y,x]))),
                          'biome':str(biome[y,x]),
                          'annual_mean_temp_c':round(float(tmean[y,x]),1),
                          'annual_precip_mm':int(round(float(p[y,x]))),
                          'monthly_temp_c':[round(float(v),1) for v in monthly_temp[:,y,x]],
                          'monthly_precip_mm':[round(float(v),1) for v in monthly_rain[:,y,x]],
                          'slope':round(float(slope[y,x]),4),
                          'river':bool(river[y,x]),'drainage_area_km2':int(basin[y,x]*CELL_AREA_KM2),
                          'downstream':{'col':int(px),'row':int(py)} if land[y,x] and px>=0 else None,
                          'hazards':{k:round(float(hazards[k][y,x]),3) for k in hazards},
                          'owner_id':str(ownership[y,x]) or None})
    return {'metadata':{'project':'Project Eos','version':'0.1.0','world_name':'埃欧斯大陆 / Eos Continent',
            'seed':seed,'world_year_bce':2000,'astronomical_year':-1999,'start_month':1,'day_count':0,
            'grid_type':'odd-r pointy-top hex','grid_width':W,'grid_height':H,
            'hex_radius_km':R_KM,'cell_area_km2':round(CELL_AREA_KM2,1),
            'assumed_planet':'Earth-like, 24h day, 365-day year, Northern Hemisphere',
            'latitude_range_deg':[8,51],
            'model_limitations':['not a general circulation model or weather forecast',
                'no physical plate dynamics / calibrated hazard return periods',
                'synthetic tectonic belts and monthly precipitation with stochastic daily perturbations',
                'sea level and orbital forcing fixed at initial epoch']},
            'world_summary':{'land_hexes':int(land.sum()),'ocean_hexes':int((~land).sum()),
                'land_area_km2':round(float(land.sum()*CELL_AREA_KM2)),
                'maximum_elevation_m':round(float(np.max(elev))),
                'river_hexes':int(river.sum()),
                'unclaimed_land_hexes':int(np.count_nonzero(land & (ownership=='')))},
            'polities':polities,'tiles':tiles,'weather_samples':weather_samples,
            'illustrative_hazard_events':events}

def plot_maps(out,land,elev,biome,p,river,parent,polities,hazards):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    from matplotlib import font_manager
    font_candidates = [
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        Path('C:/Windows/Fonts/msyh.ttc'),
        Path('C:/Windows/Fonts/simhei.ttf'),
        Path('/System/Library/Fonts/PingFang.ttc'),
    ]
    font_name = 'DejaVu Sans'
    for font_path in font_candidates:
        if font_path.is_file():
            font_manager.fontManager.addfont(str(font_path))
            font_name = font_manager.FontProperties(fname=str(font_path)).get_name()
            break
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    hexrad=1
    centers=np.zeros((H,W,2))
    vertices=[]
    for y in range(H):
        for x in range(W):
            cx=np.sqrt(3)*(x+.5*(y&1));cy=1.5*y
            centers[y,x]=[cx,cy]
            verts=[(cx+math.cos(math.radians(60*i-30)),cy+math.sin(math.radians(60*i-30))) for i in range(6)]
            vertices.append(verts)
    # note y coordinates grow toward south, render with inverted axis.
    def canvas(title,colors,river_overlay=True):
        fig,ax=plt.subplots(figsize=(17,12),dpi=160,facecolor='#f4f0e6')
        ax.set_facecolor('#f4f0e6')
        pc=PolyCollection(vertices,facecolors=colors,edgecolors=(.12,.24,.30,.12),linewidths=.18)
        ax.add_collection(pc)
        if river_overlay:
            for y in range(H):
                for x in range(W):
                    if not river[y,x]:continue
                    px,py=parent[y,x]
                    if px<0:continue
                    p0=centers[y,x];p1=centers[py,px]
                    ax.plot([p0[0],p1[0]],[p0[1],p1[1]],color='#3f98ce',lw=1.0,alpha=.92,zorder=3)
        ncolors=['#e8b365','#63a8b6','#cd817c','#b887c5']
        for i,poli in enumerate(polities):
            cp=poli['capital']; x=cp['col'];y=cp['row'];cx,cy=centers[y,x]
            for tx,ty in poli['initial_tiles']:
                txc,tyc=centers[ty,tx]
                ax.scatter([txc],[tyc],s=32,marker='h',facecolor=ncolors[i],edgecolor='#202e32',linewidth=.45,zorder=4)
            ax.scatter([cx],[cy],marker='*',s=170,c=ncolors[i],edgecolors='black',linewidth=.75,zorder=7)
            ox=8 if x<W/2 else -8
            ha='left' if ox>0 else 'right'
            ax.annotate(poli['name'],(cx,cy),xytext=(ox,(-12 if i%2 else 14)),textcoords='offset points',
                fontsize=11,fontweight='bold',color='#192d38',ha=ha,va='center',zorder=9,
                bbox=dict(facecolor='#fffaf0',alpha=.84,boxstyle='round,pad=.24',edgecolor='none'))
        ax.set_xlim(-2,np.sqrt(3)*(W+1));ax.set_ylim(1.5*(H+1),-2)
        ax.set_aspect('equal');ax.axis('off')
        ax.set_title(title,fontsize=21,fontweight='bold',pad=18,color='#172c3b')
        return fig,ax
    cols=[BIOME_COLORS[str(biome[y,x])] for y in range(H) for x in range(W)]
    fig,ax=canvas('埃欧斯大陆 · 公元前 2000 年 · 地形、生物群系与早期国家',cols)
    fig.text(.05,.045,'六边形尺度：半径 34 km  |  蓝线：主要河流  |  ★：初始都城  |  彩色六边形：国家核心领土',size=11,color='#304852')
    fig.savefig(out/'world_map.png',bbox_inches='tight',pad_inches=.22);plt.close(fig)
    norm=Normalize(vmin=0,vmax=2200)
    cm=plt.get_cmap('YlGnBu')
    cols=[cm(norm(p[y,x])) if land[y,x] else (.15,.37,.52,1) for y in range(H) for x in range(W)]
    fig,ax=canvas('埃欧斯大陆 · 年均降水量（毫米）',cols)
    cbar=fig.colorbar(ScalarMappable(norm=norm,cmap=cm),ax=ax,fraction=.025,pad=.02,shrink=.62)
    cbar.set_label('mm / year')
    fig.savefig(out/'rainfall_map.png',bbox_inches='tight',pad_inches=.22);plt.close(fig)
    norm=Normalize(vmin=0,vmax=1)
    cm=plt.get_cmap('OrRd')
    composite=np.maximum.reduce([hazards[k]*w for k,w in [('earthquake',1),('flood',1),('drought',1),('wildfire',.9),('cyclone',.9),('volcano',1)]])
    cols=[cm(norm(composite[y,x])) if land[y,x] else (.15,.37,.52,1) for y in range(H) for x in range(W)]
    fig,ax=canvas('埃欧斯大陆 · 综合自然灾害暴露指数（相对值）',cols,False)
    cbar=fig.colorbar(ScalarMappable(norm=norm,cmap=cm),ax=ax,fraction=.025,pad=.02,shrink=.62)
    cbar.set_label('Relative hazard exposure 0–1')
    fig.savefig(out/'hazard_map.png',bbox_inches='tight',pad_inches=.22);plt.close(fig)

def validate(world):
    assert len(world['tiles'])==W*H
    assert sum(t['land'] for t in world['tiles'])==world['world_summary']['land_hexes']
    all_occupied=set()
    for poli in world['polities']:
        assert poli['initial_tiles']
        capital=(poli['capital']['col'],poli['capital']['row'])
        assert capital in [tuple(c) for c in poli['initial_tiles']]
        for c in poli['initial_tiles']:
            assert tuple(c) not in all_occupied, 'overlapping states'
            all_occupied.add(tuple(c))
    tiles={(t['col'],t['row']):t for t in world['tiles']}
    for t in world['tiles']:
        if not t['land']:continue
        cur=t;seen=set()
        for i in range(W*H):
            key=(cur['col'],cur['row'])
            assert key not in seen,'river drainage loop'
            seen.add(key)
            dest=cur['downstream']
            assert dest is not None,'land not connected to downstream'
            nxt=tiles[(dest['col'],dest['row'])]
            assert hex_distance(key,(nxt['col'],nxt['row']))==1, 'nonlocal river flow'
            if not nxt['land']:break
            cur=nxt
        else:raise AssertionError('drainage not reaching sea')
    return True

def generate(out:Path, seed:int):
    out.mkdir(parents=True,exist_ok=True)
    rng,X,Y,lat,land,elev,fault,ridge=gen_base(seed)
    p,tmean,monthly_temp,monthly_rain,biome,dist_ocean=gen_climate(rng,lat,land,elev)
    parent,flow,basin,river,slope=gen_hydrology(land,elev,p)
    hazards=gen_hazards(land,elev,fault,biome,p,tmean,lat,river,basin,slope,dist_ocean)
    polities,ownership=pick_polities(land,elev,biome,p,tmean,river,basin,slope,dist_ocean,hazards,lat)
    weather_samples,events=demo_weather_hazards(seed,land,monthly_rain,monthly_temp,hazards,polities)
    world=package_world(seed,land,elev,lat,biome,p,tmean,monthly_rain,monthly_temp,parent,flow,basin,river,slope,hazards,polities,ownership,weather_samples,events)
    validate(world)
    (out/'world_2000BCE.json').write_text(json.dumps(world,ensure_ascii=False,indent=1),encoding='utf-8')
    plot_maps(out,land,elev,biome,p,river,parent,polities,hazards)
    summary={k:v for k,v in world.items() if k!='tiles'}
    (out/'world_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'seed':seed,**world['world_summary'],
          'polities':[{k:p[k] for k in ('name','capital','dominant_biome','avg_annual_precip_mm','territorial_area_km2')} for p in polities],
          'files':[x.name for x in out.iterdir()]},ensure_ascii=False,indent=2))
    return world

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--seed',type=int,default=2000)
    parser.add_argument('--output',type=Path,default=Path('output'))
    args=parser.parse_args()
    generate(args.output,args.seed)
