"""Real UI/API acceptance for forbidden water placement and legacy repair."""
import argparse
from pathlib import Path
import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def verify(output):
    import live_server
    from core.terrain import is_water
    from playwright.sync_api import sync_playwright
    output.mkdir(parents=True,exist_ok=True);errors=[]
    with tempfile.TemporaryDirectory(prefix='eos-water-') as temp:
        live_server.SAVE_DIR=Path(temp)/'saves'
        session=live_server.LiveSession(paused=True,load_path=ROOT/'examples/civil_networks/save.json')
        state=session.simulation.state
        cid,country,city,water=next((cid,c,city,p) for cid,c in state.countries.items() for city in c.cities
                                  for p in city.tiles if state.world.tile(p).get('river'))
        country.treasury=10000;country.technology['agriculture']=10;city.managed_by='manual'
        country.buildings[water]='GRANARY';city.zones[water]='residential'
        session.save_current('水面规则验收')
        session.load_game(session.current_save_id)
        country=session.simulation.state.countries[cid]
        assert water not in country.buildings and country.cities[0].zones[water]=='unzoned'
        assert 'GRANARY' in country.buildings.values()
        class Handler(live_server.Handler):
            def log_message(self,*_args):pass
        Handler.session=session
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/?play=latest');page.wait_for_function('gameLoaded&&STATE?.countries')
                page.locator('#reopenLeft').click();page.locator('#realmPicker').select_option(cid)
                page.locator('#interveneBtn').click();page.wait_for_function('id=>STATE.player_country===id',arg=cid)
                page.evaluate('p=>{selectStrategyTile(p);showStrategyInspector("build")}',list(water))
                assert page.locator('[data-build="FARM"]').is_disabled()
                assert page.locator('[data-build="GRANARY"]').is_disabled()
                assert page.locator('.water-building-notice').is_visible()
                page.screenshot(path=str(output/'water-world.png'))
                assert '水面不能放置建筑' in page.locator('#panel-tile').text_content(),page.locator('#panel-tile').text_content()
                before=page.evaluate('STATE.countries[STATE.player_country].treasury')
                response=page.request.post(base+'/api/action',data={'actor':cid,'action':{
                    'type':'BUILD','building':'FARM','tile':{'col':water[0],'row':water[1]}}}).json()
                assert not response['ok'] and response['result']['reason_code']=='WATER_TILE'
                assert page.request.get(base+'/api/state').json()['countries'][cid]['treasury']==before
                page.evaluate('async id=>{await openDeck("city",true);openCityDetail(id)}',city.city_id)
                page.wait_for_selector('#cityDetail:not([hidden])')
                page.evaluate('p=>{selectedCityTile=p;renderCityDetail()}',list(water))
                assert page.locator('[data-city-build="FARM"]').is_disabled()
                assert page.locator('[data-city-build="IRRIGATION"]').is_disabled()
                for zone in ('farm','industry','residential','commerce','scholar'):
                    assert page.locator(f'[data-zone="{zone}"]').is_disabled()
                page.screenshot(path=str(output/'water-city.png'))
                assert not errors,errors
                browser.close()
            result={'javascript_errors':errors,'legacy_facility_relocated':True,'water_zones_cleared':True,
                    'world_menu_blocks_water':True,'city_menu_blocks_water':True,'direct_api_rejected_without_charge':True}
            (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
        finally:server.shutdown();server.server_close();session.stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'runs/ui_checks/water')
    args=parser.parse_args();print(json.dumps(verify(args.output),ensure_ascii=False,indent=2))
