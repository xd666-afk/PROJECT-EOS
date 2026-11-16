from copy import deepcopy
from pathlib import Path
import pytest
from core import monthly, situations
from core.simulation import Simulation
from core.replay import replay_saved_actions
from core.state import GameState

ROOT=Path(__file__).resolve().parents[1]


def simulation():
    sim=Simulation.new(use_mock_agents=False)
    sim.engine.enable_city_manager=False;sim.engine.enable_frontier_ai=False
    return sim


@pytest.mark.parametrize('month,length',[(0,31),(1,28),(2,31),(3,30),(11,31),(12,31)])
def test_natural_month_has_actual_length(month,length):
    start=monthly.month_start(month)
    assert monthly.after_months(start,1)-start==length
    assert monthly.month_index(start)==month
    assert monthly.months_for_days(start,length)==1
    assert monthly.months_for_days(start,length+1)==2


def test_month_is_atomic_pause_force_and_midmonth_migration():
    sim=simulation();sim.step(2)
    before=deepcopy(sim.state.countries['ELAR'].to_dict())
    sim.pause();assert sim.run_months(1)==0
    assert sim.state.day_index==2 and sim.state.countries['ELAR'].to_dict()==before
    assert sim.step_months(1)==1
    assert sim.state.day_index==31
    assert sim.state.monthly_ledger['settled_days']==29
    assert sim.state.time_unit=='month'
    assert '日' not in monthly.calendar(sim.state)['label']


def test_monthly_economy_sums_every_settlement_and_preserves_balance():
    sim=simulation();reference=simulation()
    sums={}
    for _ in range(31):
        reference.step()
        for key in monthly.SUM_METRICS:
            sums[key]=sums.get(key,0)+reference.state.countries['ELAR'].last_economy.get(key,0)
    sim.step_months()
    actual=sim.state.monthly_ledger['countries']['ELAR']
    for key,value in sums.items():assert actual.get(key,0)==pytest.approx(value)
    result=sim.state.countries['ELAR'].to_dict()
    result['last_economy'].pop('military_upkeep')  # Added monthly bookkeeping, not a balance change.
    assert result==reference.state.countries['ELAR'].to_dict()


def test_monthly_planner_runs_once_per_month_and_never_midmonth():
    class Planner:
        def __init__(self):self.days=[]
        def plan(self,engine,**_kwargs):self.days.append(engine.state.day_index)
    sim=simulation();planner=Planner();sim.engine.planner=planner
    sim.step_months(3)
    assert planner.days==[0,31,59]
    assert sim.state.day_index==90


def test_monthly_army_maintenance_records_actual_payments():
    sim=simulation();monthly.enable(sim.state)
    country=sim.state.countries['ELAR'];country.treasury=10000
    country.new_army(tile=country.cities[0].center,units={'MILITIA':3})
    charges=[];upkeep=sim.engine.military.upkeep_daily
    def measured():
        before=country.treasury;upkeep();charges.append(before-country.treasury)
    sim.engine.military.upkeep_daily=measured
    sim.step_months()
    assert sim.state.monthly_ledger['countries']['ELAR']['military_upkeep']==pytest.approx(sum(charges))


def test_monthly_cli_load_uses_the_saved_world_instead_of_default_baseline(tmp_path):
    from run_simulation import build_parser
    args=build_parser().parse_args(['run','--load',str(ROOT/'examples/civil_networks/save.json'),
        '--no-agents','--months','1','--save',str(tmp_path/'save.json'),'--log',str(tmp_path/'events.jsonl'),
        '--snapshots',str(tmp_path/'snapshots.json'),'--api-usage',str(tmp_path/'usage.json')])
    assert args.handler(args)==0
    restored=GameState.load(tmp_path/'save.json')
    assert restored.time_unit=='month' and restored.day_index==31
    assert replay_saved_actions(tmp_path/'save.json').fingerprint()==restored.fingerprint()


def test_legacy_active_events_round_up_without_changing_world():
    sim=simulation();item=situations.create(sim.state,{'preset_id':'drought','country_id':'ELAR','duration':5})
    sim.step(2);before=sim.state.countries['ELAR'].to_dict()
    monthly.enable(sim.state)
    assert sim.state.countries['ELAR'].to_dict()==before
    assert sim.state.situations[item['id']]['end_day']==31
    sim.step_months()
    assert sim.state.situations[item['id']]['status']=='ended'


def test_saved_month_ledger_and_weather_resume_exactly(tmp_path):
    sim=simulation();sim.step_months(2)
    path=sim.state.save(tmp_path/'monthly.json')
    restored=Simulation.load(path,use_mock_agents=False)
    restored.engine.enable_city_manager=False;restored.engine.enable_frontier_ai=False
    assert restored.state.monthly_ledger==sim.state.monthly_ledger
    sim.step_months();restored.step_months()
    assert restored.state.fingerprint()==sim.state.fingerprint()


