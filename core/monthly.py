"""Natural-month game transactions over the deterministic legacy settlement kernel."""
from __future__ import annotations
from copy import deepcopy
import math
import re

MONTH_DAYS=(31,28,31,30,31,30,31,31,30,31,30,31)
SUM_METRICS={'food_production','food_consumption','food_shortage','food_overflow','food_logistics_loss',
             'city_service_spend','city_food_surplus','city_food_deficit','rural_food_output',
             'tax_income','mine_income','upkeep','treasury_income','population_loss','military_upkeep'}
CITY_METRICS=('food_output','food_need','food_balance','food_loss','food_imported','food_exported',
              'food_unmet','local_revenue','local_upkeep','local_net')


def month_index(day):
    years,remainder=divmod(max(0,int(day)),365)
    month=0
    while remainder>=MONTH_DAYS[month]:
        remainder-=MONTH_DAYS[month];month+=1
    return years*12+month


def month_start(index):
    years,month=divmod(max(0,int(index)),12)
    return years*365+sum(MONTH_DAYS[:month])


def after_months(day,count):
    return month_start(month_index(day)+count)


def months_for_days(day,days):
    if days is None:return None
    if float(days)<=0:return 0
    return max(1,month_index(day+math.ceil(float(days))-1)-month_index(day)+1)


def construction_months(state,country,remaining):
    from core.situations import factor
    base=state.config['workers_baseline']['construction']
    rate=(country.workers['construction']/base if base else 1)*state.config['policies'][country.policy]['construction']
    rate*=factor(state,country.country_id,'construction')
    return months_for_days(state.day_index,remaining/rate) if rate>0 else None


def road_months(state,country,quote):
    from core.situations import factor
    baseline=state.config['workers_baseline']['construction']
    rate=(country.workers['construction']/baseline if baseline else 1)*state.config['policies'][country.policy]['construction']
    rate*=factor(state,country.country_id,'construction')
    if rate<=0:return None
    pending={tuple(p) for p in quote.get('pending_tiles',[])}
    work=[row['days'] for row in quote['segments']]+[p['remaining_days'] for p in country.projects if tuple(p['tile']) in pending]
    days=sum(math.ceil(max(0,value)/rate) for value in work)
    return months_for_days(state.day_index,days)


def month_label(day,start_year=-1999):
    index=month_index(day);year=start_year+index//12
    prefix=f'公元前{1-year}年' if year<=0 else f'公元{year}年'
    return prefix+str(index%12+1)+'月'


def calendar(state):
    index=month_index(state.day_index)
    return {'month_index':index,'month_number':index+1,'label':month_label(state.day_index,state.start_astronomical_year),
            'days':MONTH_DAYS[index%12],'remaining_days':after_months(state.day_index,1)-state.day_index}


def enable(state):
    if state.time_unit=='month':return
    # Do not replay or discard an already settled partial month from an old save.
    adjustments=[]
    for item in state.situations.values():
        if item['status']!='active':continue
        previous=item['end_day']
        remaining=months_for_days(state.day_index,max(1,previous-state.day_index))
        item['end_day']=after_months(state.day_index,remaining)
        adjustments.append({'id':item['id'],'previous_end_day':previous,'end_day':item['end_day']})
    state.time_unit='month'
    state.record('monthly_time_migrated',country_id=None,adjustments=adjustments,
                 legacy_research_progress={cid:deepcopy(c.research_progress) for cid,c in state.countries.items()},
                 note='保留世界状态与月内已结算进度，之后按自然月推进')


def begin_period(state):
    return {'month_index':month_index(state.day_index),'label':month_label(state.day_index,state.start_astronomical_year),
            'start_day':state.day_index,'end_day':after_months(state.day_index,1),'settled_days':0,
            'countries':{},'cities':{}}


def collect(state,period):
    period['settled_days']+=1
    for cid,country in state.countries.items():
        target=period['countries'].setdefault(cid,{})
        for key,value in country.last_economy.items():
            if isinstance(value,(int,float)):
                target[key]=target.get(key,0)+float(value) if key in SUM_METRICS else float(value)
        for city in country.cities:
            values=period['cities'].setdefault(city.city_id,{})
            for key in CITY_METRICS:values[key]=values.get(key,0)+float(getattr(city,key,0))


def finish_period(state,period):
    state.monthly_ledger=period
    state.record('monthly_settlement',month_index=period['month_index'],settled_days=period['settled_days'],
                 period_label=period['label'],end_day=state.day_index)


