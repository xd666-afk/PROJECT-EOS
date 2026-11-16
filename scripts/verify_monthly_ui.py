"""Real HTTP/browser acceptance for atomic monthly play and all visible time units."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def verify(output):
    import live_server
    from playwright.sync_api import sync_playwright
    output.mkdir(parents=True,exist_ok=True)
    errors=[]
    with tempfile.TemporaryDirectory(prefix='eos-monthly-') as temp:
        live_server.SAVE_DIR=Path(temp)/'saves'
        session=live_server.LiveSession(paused=True,load_path=ROOT/'examples/civil_networks/save.json')
        country=session.simulation.state.countries['A'];country.treasury=10000
        army=country.new_army(tile=country.cities[0].center,units={'MILITIA':1})
        session.save_current('月度验收专用')

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
                page.on('pageerror',lambda err:errors.append(str(err)))
                page.goto(base+'/?play=latest')
                page.wait_for_function('gameLoaded && STATE?.time_unit==="month"')
                assert page.locator('#stepBtn').inner_text()=='+1 月'
                assert page.evaluate('STATE.day')==1
                assert page.evaluate('STATE.engine_day')==2
                page.locator('#reopenLeft').click()
                page.locator('#realmPicker').select_option('A')
                page.locator('#interveneBtn').click()
                page.wait_for_function('STATE.player_country==="A"')
                page.locator('[data-deck="situations"]').click()
                page.locator('#situationSections [data-sit-section="library"]').click()
                page.locator('[data-sit-category="自然与气候"]').click()
                page.locator('[data-sit-preset="drought"]').click()
                form=page.locator('#situationCreateForm')
                form.locator('[name="country_id"]').select_option('B')
                form.locator('[name="duration_months"]').fill('2')
                form.locator('button[type="submit"]').click()
                page.wait_for_selector('[data-sit-id]')
                page.locator('[data-sit-id]').first.click()
                page.wait_for_selector('#situationDetailBody h2')
                assert '剩余 2 月' in page.locator('#situationFocusBar').inner_text()
                page.screenshot(path=str(output/'event-months.png'))
                page.locator('#stepBtn').click()
                page.wait_for_function('STATE.day===2 && STATE.engine_day===31')
                page.wait_for_function('situationUI.detail?.remaining_days===1')
                assert '日' not in page.evaluate('STATE.date')
                raw=page.request.get(base+'/api/state').json()
                assert raw['calendar']['month_number']==2
                expected=raw['countries']['A']['monthly_economy']['treasury_income']
                assert abs(page.evaluate('STATE.countries.A.last_economy.treasury_income')-expected)<1e-7
                page.locator('[data-deck="nation"]').click()
                page.locator('[data-nation-tab="finance"]').click()
                page.wait_for_selector('#financeTaxRate')
                assert '实际月结算' in page.locator('#strategyFinance').inner_text() if page.locator('#strategyFinance').count() else '实际月结算' in page.locator('#nationModal').inner_text()
                page.screenshot(path=str(output/'monthly-ledger.png'))
                page.keyboard.press('Escape')
                # The quote is in months, and one subsequent month completes the short order.
                page.evaluate("selectedArmy=STATE.countries.A.armies.find(a=>a.strength>0).army_id;strategyCommand='move';selectStrategyTile([13,20])")
                page.wait_for_function('!document.querySelector(\'[data-command="confirm-move"]\')?.disabled')
                assert '个月' in page.locator('#commandHint').inner_text()
                page.screenshot(path=str(output/'march-months.png'))
                page.locator('[data-command="confirm-move"]').click()
                page.wait_for_function('STATE.countries.A.armies.some(a=>a.march)')
                page.locator('#stepBtn').click()
                page.wait_for_function('STATE.day===3 && STATE.engine_day===59')
                assert page.evaluate('STATE.countries.A.armies.some(a=>a.tile?.[0]===13&&a.tile?.[1]===20&&!a.march)')
                assert page.evaluate('STATE.situations[0].status')=='ended'
                page.locator('#situationFocusBar').click()
                page.wait_for_selector('.situation-chronicle')
                assert ' 日' not in page.locator('.situation-chronicle').inner_text()
                page.screenshot(path=str(output/'monthly-chronicle.png'))
                # Units are monthly on all major panels; no daily counters leak back in.
                for deck in ('situations','nation','city','tech','diplo','military'):
                    page.evaluate('name=>openDeck(name,true)',deck)
                    page.wait_for_timeout(100)
                    visible=page.locator('#app').inner_text()
                    visible+=' '+page.locator('.modal:not([hidden])').inner_text() if page.locator('.modal:not([hidden])').count()==1 else ''
                    assert not re.search(r'每日|游戏日|\d+\s*天|\d+\s*日(?!记)',visible),(deck,visible)
                page.evaluate("openDeck('world',true)")
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(output/'monthly-mobile.png'))
                assert page.locator('#stepBtn').is_visible()
                assert page.evaluate('STATE.paused')
                assert not errors,errors
                browser.close()
            result={'javascript_errors':errors,'calendar_steps':[{'month':1,'engine_day':2},{'month':2,'engine_day':31},{'month':3,'engine_day':59}],
                    'monthly_finance':True,'monthly_event_expiry':True,'monthly_march':True,'visible_daily_units':False}
            (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
        finally:
            server.shutdown();server.server_close();session.stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'runs/ui_checks/monthly')
    args=parser.parse_args();print(json.dumps(verify(args.output),ensure_ascii=False,indent=2))
