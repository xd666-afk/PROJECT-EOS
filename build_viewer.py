"""Produce a self-contained, offline-interactive HTML hex map viewer."""
from pathlib import Path
import json

HERE=Path(__file__).resolve().parent
world=json.loads((HERE/'output/world_2000BCE.json').read_text(encoding='utf-8'))
mini={'metadata':world['metadata'],'polities':world['polities'],
      'tiles':[{k:v for k,v in t.items() if k in ('col','row','q','r','land','elevation_m','biome','annual_precip_mm','annual_mean_temp_c','river','hazards','owner_id','drainage_area_km2')} for t in world['tiles']]}
blob=json.dumps(mini,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
html=r'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Project Eos · 大陆观察器</title><style>
:root{color-scheme:dark} *{box-sizing:border-box} body{margin:0;background:#101d29;color:#ecf2f4;font:14px/1.5 system-ui,"Microsoft Yahei",sans-serif}
header{height:70px;padding:12px 22px;border-bottom:1px solid #314252;display:flex;align-items:center;justify-content:space-between;gap:16px}
h1{font-size:20px;letter-spacing:1px;margin:0} header small{color:#a7bec9} .main{display:grid;grid-template-columns:1fr 300px;height:calc(100vh - 70px);min-height:450px}
#stage{position:relative;overflow:hidden;background:#1b3e55;cursor:grab} #stage.grab{cursor:grabbing}canvas{width:100%;height:100%;display:block}
#guide{position:absolute;left:18px;bottom:16px;padding:8px 11px;border-radius:8px;background:#122331d9;color:#dbe8eb;font-size:12px;pointer-events:none}
aside{border-left:1px solid #304151;background:#172734;overflow:auto;padding:18px} h2{font-size:14px;margin:16px 0 9px;color:#d2e5e9}p{color:#afc1ca;margin:4px 0 9px;font-size:12px}
select,button{background:#253b4b;color:white;border:1px solid #455c69;border-radius:7px;padding:9px 10px;width:100%;font:inherit}
.card{margin:10px 0;border:1px solid #354c59;border-radius:10px;padding:11px 12px;background:#203340;min-height:106px}
.kv{display:flex;justify-content:space-between;border-bottom:1px solid #304754;padding:5px 0;gap:10px;font-size:12px}.kv span{color:#a6bcc9}.kv strong{font-weight:500;text-align:right}
.pill{border-radius:5px;padding:3px 7px;background:#304856;font-size:11px;margin-right:4px;display:inline-block}
.country{display:flex;gap:8px;padding:10px 6px;align-items:flex-start;border-bottom:1px solid #304351}.country>i{width:11px;height:11px;flex:none;border-radius:50%;margin-top:5px}.country b{font-size:13px}.country small{display:block;font-size:11px;color:#9eb4bd}
#legend{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.l{display:flex;gap:4px;align-items:center;font-size:11px;color:#a9bdc6}.l i{width:10px;height:10px;border-radius:2px}
@media(max-width:840px){header{height:auto;min-height:70px}.main{display:flex;flex-direction:column;height:auto}#stage{height:65vh;min-height:420px} aside{border-left:0;border-top:1px solid #304151}}
</style></head><body><header><div><h1>PROJECT EOS · 埃欧斯大陆</h1><small>公元前 2000 年 · 初始世界 / 可暂停实时战略模拟基础地图</small></div><div style="text-align:right"><span class="pill">SEED 2000</span><span class="pill">3,888 HEX</span></div></header><div class="main"><div id="stage"><canvas id="map"></canvas><div id="guide">拖动平移 · 滚轮缩放 · 点击地块查看环境数据</div></div><aside><h2>地图图层</h2><select id="layer"><option value="biome">地形与生物群系</option><option value="rain">年均降水量</option><option value="temperature">年均温度</option><option value="elevation">海拔高度</option><option value="hazard">自然灾害综合暴露指数</option><option value="political">国家控制区域</option></select><div id="legend"></div><h2>选中地块</h2><div class="card" id="info">点击六边形查看坐标、气候、地势、河流和灾害风险。</div><h2>初始国家（青铜时代）</h2><div id="countries"></div><p>四国只占据早期聚落核心区，大陆其余地块未被国家占有。</p><button id="reset">重置视角</button><p style="margin-top:16px">气候：纬度、季节性辐射、地形抬升与雨影的简化模型。灾害：相对暴露指数，尚未标定真实重现期。</p></aside></div><script>
const WORLD=__DATA__;
const c=document.getElementById('map'),ctx=c.getContext('2d');const stage=document.getElementById('stage');
const tiles=WORLD.tiles, polities=WORLD.polities;const map=new Map(tiles.map(t=>[t.col+','+t.row,t]));
const colors={ocean:'#286486',alpine:'#acb0b5',tundra:'#b2b8a3',desert:'#ddb777',steppe:'#c7bc83',savanna:'#afc87b',grassland:'#8db579',forest:'#488b6c',rainforest:'#267559',wetland:'#73a897'};
const polColors=['#ebbb6e','#65abc6','#dc877c','#be8bcc'], polityColor=Object.fromEntries(polities.map((p,i)=>[p.id,polColors[i]]));
const cx=t=>Math.sqrt(3)*(t.col+.5*(t.row%2)), cy=t=>1.5*t.row;
let w=1,h=1,s=1,offsetX=0,offsetY=0,mode='biome',active=null,drag=false,lastX=0,lastY=0,moved=false;
function clamp(a,b,v){return Math.max(a,Math.min(b,v))}
function rgb(r,g,b){return `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`}
function ramp(v,stops){v=clamp(0,1,v);const f=v*(stops.length-1),i=Math.min(Math.floor(f),stops.length-2),t=f-i;return rgb(...stops[i].map((n,k)=>n+(stops[i+1][k]-n)*t))}
function maxRisk(t){return Math.max(...Object.values(t.hazards))}
function tileColor(t){if(!t.land)return colors.ocean;if(mode==='political')return polityColor[t.owner_id]||'#8b9b8b';
if(mode==='biome')return colors[t.biome]||'#aaa';
if(mode==='rain')return ramp(t.annual_precip_mm/2400,[[227,195,127],[241,233,163],[116,194,154],[39,136,173],[26,67,116]]);
if(mode==='elevation')return ramp(t.elevation_m/3900,[[125,182,116],[207,188,124],[145,127,102],[154,145,134],[235,232,218]]);
if(mode==='temperature')return ramp((t.annual_mean_temp_c+8)/38,[[76,124,171],[154,191,198],[231,220,136],[220,139,87],[155,78,69]]);
return ramp(maxRisk(t),[[240,233,185],[233,177,118],[207,94,66],[131,37,54]]);}
function fit(){const boundX=Math.sqrt(3)*(WORLD.metadata.grid_width+.5),boundY=1.5*WORLD.metadata.grid_height;
s=Math.min((w-34)/boundX,(h-34)/boundY);offsetX=(w-boundX*s)/2;offsetY=(h-boundY*s)/2;render();}
function size(){let dpr=Math.min(window.devicePixelRatio||1,2);w=stage.clientWidth;h=stage.clientHeight;c.width=w*dpr;c.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);fit()}
function hex(x,y){ctx.beginPath();for(let i=0;i<6;i++){const angle=(60*i-30)*Math.PI/180,xx=x+.98*Math.cos(angle),yy=y+.98*Math.sin(angle);if(!i)ctx.moveTo(xx,yy);else ctx.lineTo(xx,yy)}ctx.closePath()}
function render(){ctx.setTransform(c.width/w,0,0,c.height/h,0,0);ctx.fillStyle='#1c415c';ctx.fillRect(0,0,w,h);ctx.save();ctx.translate(offsetX,offsetY);ctx.scale(s,s);
for(const t of tiles){hex(cx(t),cy(t));ctx.fillStyle=tileColor(t);ctx.fill();}
if(mode!=='political'){ctx.beginPath();for(const t of tiles){if(!t.river)continue;const down=WORLD._flow?.[t.col+','+t.row]; // river routes stored in source world, but optional here
 if(!down)continue;ctx.moveTo(cx(t),cy(t));ctx.lineTo(cx(down),cy(down));}ctx.strokeStyle='#61b5df';ctx.lineWidth=Math.max(.15,1/s);ctx.stroke();}
for(let i=0;i<polities.length;i++){const p=polities[i],t=map.get(p.capital.col+','+p.capital.row);if(!t)continue;const x=cx(t),y=cy(t);ctx.beginPath();ctx.arc(x,y,1.08,0,Math.PI*2);ctx.fillStyle=polColors[i];ctx.fill();ctx.lineWidth=.28;ctx.strokeStyle='#172632';ctx.stroke();ctx.fillStyle='#fff';ctx.font='bold 2px system-ui';ctx.textAlign='center';ctx.fillText('★',x,y+.7);}
if(active){hex(cx(active),cy(active));ctx.strokeStyle='#fff9a8';ctx.lineWidth=.5;ctx.stroke()}
ctx.restore();ctx.textAlign='left';ctx.fillStyle='rgba(20,38,50,.75)';ctx.fillRect(12,12,200,25);ctx.fillStyle='#e8f1f1';ctx.font='12px system-ui';ctx.fillText('大陆比例尺：六边形半径 34 km',20,29);}
function closest(px,py){const x=(px-offsetX)/s,y=(py-offsetY)/s;let best=null,d=1.2;let row=Math.round(y/1.5);for(let yy=row-2;yy<=row+2;yy++){if(yy<0||yy>=WORLD.metadata.grid_height)continue;let col=Math.round(x/Math.sqrt(3)-.5*(yy%2));for(let xx=col-2;xx<=col+2;xx++){let t=map.get(xx+','+yy);if(!t)continue;const dd=Math.hypot(cx(t)-x,cy(t)-y);if(dd<d){best=t;d=dd}}}return best}
const biomes={ocean:'海洋',alpine:'高山',tundra:'冻原',desert:'沙漠',steppe:'半干旱草原',savanna:'稀树草原',grassland:'草原',forest:'温带森林',rainforest:'雨林',wetland:'湿地'};
function show(t){active=t;const country=polities.find(p=>p.id===t.owner_id);document.getElementById('info').innerHTML=`<div class="kv"><span>坐标</span><strong>q=${t.q}, r=${t.r}</strong></div><div class="kv"><span>生物群系</span><strong>${biomes[t.biome]||t.biome}</strong></div><div class="kv"><span>海拔</span><strong>${t.elevation_m} m</strong></div><div class="kv"><span>年均温</span><strong>${t.annual_mean_temp_c} °C</strong></div><div class="kv"><span>年均降水</span><strong>${t.annual_precip_mm} mm</strong></div><div class="kv"><span>地表径流</span><strong>${t.river?'主要河道':'非主要河道'}</strong></div><div class="kv"><span>控制权</span><strong>${country?.name||'无国家控制'}</strong></div><h2>相对自然灾害暴露</h2>${Object.entries(t.hazards).map(([k,v])=>`<div class="kv"><span>${{flood:'洪水',drought:'干旱',earthquake:'地震',volcano:'火山',wildfire:'野火',cyclone:'热带气旋'}[k]}</span><strong>${(v*100).toFixed(1)}%</strong></div>`).join('')}<p>百分比是归一化指数，不是实际发生概率。</p>`;render()}
stage.addEventListener('pointerdown',e=>{drag=true;moved=false;lastX=e.clientX;lastY=e.clientY;stage.classList.add('grab');stage.setPointerCapture(e.pointerId)})
stage.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-lastX,dy=e.clientY-lastY;if(Math.abs(dx)+Math.abs(dy)>1)moved=true;offsetX+=dx;offsetY+=dy;lastX=e.clientX;lastY=e.clientY;render()})
stage.addEventListener('pointerup',e=>{if(!drag)return;drag=false;stage.classList.remove('grab');if(!moved){const rect=stage.getBoundingClientRect();const t=closest(e.clientX-rect.left,e.clientY-rect.top);if(t)show(t)}})
stage.addEventListener('wheel',e=>{e.preventDefault();const rect=stage.getBoundingClientRect(),px=e.clientX-rect.left,py=e.clientY-rect.top,scale=Math.exp(-e.deltaY*.001);const ns=clamp(2,60,s*scale),factor=ns/s;offsetX=px+(offsetX-px)*factor;offsetY=py+(offsetY-py)*factor;s=ns;render()},{passive:false})
const legend=document.getElementById('legend');const legendDict={biome:[['海洋',colors.ocean],['森林',colors.forest],['草原',colors.grassland],['干旱',colors.desert],['高山',colors.alpine]],rain:[['少雨','#e3c37f'],['多雨','#1a4374']],temperature:[['冷','#4c7cab'],['暖','#db8b57']],elevation:[['低','#7db674'],['高','#ebe8da']],hazard:[['低','#f0e9b9'],['高','#832536']],political:polities.map((p,i)=>[p.name,polColors[i]])};
function legendRender(){legend.innerHTML=legendDict[mode].map(([a,b])=>`<div class="l"><i style="background:${b}"></i>${a}</div>`).join('')}
document.getElementById('layer').addEventListener('change',e=>{mode=e.target.value;legendRender();render()});
document.getElementById('reset').addEventListener('click',fit);
document.getElementById('countries').innerHTML=polities.map((p,i)=>`<div class="country"><i style="background:${polColors[i]}"></i><div><b>${p.name}</b><small>${p.government} · ${p.population.toLocaleString()} 人 · ${p.territorial_area_km2.toLocaleString()} km²</small><small>都城 (${p.capital.col},${p.capital.row}) / 年雨量 ${p.avg_annual_precip_mm} mm</small></div></div>`).join('');
window.addEventListener('resize',size);legendRender();size();
</script></body></html>'''
# Make river flow visible in viewer through a small lookup map.
mini_flow={str(t['col'])+','+str(t['row']):t['downstream'] for t in world['tiles'] if t['river'] and t['downstream']}
# Keep rivers included in a second mapping; use object IDs of target tile.
viewer_data=mini
viewer_data['_flow']={k:{'col':v['col'],'row':v['row']} for k,v in mini_flow.items()}
blob=json.dumps(viewer_data,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
html=html.replace('__DATA__',blob)
(HERE/'output/viewer.html').write_text(html,encoding='utf-8')
print('viewer.html',len(html),'characters')