def economy_view(state,country):
    settled=state.monthly_ledger.get('countries',{}).get(country.country_id)
    if settled is not None:
        return {**deepcopy(settled),'estimated':False,'settled_days':state.monthly_ledger['settled_days'],
                'partial':state.monthly_ledger['start_day']!=month_start(state.monthly_ledger['month_index']),
                'period_label':state.monthly_ledger['label']}
    days=calendar(state)['remaining_days']
    return {key:value*days if key in SUM_METRICS else value for key,value in country.last_economy.items()}|{
        'estimated':True,'settled_days':days,'period_label':calendar(state)['label']}


def decorate(payload,state):
    """Add explicit monthly counterparts; legacy engine fields keep their original units."""
    now=payload.get('day',state.day_index) if isinstance(payload,dict) else state.day_index
    now=now if type(now) is int else state.day_index
    days=MONTH_DAYS[month_index(now)%12]
    duration_keys={'days':'months','days_left':'months_left','remaining_days':'remaining_months',
                   'estimated_days':'estimated_months','duration_days':'duration_months','total_days':'total_months',
                   'capture_tribute_days':'capture_tribute_months','days_needed':'months_needed'}
    time_keys={'day':'month_number','start_day':'start_month','end_day':'end_month','ended_day':'ended_month',
               'created_day':'created_month','expires_day':'expires_month','resolved_day':'resolved_month',
               'arrival_day':'arrival_month','founded_day':'founded_month','source_day':'source_month',
               'maximum_day':'maximum_month_number','tested_day':'tested_month',
               'started_day':'started_month','applied_day':'applied_month'}
    def walk(value):
        if isinstance(value,list):return [walk(v) for v in value]
        if not isinstance(value,dict):return value
        result={key:walk(v) for key,v in value.items()}
        for key,v in value.items():
            if key in duration_keys and (v is None or isinstance(v,(int,float))):result.setdefault(duration_keys[key],months_for_days(now,v))
            if key in time_keys and type(v) is int:result[time_keys[key]]=month_index(v)+1
            if isinstance(v,(int,float)) and not isinstance(v,bool):
                if key=='daily':result['monthly']=v*days
                if key.startswith('daily_'):result['monthly_'+key[6:]]=v*days
                if key.endswith('_per_day'):result[key[:-8]+'_per_month']=v*days
            if key=='date' and isinstance(v,str):result['month_date']=re.sub(r'(\d+月)\d+日',r'\1',v)
            elif key.endswith('_date') and isinstance(v,str):result[key[:-5]+'_month_date']=re.sub(r'(\d+月)\d+日',r'\1',v)
            if key in {'hint','reason_text'} and isinstance(v,str):
                result['monthly_'+key]=re.sub(r'约 (\d+) 天',lambda m:f'约 {months_for_days(now,int(m[1]))} 个月',v)
        return result
    result=walk(payload)
    if isinstance(result,dict) and 'road_permits' in result:
        for cid,entries in result['road_permits'].items():
            if cid not in state.countries:continue
            for entry in entries.values():entry['months']=construction_months(state,state.countries[cid],entry['days'])
    if isinstance(result,dict):
        result['time_unit']='month'
        result['calendar']=deepcopy(payload.get('calendar')) if isinstance(payload.get('calendar'),dict) else calendar(state)
    return result


def situation_view(state,item,detailed=False):
    from core import situations
    value=situations.snapshot(state,item,detailed)
    current=state.day_index if item['status']=='active' else item['ended_day']
    value.update(start_month=month_index(item['start_day'])+1,end_month=month_index(item['end_day'])+1,
                 ended_month=month_index(item['ended_day'])+1 if item['ended_day'] is not None else None,
                 elapsed_months=max(0,month_index(current)-month_index(item['start_day'])),
                 remaining_months=max(0,month_index(item['end_day'])-month_index(state.day_index)) if item['status']=='active' else 0,
                 duration_months=max(1,month_index(item['end_day'])-month_index(item['start_day'])))
    value['progress']=1. if item['status']!='active' else min(1.,value['elapsed_months']/value['duration_months'])
    value['monthly_milestones']={key:month_index(day)+1 for key,day in item.get('milestones',{}).items()}
    if value.get('chronicle'):
        value['month_chronicle']=re.sub(r'^第 \d+—\d+ 日',f"第 {value['start_month']}—{value['ended_month']} 月",value['chronicle'])
    for row in value.get('history',[]):
        row['month_number']=month_index(row.get('source_day',row['day']))+1
    return value