def test_monthly_replay_preserves_commands_and_ledger(tmp_path):
    sim=simulation();monthly.enable(sim.state)
    item=situations.create(sim.state,{'preset_id':'confidence','country_id':'ELAR','duration':59})
    sim.engine.apply_action('ELAR',{'type':'SET_POLICY','priority':'AGRICULTURE'})
    sim.step_months()
    situations.update(sim.state,item['id'],{'remaining_days':28,'intensity':3})
    sim.step_months()
    path=sim.state.save(tmp_path/'monthly-replay.json')
    restored=replay_saved_actions(path)
    assert restored.fingerprint()==sim.state.fingerprint()


def test_public_month_fields_keep_engine_compatibility_fields():
    sim=simulation();monthly.enable(sim.state)
    data=monthly.decorate({'day':0,'march':{'days_left':31},'daily_cost':2,'date':'公元前2000年1月1日','started_day':31,'applied_day':59,'reason_text':'约 40 天，超过命令上限'},sim.state)
    assert data['march']=={'days_left':31,'months_left':1}
    assert data['monthly_cost']==62 and data['daily_cost']==2
    assert data['month_number']==1 and data['month_date']=='公元前2000年1月'
    assert data['started_month']==2 and data['applied_month']==3
    assert data['monthly_reason_text']=='约 2 个月，超过命令上限'


def test_serialization_preserves_the_snapshot_month_if_clock_has_advanced():
    sim=simulation();monthly.enable(sim.state)
    snapshot={'day':sim.state.day_index,'calendar':monthly.calendar(sim.state)}
    sim.step_months()
    result=monthly.decorate(snapshot,sim.state)
    assert result['calendar']['month_number']==1 and result['month_number']==1
    assert result['calendar']['days']==31


def test_project_months_reflect_workers_and_disruption():
    sim=simulation();sim.state.day_index=31;monthly.enable(sim.state)
    country=sim.state.countries['ELAR'];country.policy='BALANCED'
    country.workers['construction']=sim.state.config['workers_baseline']['construction']
    assert monthly.construction_months(sim.state,country,20)==1
    situations.create(sim.state,{'preset_id':'work_delay','country_id':'ELAR','duration':28})
    assert monthly.construction_months(sim.state,country,20)==2
    country.workers['construction']=0
    assert monthly.construction_months(sim.state,country,20) is None


def test_live_session_rejects_day_events_and_steps_a_whole_month(tmp_path,monkeypatch):
    import live_server
    monkeypatch.setattr(live_server,'SAVE_DIR',tmp_path/'saves')
    session=live_server.LiveSession(paused=True,load_path=ROOT/'examples/civil_networks/save.json')
    try:
        with pytest.raises(ValueError,match='按月'):
            session.change_situation({'operation':'create','event':{'preset_id':'drought','country_id':'A','duration':1}})
        first=session.change_situation({'operation':'create','event':{'preset_id':'drought','country_id':'A','duration_months':2}})['situation']
        assert first['remaining_months']==2
        session.control('step_month')
        assert session.simulation.state.day_index==31
        assert session.situation_payload(first['id'])['situation']['remaining_months']==1
        session.control('step')
        assert session.simulation.state.day_index==59
        assert session.situation_payload(first['id'])['situation']['status']=='ended'
        assert session.snapshot()['countries']['A']['monthly_economy']['estimated'] is False
    finally:session.stop()


@pytest.mark.parametrize('failure',[RuntimeError,KeyboardInterrupt])
def test_failed_month_rolls_back_resources_clock_rng_and_uncommitted_log(failure):
    sim=simulation();monthly.enable(sim.state)
    before=sim.state.fingerprint();events=[];sim.state.add_listener(events.append)
    settle=sim.engine.economy.settle_all
    def failing(weather):
        settle(weather)
        if sim.state.day_index==3:raise failure('injected settlement failure')
    sim.engine.economy.settle_all=failing
    with pytest.raises(failure):sim.step_months()
    assert sim.state.fingerprint()==before
    assert events==[]
    sim.engine.economy.settle_all=settle
    sim.step_months()
    assert sim.state.day_index==31
    assert events[-1]['type']=='monthly_settlement'


def test_readers_cannot_observe_an_incomplete_month(tmp_path,monkeypatch):
    import live_server
    import threading
    monkeypatch.setattr(live_server,'SAVE_DIR',tmp_path/'saves')
    session=live_server.LiveSession(paused=True,load_path=ROOT/'examples/civil_networks/save.json')
    entered=threading.Event();release=threading.Event();read=threading.Event();result=[]
    settle=session.simulation.engine.economy.settle_all
    def blocking(weather):
        entered.set();release.wait(5);settle(weather)
    session.simulation.engine.economy.settle_all=blocking
    worker=threading.Thread(target=lambda:session.control('step_month'))
    reader=threading.Thread(target=lambda:(result.append(session.snapshot()['day']),read.set()))
    try:
        worker.start();assert entered.wait(5)
        reader.start();assert not read.wait(.05)
        release.set();worker.join(10);reader.join(10)
        assert result==[31]
    finally:
        release.set();worker.join(10)
        if reader.ident:reader.join(10)
        session.stop()
