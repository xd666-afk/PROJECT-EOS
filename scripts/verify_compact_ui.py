"""Measure unobstructed map area and exercise compact edge controls on real pages."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
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
    with tempfile.TemporaryDirectory(prefix='eos-compact-') as temp:
        live_server.SAVE_DIR=Path(temp)/'saves'
        session=live_server.LiveSession(paused=True,load_path=ROOT/'examples/civil_networks/save.json')
        session.save_current('紧凑界面验收')

        class Handler(live_server.Handler):
            def log_message(self,*_args):
                pass

        Handler.session=session
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1366,'height':768})
                page.on('pageerror',lambda err:errors.append(str(err)))
                page.goto(base+'/?play=latest')
                page.wait_for_function('gameLoaded && STATE?.countries')

                def map_area():
                    return page.evaluate('''()=>{
                        let total=0,clear=0;
                        for(let y=8;y<innerHeight;y+=16)for(let x=8;x<innerWidth;x+=16){
                            total++;if(document.elementFromPoint(x,y)?.id==='map')clear++;
                        }
                        const r=canvas.getBoundingClientRect();
                        return {width:innerWidth,height:innerHeight,canvas_height:r.height,
                            header:r.top,clear_map_fraction:Math.round(clear/total*1000)/1000};
                    }''')

                reports=[]
                for width,height in ((1920,1080),(1707,929),(1366,768),(1280,720),(1024,768),(800,900),(390,844)):
                    page.set_viewport_size({'width':width,'height':height})
                    page.wait_for_timeout(200)
                    assert page.locator('#worldLeft').is_hidden()
                    assert page.locator('#worldRight').is_hidden()
                    assert page.locator('#commandDock').is_hidden()
                    report=map_area()
                    assert report['canvas_height']>=height-72,report
                    assert report['clear_map_fraction']>=.80,report
                    for selector in ('#realmHome','#pauseBtn','#stepBtn','#timeDock','#mapLayerSummary'):
                        box=page.locator(selector).bounding_box()
                        assert box and box['x']>=0 and box['x']+box['width']<=width+1,(selector,box,width)
                        assert box['y']>=0 and box['y']+box['height']<=height+1,(selector,box,height)
                    reports.append(report)
                    if width in (1707,1366,390):page.screenshot(path=str(output/f'map-{width}.png'))
                page.set_viewport_size({'width':1366,'height':768})
                page.locator('#mapLayerSummary').click()
                page.locator('[data-layer="political"]').click()
                assert page.evaluate('mapMode')=='political'
                assert not page.locator('#mapLayerMenu').evaluate('(r)=>r.open')
                assert '政治' in page.locator('#mapLayerSummary').inner_text()
                page.locator('#mapLayerSummary').focus()
                page.keyboard.press('Space')
                assert page.locator('#mapLayerMenu').evaluate('(r)=>r.open')
                assert page.evaluate('STATE.paused')
                page.keyboard.press('Escape')
                assert not page.locator('#mapLayerMenu').evaluate('(r)=>r.open')
                assert page.locator('#pauseMenu').is_hidden()
                page.locator('#mapLayerSummary').click()
                page.locator('#fitWorldBtn').click()
                assert page.evaluate('zoom')<1
                assert page.evaluate('mapMode')=='political'
                page.screenshot(path=str(output/'whole-world.png'))
                page.locator('#primaryRail [data-deck="situations"]').click()
                assert page.locator('#situationFocusBar').is_hidden()
                empty=map_area()
                assert empty['clear_map_fraction']>=.78,empty
                page.screenshot(path=str(output/'empty-situations.png'))
                page.locator('#situationSections [data-sit-section="library"]').click()
                page.locator('[data-sit-category="自然与气候"]').click()
                page.locator('[data-sit-preset="drought"]').click()
                assert page.locator('#situationHub').evaluate('(r)=>getComputedStyle(r).visibility')=='hidden'
                page.locator('#situationCreateForm [name="country_id"]').select_option('A')
                page.locator('#situationCreateForm button[type="submit"]').click()
                page.wait_for_selector('[data-sit-id]')
                page.locator('[data-sit-id]').first.click()
                page.wait_for_selector('#situationDetailBody h2')
                page.request.post(base+'/api/control',data={'action':'step'})
                page.evaluate('poll(true)')
                page.wait_for_function('situationUI.detail?.elapsed>=1')
                assert page.locator('#situationHub').evaluate('(r)=>getComputedStyle(r).visibility')=='hidden'
                detail=map_area()
                assert detail['clear_map_fraction']>=.62,detail
                page.screenshot(path=str(output/'focused-situation.png'))
                page.locator('[data-sit-action="close"]').count()
                page.keyboard.press('Escape')
                page.keyboard.press('Escape')
                assert page.locator('#situationFocusBar').is_visible()
                assert page.locator('#commandDock').is_hidden()
                page.screenshot(path=str(output/'tracking-map.png'))
                # Focus progress and list/detail never change realtime control.
                assert page.evaluate('STATE.paused')
                assert not errors,errors
                browser.close()
            result={'javascript_errors':errors,'idle_map_measurements':reports,'empty_situation_menu':empty,'focused_detail':detail}
            (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
        finally:
            server.shutdown();server.server_close();session.stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'runs/ui_checks/compact')
    args=parser.parse_args()
    print(json.dumps(verify(args.output),ensure_ascii=False,indent=2))
