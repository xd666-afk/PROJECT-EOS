"""Verify real satellite control rendering, shared edges, holes, and ownership updates."""
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
    with tempfile.TemporaryDirectory(prefix='eos-satellite-') as temp:
        live_server.SAVE_DIR=Path(temp)/'saves'
        session=live_server.LiveSession(paused=True,load_path=ROOT/'examples/civil_networks/save.json')
        session.save_current('卫星控制区验收')

        class Handler(live_server.Handler):
            def log_message(self,*_args):pass

        Handler.session=session
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':900})
                page.on('pageerror',lambda err:errors.append(str(err)))
                page.goto(base+'/?play=latest')
                page.wait_for_function('gameLoaded && STATE?.countries && territoryCache.regions.length>0')
                page.wait_for_timeout(200)
                geometry=page.evaluate('''()=>{
                    const check=(ok,label)=>{if(!ok)throw Error(label);};let pairs=0;
                    check(buildTerritoryGeometry({'0,0':'A'})[0].edges.length===6,'single hex');
                    for(const row of [4,5])for(const [dx,dy] of (row&1?HEX_DIR_ODD:HEX_DIR_EVEN)){
                        const owners={};owners['4,'+row]='A';owners[(4+dx)+','+(row+dy)]='A';
                        const shape=buildTerritoryGeometry(owners)[0];
                        check(shape.edges.length===10,'shared internal edge');
                        const mx=(cx([4,row])+cx([4+dx,row+dy]))/2,my=(cy([4,row])+cy([4+dx,row+dy]))/2;
                        check(!shape.edges.some(e=>Math.hypot((e[0]+e[2])/2-mx,(e[1]+e[3])/2-my)<1e-8),'internal segment not removed');pairs++;
                    }
                    const ring={};for(const [dx,dy] of HEX_DIR_EVEN)ring[(4+dx)+','+(4+dy)]='A';
                    check(buildTerritoryGeometry(ring)[0].edges.length===24,'hole boundary');
                    ring['4,4']='A';check(buildTerritoryGeometry(ring)[0].edges.length===18,'filled hole');
                    const separate=buildTerritoryGeometry({'0,0':'A','9,9':'A','1,0':'B'});
                    check(separate.find(r=>r.id==='A').edges.length===12,'disconnected holdings');
                    check(separate.find(r=>r.id==='B').edges.length===6,'foreign shared edge');
                    for(const region of separate)check(region.tiles.some(p=>p.join(',')===region.anchor.join(',')),'anchor on owned tile');
                    const large=buildTerritoryGeometry({'0,0':'A','9,9':'A','10,9':'A'})[0];
                    check(large.anchor[0]>=9,'largest component label');
                    check(buildTerritoryGeometry({}).length===0,'empty control map');
                    return {adjacent_pairs:pairs,hole:true,disconnected:true,foreign_boundary:true};
                }''')
                page.evaluate('showWholeMap()')
                page.screenshot(path=str(output/'satellite-world.png'))
                ownership=page.evaluate('''()=>{
                    const first=STATE.countries.A,second=STATE.countries.B;
                    const a=first.tiles.slice(),b=second.tiles.slice(),oldDay=STATE.day,oldKey=territoryCache.key;
                    try{
                        const tile=first.tiles[0];first.tiles=first.tiles.slice(1);second.tiles=[...second.tiles,tile];
                        render();
                        const regions=territoryCache.regions;
                        if(regions.find(r=>r.id==='A').count!==a.length-1||regions.find(r=>r.id==='B').count!==b.length+1)throw Error('same-day ownership did not repaint');
                        const newKey=territoryCache.key;
                        second.tiles=second.tiles.filter(p=>p!==tile);render();
                        if(territoryCache.regions.find(r=>r.id==='A').tiles.some(p=>p.join(',')===tile.join(',')))throw Error('static owner resurrected');
                        delete STATE.countries.B;render();
                        if(territoryCache.regions.some(r=>r.id==='B'))throw Error('eliminated country remains');
                        return {same_day:STATE.day===oldDay,key_changed:newKey!==oldKey,unclaimed_not_restored:true,eliminated_removed:true};
                    }finally{first.tiles=a;second.tiles=b;STATE.countries.B=second;render(true);}
                }''')
                page.evaluate("selectedCountry='A';zoom=3;focusTile(...STATE.countries.A.cities[0].center);setSidePanel('right',false);setSidePanel('left',false)")
                page.screenshot(path=str(output/'satellite-detail.png'))
                pixel=page.evaluate('''()=>{
                    const original=drawSatelliteTerritories,originalLabels=drawSatelliteControlLabels;
                    const before=ctx.getImageData(0,0,canvas.width,canvas.height).data;
                    try{
                        drawSatelliteTerritories=()=>{};drawSatelliteControlLabels=()=>{};render(true);
                        const after=ctx.getImageData(0,0,canvas.width,canvas.height).data;
                        let changed=0;for(let i=0;i<before.length;i+=4)if(before[i]!==after[i]||before[i+1]!==after[i+1]||before[i+2]!==after[i+2])changed++;
                        if(changed<100)throw Error('satellite overlay has no visible pixels');
                        return {changed_pixels:changed};
                    }finally{drawSatelliteTerritories=original;drawSatelliteControlLabels=originalLabels;render(true);}
                }''')
                # The same control overlay also renders above raster terrain textures.
                page.evaluate('''()=>{
                    window.savedSatelliteTerrain={image:terrainImage,ready:terrainReady};
                    const texture=document.createElement('canvas');texture.width=64;texture.height=64;
                    const c=texture.getContext('2d');c.fillStyle='#3c6846';c.fillRect(0,0,64,64);
                    terrainImage=texture;terrainReady=true;render(true);
                }''')
                page.screenshot(path=str(output/'texture-overlay.png'))
                page.evaluate('terrainImage=savedSatelliteTerrain.image;terrainReady=savedSatelliteTerrain.ready;render(true)')
                page.set_viewport_size({'width':390,'height':844})
                page.evaluate('showWholeMap()')
                page.screenshot(path=str(output/'satellite-mobile.png'))
                assert not errors,errors
                browser.close()
            result={'javascript_errors':errors,'geometry':geometry,'ownership':ownership,'visible_overlay':pixel}
            (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
        finally:
            server.shutdown();server.server_close();session.stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'runs/ui_checks/satellite')
    args=parser.parse_args()
    print(json.dumps(verify(args.output),ensure_ascii=False,indent=2))
