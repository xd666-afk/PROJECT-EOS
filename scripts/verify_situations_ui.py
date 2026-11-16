"""Exercise the real HTTP server and three-level situation UI using isolated saves."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(output):
    from playwright.sync_api import sync_playwright
    import live_server
    output.mkdir(parents=True, exist_ok=True)
    errors, controls = [], []
    with tempfile.TemporaryDirectory(prefix='eos-situations-') as tmp:
        live_server.SAVE_DIR = Path(tmp) / 'saves'
        session = live_server.LiveSession(paused=True, load_path=ROOT / 'examples/civil_networks/save.json')
        session.save_current('事态浏览器验收专用')

        class Handler(live_server.Handler):
            def log_message(self, *_args):
                pass

        Handler.session = session
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.on('request', lambda req: controls.append(req.post_data_json) if req.method=='POST' and req.url.endswith('/api/control') else None)
                page.goto(base+'/?play=latest')
                page.wait_for_function('STATE?.countries && gameLoaded')
                assert page.request.get(base+'/api/situations').json()['active_limit'] == 12
                assert 'javascript' in page.request.get(base+'/assets/ui/situations.js').headers['content-type']

                page.locator('[data-deck="situations"]').click()
                page.wait_for_selector('#situationHub:not([hidden])')
                assert page.locator('#situationDetail').is_hidden()
                assert page.locator('#primaryRail [data-deck="situations"]').count() == 1
                assert page.locator('#situationSections button').count() == 3
                assert page.locator('[data-sit-preset]').count() == 0
                page.locator('#situationSections [data-sit-section="library"]').click()
                page.locator('[data-sit-category="自然与气候"]').click()
                page.locator('[data-sit-preset="drought"]').click()
                page.locator('#situationCreateForm [name="country_id"]').select_option('A')
                page.locator('#situationCreateForm [name="duration"]').fill('12')
                page.locator('#situationCreateForm button[type="submit"]').click()
                page.wait_for_selector('#situationList [data-sit-id]')
                first = page.locator('#situationList [data-sit-id]').first.get_attribute('data-sit-id')
                assert page.evaluate('situationUI.focus') is None
                page.locator(f'[data-sit-id="{first}"]').click()
                page.wait_for_selector('#situationDetailBody h2')
                assert '持续干旱' in page.locator('#situationDetailBody h2').inner_text()
                assert '持续干旱' in page.locator('#situationFocusBar').inner_text()

                # Creating another event never steals the existing focus.
                page.locator('#situationSections [data-sit-section="library"]').click()
                page.locator('[data-sit-preset="harvest"]').click()
                page.locator('#situationCreateForm [name="country_id"]').select_option('B')
                page.locator('#situationCreateForm [name="duration"]').fill('15')
                page.locator('#situationCreateForm button[type="submit"]').click()
                page.wait_for_function('STATE.situations.length===2')
                assert page.evaluate('situationUI.focus') == first
                second = page.evaluate('STATE.situations.find(s=>s.preset_id==="harvest").id')
                page.locator(f'[data-sit-id="{second}"]').click()
                page.wait_for_function('situationUI.detail?.preset_id==="harvest"')
                assert page.evaluate('situationUI.focus') == second

                # Actual day settlement, action receipts, independently advancing effects.
                for _ in range(2):
                    assert page.request.post(base+'/api/control',data={'action':'step'}).json()['ok']
                page.evaluate('poll(true)')
                page.wait_for_function('situationUI.detail?.elapsed===2')
                assert page.evaluate('STATE.situations.every(s=>s.elapsed===2)')
                page.locator('.situation-data-fold summary').click()
                page.evaluate('situationUI.detailKey="";refreshSituations()')
                assert page.locator('.situation-data-fold').get_attribute('open') is not None
                page.locator('[data-sit-tab="history"]').click()
                assert page.locator('.situation-history [data-kind="observation"]').count() >= 1
                page.screenshot(path=str(output/'development.png'))
                page.locator('[data-sit-tab="adjust"]').click()
                page.locator('#situationAdjustForm [name="remaining_days"]').fill('9')
                # A poll must not overwrite unsaved edits.
                page.evaluate('poll(true)')
                assert page.locator('#situationAdjustForm [name="remaining_days"]').input_value() == '9'
                page.locator('#situationAdjustForm [name="intensity"]').select_option('3')
                page.locator('#situationAdjustForm button[type="submit"]').click()
                page.wait_for_function('STATE.situations.find(s=>s.preset_id==="harvest").remaining_days===9')
                page.locator('[data-sit-action="end"]').click()
                page.locator('[data-sit-action="end-confirm"]').click()
                page.wait_for_selector('.situation-chronicle')
                assert page.evaluate('STATE.situations.find(s=>s.id===situationUI.focus).status') == 'ended'
                assert page.evaluate('STATE.situations.find(s=>s.preset_id==="drought").status') == 'active'
                page.screenshot(path=str(output/'chronicle.png'))

                # Escape steps back through the hierarchy without opening the pause menu.
                page.keyboard.press('Escape')
                assert page.locator('#situationDetail').is_hidden()
                assert page.locator('#situationHub').is_visible()
                page.keyboard.press('Escape')
                assert page.locator('#situationHub').is_hidden()
                assert page.locator('#pauseMenu').is_hidden()
                assert page.locator('#situationFocusBar').is_visible()
                page.locator('#situationFocusBar').click()
                page.wait_for_selector('#situationDetail:not([hidden])')
                page.locator('[data-sit-action="back"]').click()
                page.locator('#situationSections [data-sit-section="active"]').click()
                page.locator(f'[data-sit-id="{first}"]').click()
                page.wait_for_function('situationUI.detail?.preset_id==="drought"')
                page.screenshot(path=str(output/'desktop.png'))

                layouts=[]
                for width in (1440,1024,800,390):
                    page.set_viewport_size({'width':width,'height':1000 if width>600 else 844})
                    page.wait_for_timeout(150)
                    report=page.locator('#situationDetail').evaluate('(r)=>{const b=r.getBoundingClientRect();return {width:innerWidth,left:b.left,right:b.right,top:b.top,bottom:b.bottom,scroll:r.scrollWidth,client:r.clientWidth}}')
                    assert report['left'] >= 0 and report['right'] <= width, report
                    assert report['scroll'] <= report['client'] + 1, report
                    chrome=page.locator('#situationFocusBar').evaluate('(r)=>{const b=r.getBoundingClientRect();return {left:b.left,right:b.right}}')
                    if width>600:
                        assert chrome['left'] >= report['right'], (report,chrome)
                    layouts.append(report)
                    if width in (1024,800):
                        page.screenshot(path=str(output/f'width-{width}.png'))
                    if width==390:
                        assert page.locator('#situationHub').evaluate('(r)=>getComputedStyle(r).visibility') == 'hidden'
                        page.screenshot(path=str(output/'mobile.png'))
                        page.locator('[data-sit-action="back"]').click()
                        page.locator('#situationSections [data-sit-section="library"]').click()
                        page.locator('[data-sit-action="categories"]').click()
                        page.locator('[data-sit-category="外交关系"]').click()
                        page.locator('[data-sit-preset="friendship"]').click()
                        assert page.locator('#situationCreateForm [name="partner_id"]').is_visible()
                        page.screenshot(path=str(output/'mobile-create.png'))

                # Requests are validated server-side; custom text and conflicts cannot enter state.
                bad=page.request.post(base+'/api/situations',data={'operation':'create','event':{'preset_id':'drought','country_id':'A'}}).json()
                assert not bad['ok']
                assert not any(c.get('action') in {'pause','resume'} for c in controls), controls
                # View-state survives reload; reading menus never pauses live simulation.
                page.reload()
                page.wait_for_function('gameLoaded && situationUI.focus!==null')
                assert page.evaluate('situationUI.focus') == first
                page.set_viewport_size({'width':1440,'height':1000})
                page.locator('#situationFocusBar').click()
                page.wait_for_selector('#situationDetail:not([hidden])')
                page.locator('#pauseBtn').click()
                page.wait_for_function('!STATE.paused')
                day=page.evaluate('STATE.day')
                baseline=len(controls)
                page.locator('[data-sit-action="back"]').click()
                page.locator('#situationSections [data-sit-section="library"]').click()
                page.locator('[data-sit-category="科技与建设"]').click()
                page.locator('[data-sit-preset="discovery"]').click()
                page.wait_for_function('day=>STATE.day>day',arg=day)
                assert not page.evaluate('STATE.paused')
                assert not any(c.get('action') in {'pause','resume'} for c in controls[baseline:])
                page.locator('#pauseBtn').click()
                page.wait_for_function('STATE.paused')
                # Expiry while the adjustment form is open removes stale controls.
                page.locator('[data-sit-action="back"]').click()
                page.locator('#situationSections [data-sit-section="active"]').click()
                page.locator(f'[data-sit-id="{first}"]').click()
                page.wait_for_function('situationUI.detail?.preset_id==="drought"')
                page.locator('[data-sit-tab="adjust"]').click()
                assert page.request.post(base+'/api/situations',data={'operation':'update','id':first,'changes':{'remaining_days':1}}).json()['ok']
                assert page.request.post(base+'/api/control',data={'action':'step'}).json()['ok']
                page.evaluate('poll(true)')
                page.wait_for_selector('.situation-chronicle')
                assert page.locator('#situationAdjustForm').count() == 0
                browser.close()
            assert not errors, errors
            result={'browser_errors':errors,'layouts':layouts,'scenarios':['parallel','single-focus','editing','history','end','menu-back','mobile','server-validation']}
            (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
        finally:
            server.shutdown();server.server_close();session.stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'docs/report_assets/situations_v050')
    args=parser.parse_args()
    print(json.dumps(verify(args.output),ensure_ascii=False,indent=2))
