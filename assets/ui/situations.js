/* Audience interventions. Browser focus is a view choice, never a simulation switch. */
const situationUI={section:'active',category:null,focus:null,detail:null,detailTab:'overview',preset:null,
  presets:[],limit:12,world:null,signature:'',detailKey:'',loading:false,busy:false,ending:false};
const SITUATION_EFFECT_NAMES={food:'粮食产出',tax:'税收',research:'研究产出',construction:'工程进度',stability:'稳定度',population:'人口',relation:'关系'};
const SITUATION_KIND_NAMES={intervention:'观众干预',adjustment:'观众调整',action:'已执行命令',result:'已发生结果',statement:'决策理由 / 公开表态',observation:'世界观察',ended:'事态结束'};
const situationName=id=>STATE?.countries?.[id]?.name||countryMeta(id)?.name||id||'未知国家';
const situationItems=()=>STATE?.situations||[];
const focusedSituation=()=>situationItems().find(item=>item.id===situationUI.focus);

function persistSituationFocus(){
  try{localStorage.setItem('eos-situation-focus:'+situationUI.world,situationUI.focus||'');}catch(_error){}
}
function refreshSituationChrome(){
  if(!STATE)return;
  const item=focusedSituation(),bar=$('situationFocusBar');
  const inMap=activeDeck==='world'||activeDeck==='situations';
  bar.hidden=!inMap||!item;
  document.body.classList.toggle('has-situation-focus',!bar.hidden);
  document.body.classList.toggle('has-situation-commands',activeDeck==='situations'&&!!item);
  if(bar.hidden)return;
  const percent=Math.round(item.progress*100);
  bar.innerHTML=`<strong>${esc(item.name)} · ${esc(item.country_name)}</strong><small>${item.status==='active'?`剩余 ${item.remaining_days} 月`:'已结束'}</small><div class="situation-progress" role="progressbar" aria-label="事态持续时间进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><i style="width:${percent}%"></i></div><span class="situation-bar-caption">${esc(item.stage)} · 已持续 ${item.elapsed} 月 · ${item.action_count} 条相关行动与结果 · 点击查看</span>`;
}
function renderSituationCommands(){
  const item=focusedSituation();
  if(!STATE.player_country){
    $('realmEmblem').textContent='E';$('realmName').textContent='世界观战';$('eraLine').textContent='上帝视角 · 互动编年';
    $('realmHome').title='世界事态与观战视角';
    $('powerBar').innerHTML=`<div class="hud-stat" data-sit-metric="active"><small>正在演进的事态</small><strong>${situationItems().filter(s=>s.status==='active').length}</strong></div><div class="hud-stat" data-sit-metric="ended"><small>已留下的编年</small><strong>${situationItems().filter(s=>s.status==='ended').length}</strong></div><div class="hud-stat" data-sit-metric="population"><small>世界人口</small><strong>${fmtInt(Object.values(STATE.countries).reduce((sum,c)=>sum+c.population,0))}</strong></div><div class="hud-stat" data-sit-metric="realms"><small>存续国家</small><strong>${Object.keys(STATE.countries).length}</strong></div>`;
  }
  $('selectionSummary').innerHTML=`<span class="eyebrow">${item?'唯一焦点':'上帝视角'}</span><b>${item?esc(item.name):'世界自主演进'}</b><p>${item?esc(item.country_name)+' · '+esc(item.stage):'选择事态，追踪国家如何回应'}</p>`;
  $('commandHint').textContent='查看与切换焦点不改变时间；所有事态持续独立演进';
  $('commandActions').innerHTML=item?`<button data-sit-action="command-locate"><b>定位焦点</b><small>${esc(item.country_name)}</small></button><button data-sit-action="command-history"><b>发展记录</b><small>行动与公开表态</small></button>${item.status==='active'?'<button data-sit-action="command-adjust"><b>调整事态</b><small>强度、时间与结束</small></button>':'<button data-sit-action="command-overview"><b>查看编年</b><small>回看这段历史</small></button>'}`:'<button data-sit-section="library"><b>施加事件</b><small>从六类预设中选择</small></button><span class="situation-command-empty">从二级列表单击事态后，相关操作会出现在这里。</span>';
}
function closeSituationHub(){
  $('situationHub').hidden=true;$('situationDetail').hidden=true;
  document.body.classList.remove('situation-hub-open','situation-detail-open');
  situationUI.preset=null;situationUI.ending=false;
}
async function openSituationHub(){
  $('situationHub').hidden=false;document.body.classList.add('situation-hub-open');
  refreshSituationChrome();renderSituationList();
  if(!situationUI.presets.length){
    try{const response=await fetch('/api/situations',{cache:'no-store'});const data=monthlyView(await response.json());if(!data.ok)throw Error(data.error);
      situationUI.presets=data.presets;situationUI.limit=data.active_limit;renderSituationList();
    }catch(error){$('situationList').textContent='事件库载入失败，请收起后重试。';showToast(error.message,true);}
  }
}
function hideSituationDetail(){
  $('situationDetail').hidden=true;document.body.classList.remove('situation-detail-open');
  situationUI.preset=null;situationUI.ending=false;refreshSituationChrome();
}
function showSituationDetail(){
  $('situationDetail').hidden=false;document.body.classList.add('situation-detail-open');refreshSituationChrome();
}
function handleSituationEscape(){
  if(activeDeck!=='situations')return false;
  if(!$('situationDetail').hidden){hideSituationDetail();return true;}
  closeSituationHub();setRail('world');refreshSituationChrome();return true;
}
function renderSituationList(){
  const ui=situationUI,host=$('situationList');
  for(const button of document.querySelectorAll('[data-sit-section]')){
    button.classList.toggle('on',button.dataset.sitSection===ui.section);
    button.setAttribute('aria-pressed',String(button.dataset.sitSection===ui.section));
  }
  if(ui.section==='library'){
    const categories=[...new Set(ui.presets.map(item=>item.category))];
    if(!ui.category){
      host.innerHTML=`<h3>先选择事件类别</h3>${categories.map(category=>`<button class="situation-category" data-sit-category="${esc(category)}"><b>${esc(category)}</b><small>${ui.presets.filter(item=>item.category===category).map(item=>esc(item.name)).join(' · ')} →</small></button>`).join('')||'<p class="situation-empty">正在读取预设事件…</p>'}<p class="situation-muted">选择预设后，再设置目标、强度与时间。</p>`;
    }else host.innerHTML=`<button class="situation-back-category" data-sit-action="categories">← 返回事件类别</button><h3>${esc(ui.category)}</h3>${ui.presets.filter(item=>item.category===ui.category).map(item=>`<button class="situation-item" data-sit-preset="${item.id}"><span><b>${esc(item.name)}</b><em>预设事件 →</em></span><small>${esc(item.description)}</small></button>`).join('')}`;
    return;
  }
  const ended=ui.section==='archive',items=situationItems().filter(item=>(item.status==='ended')===ended);
  host.innerHTML=`<h3>${ended?'已结束的事态':`正在演进 · ${items.length} / ${ui.limit}`}</h3>`+(items.map(item=>`<button class="situation-item ${item.id===ui.focus?'selected':''}" data-sit-id="${item.id}" aria-pressed="${item.id===ui.focus}"><span><b>${esc(item.name)}</b><em>${item.id===ui.focus?'当前焦点':item.stage}</em></span><small>${esc(item.country_name)}${item.partner_id?' ↔ '+esc(situationName(item.partner_id)):''}<br>第 ${item.start_day} 月起 · ${ended?`第 ${item.ended_day} 月结束`:`剩余 ${item.remaining_days} 月`}</small><div class="situation-progress"><i style="width:${Math.round(item.progress*100)}%"></i></div></button>`).join('')||`<div class="situation-empty">${ended?'结束后的事态会在这里留下编年。':'世界照常演进。施加一个预设事件，观察各国怎样回应。'}${!ended?'<button data-sit-section="library">选择预设事件 →</button>':''}</div>`);
}
function selectSituation(id){
  if(!situationItems().some(item=>item.id===id))return;
  situationUI.focus=id;situationUI.preset=null;situationUI.detail=null;situationUI.detailKey='';
  situationUI.detailTab='overview';situationUI.ending=false;persistSituationFocus();
  showSituationDetail();renderSituationList();refreshSituationChrome();renderSituationDetail();loadSituationDetail(true);render(true);
  $('situationDetailBody').scrollTop=0;renderSituationCommands();locateSituation();
}
async function loadSituationDetail(force=false){
  const item=focusedSituation();if(!item||situationUI.preset||$('situationDetail').hidden)return;
  const key=JSON.stringify([item.id,STATE.day,item.latest,item.status,item.totals]);
  if(!force&&key===situationUI.detailKey)return;
  if(situationUI.loading)return;
  situationUI.loading=true;const id=item.id;
  try{
    const response=await fetch('/api/situations?id='+encodeURIComponent(id),{cache:'no-store'});
    const data=monthlyView(await response.json());if(!data.ok)throw Error(data.error);
    if(situationUI.focus!==id||situationUI.preset)return;
    situationUI.detail=data.situation;situationUI.detailKey=key;
    // Polling updates evidence, without replacing a form the player is editing.
    if(data.situation.status==='ended'&&situationUI.detailTab==='adjust'){situationUI.detailTab='overview';$('situationDetailBody').scrollTop=0;}
    if(situationUI.detailTab!=='adjust'||!$('situationDetailBody').querySelector('form'))renderSituationDetail();
  }catch(error){showToast(error.message,true);}finally{situationUI.loading=false;}
}
function situationProgress(item){
  return `<div class="situation-progress"><i style="width:${Math.round(item.progress*100)}%"></i></div><p class="situation-muted">第 ${item.start_day} 月开始 · ${item.status==='active'?`已持续 ${item.elapsed} 月，剩余 ${item.remaining_days} 月`:`第 ${item.ended_day} 月结束 · ${esc(item.end_reason)}`}<br>此条表示持续时间，不预判各国行动和结局。</p><div class="situation-milestones">${[['intervention','施加'],['action','国家行动'],['result','相关结果'],['ended','结束']].map(([kind,label])=>`<span class="${item.milestones?.[kind]!==undefined?'reached':''}">${label}<small>${item.milestones?.[kind]!==undefined?'第 '+item.milestones[kind]+' 月':'待观察'}</small></span>`).join('')}</div>`;
}
function effectDescription(spec,intensity=2){
  const strength={1:.5,2:1,3:1.5}[intensity]||1;
  const days=STATE?.calendar?.remaining_days||STATE?.month_days||30;
  return Object.entries(spec.effects).map(([key,value])=>{
    let detail;
    if(['food','tax','research','construction'].includes(key))detail=`${value>0?'+':''}${Math.round(value*strength*100)}%`;
    else if(key==='population')detail=`本月约 ${value>0?'+':''}${((Math.pow(1+value*strength,days)-1)*100).toFixed(2)}%`;
    else if(key==='stability')detail=`本月约 ${value>0?'+':''}${(value*strength*days).toFixed(2)}`;
    else detail=`本月约 ${value>0?'+':''}${value*(intensity===1?Math.ceil(days/2):days*(intensity===3?2:1))}（受关系上下限约束）`;
    return `${SITUATION_EFFECT_NAMES[key]} ${detail}`;
  }).join('；');
}
function renderSituationDetail(){
  const ui=situationUI,item=ui.detail,host=$('situationDetailBody');
  if(!item||item.id!==ui.focus){host.innerHTML='<p>正在读取事态记录…</p>';return;}
  const previousScroll=host.scrollTop,dataOpen=!!host.querySelector('.situation-data-fold[open]');
  const spec=ui.presets.find(p=>p.id===item.preset_id);
  const heading=`<div class="situation-title-line"><span>${esc(item.category)} / ${esc(item.stage)}</span><span>唯一焦点</span></div><h2>${esc(item.name)}</h2><p>${esc(item.country_name)}${item.partner_id?' ↔ '+esc(situationName(item.partner_id)):''}</p>${situationProgress(item)}<nav class="situation-detail-tabs" aria-label="所选事态详情"><button data-sit-tab="overview" class="${ui.detailTab==='overview'?'on':''}">概况</button><button data-sit-tab="history" class="${ui.detailTab==='history'?'on':''}">发展记录</button><button data-sit-tab="adjust" class="${ui.detailTab==='adjust'?'on':''}" ${item.status==='ended'?'disabled':''}>调整</button></nav>`;
  let content='';
  if(ui.detailTab==='history'){
    content=`<p class="situation-muted">记录覆盖期间相关国家的行动；相关不代表都由本事态引起。表态与已执行命令分别标记。</p><ol class="situation-history">${item.history.slice().reverse().map(row=>`<li data-kind="${row.kind}"><small>第 ${row.source_day??row.day} 月 · ${SITUATION_KIND_NAMES[row.kind]||row.kind}${row.country_id?' · '+esc(situationName(row.country_id)):''}</small>${row.kind==='statement'?`<blockquote>“${esc(row.text)}”</blockquote>`:`<p>${esc(row.text)}</p>`}${row.source_sequence?`<span class="situation-evidence">${row.kind==='statement'?'原始表态':'世界记录'} #${row.source_sequence}</span>`:''}</li>`).join('')}</ol>`;
  }else if(ui.detailTab==='adjust'&&item.status==='active'){
    content=`<p>调整只影响之后的演进。此前的资源消耗、人口变化、外交与建设结果会保留。</p><form id="situationAdjustForm" class="situation-form"><label>事件强度<select name="intensity">${[1,2,3].map((n,i)=>`<option value="${n}" ${n===item.intensity?'selected':''}>${['轻微','适中','强烈'][i]}</option>`).join('')}</select></label><label>剩余时间（游戏月）<input name="remaining_months" type="number" min="1" max="24" step="1" value="${item.remaining_days}" required></label><div class="situation-effect-preview" id="situationEffectPreview">${spec?esc(effectDescription(spec,item.intensity)):''}</div><button class="primary" type="submit" ${ui.busy?'disabled':''}>保存调整</button></form><p id="situationFormMessage" class="situation-result-message" aria-live="polite"></p><h3>提前结束</h3><p class="situation-muted">立即停止持续影响，并将目前结果收入编年。</p>${ui.ending?'<div class="situation-confirm"><p>结束这个事态？已经产生的结果将保留。</p><button class="situation-danger" data-sit-action="end-confirm">确认结束</button><button data-sit-action="end-cancel">继续演进</button></div>':'<button class="situation-danger" data-sit-action="end">提前结束此事态</button>'}`;
  }else{
    const first=item.initial||{},now=item.current||{},keys=[['food','粮仓'],['treasury','国库'],['population','人口'],['stability','稳定度'],...(item.partner_id?[['relation','两国关系']]:[])];
    content=`${spec?`<div class="situation-effect-preview">${esc(effectDescription(spec,item.intensity))}</div>`:''}<div class="situation-detail-actions"><button data-sit-action="locate">定位影响国家</button><button data-sit-action="unfocus">取消焦点</button></div>${item.chronicle?`<h3>这段历史</h3><div class="situation-chronicle">${esc(item.chronicle)}</div>`:''}<h3>事态前后 · 世界实况</h3>${item.current?`<table class="situation-metrics"><thead><tr><th>指标</th><th>开始时</th><th>${item.status==='ended'?'结束时':'现在'}</th><th>净变化</th></tr></thead><tbody>${keys.map(([key,label])=>`<tr><td>${label}</td><td>${fmtNum(first[key]||0,key==='population'?0:1)}</td><td>${fmtNum(now[key]||0,key==='population'?0:1)}</td><td>${signedValue((now[key]||0)-(first[key]||0))}</td></tr>`).join('')}</tbody></table>`:'<p>目标国家已退出世界。</p>'}<p class="situation-muted">这些净变化包含同期其他因素。下列直接影响单独记账。</p><div class="situation-ledger">${Object.entries(item.totals).map(([key,value])=>`${SITUATION_EFFECT_NAMES[key]}累计直接影响：${signedValue(value)}${['food','tax'].includes(key)?' 单位':key==='construction'?' 工程进度点':key==='research'?' 基础研究点':''}`).join('<br>')||'尚未发生每月结算。'}</div><h3>相关国家如何回应</h3>${item.participants.map(id=>{
      const action=item.history.filter(row=>row.country_id===id&&['action','result'].includes(row.kind)).at(-1);
      const quote=item.history.filter(row=>row.country_id===id&&row.kind==='statement').at(-1);
      return `<section class="situation-country-response"><strong>${esc(situationName(id))}</strong><p>${action?`已记录：${esc(action.text)}`:STATE.player_country===id?'由玩家执政，等待玩家下令。':'尚无新的相关行动；世界仍在演进。'}</p>${quote?`<blockquote>“${esc(quote.text)}”</blockquote><span class="situation-evidence">第 ${quote.source_day??quote.day} 月 · 决策理由 / 公开表态</span>`:'<span class="situation-evidence">尚无新的决策理由或公开表态。</span>'}</section>`;
    }).join('')}`;
  }
  host.innerHTML=heading+content;
  if(item.status==='ended'){
    const effect=host.querySelector('.situation-effect-preview');
    if(effect)effect.textContent='最后设置：'+effect.textContent+'（持续影响已停止）';
  }
  if(ui.detailTab==='overview'){
    // Lead with state and country reactions. Keep the audit numbers one click deeper.
    const responseTitle=Array.from(host.querySelectorAll('h3')).find(node=>node.textContent==='相关国家如何回应');
    const dataTitle=Array.from(host.querySelectorAll('h3')).find(node=>node.textContent==='事态前后 · 世界实况');
    if(responseTitle&&dataTitle){
      const reactions=[];for(let node=responseTitle;node;node=node.nextElementSibling)reactions.push(node);
      const nodes=[];for(let node=dataTitle;node&&node!==responseTitle;node=node.nextElementSibling)nodes.push(node);
      const fold=document.createElement('details');fold.className='situation-data-fold';
      fold.open=dataOpen;
      const summary=document.createElement('summary');summary.textContent='展开世界实况与直接影响';fold.appendChild(summary);
      for(const node of nodes){if(node!==dataTitle)fold.appendChild(node);else node.remove();}
      for(const node of reactions)host.appendChild(node);
      host.appendChild(fold);
    }
  }
  host.scrollTop=previousScroll;
}
function openSituationPreset(id){
  const spec=situationUI.presets.find(item=>item.id===id);if(!spec)return;
  situationUI.preset=id;situationUI.ending=false;showSituationDetail();
  const countries=Object.keys(STATE.countries),target=STATE.countries[selectedCountry]?selectedCountry:countries[0];
  const options=selected=>countries.map(id=>`<option value="${esc(id)}" ${id===selected?'selected':''}>${esc(situationName(id))}</option>`).join('');
  $('situationDetailBody').innerHTML=`<div class="situation-title-line">事件预设 / ${esc(spec.category)}</div><h2>${esc(spec.name)}</h2><p>${esc(spec.description)}</p><form id="situationCreateForm" class="situation-form"><label>施加对象<select name="country_id">${options(target)}</select></label>${spec.bilateral?`<label>另一个国家<select name="partner_id">${options(countries.find(id=>id!==target))}</select></label>`:''}<label>事件强度<select name="intensity"><option value="1">轻微</option><option value="2" selected>适中</option><option value="3">强烈</option></select></label><label>持续时间（游戏月）<input name="duration_months" type="number" min="1" max="24" step="1" value="3" required></label><div class="situation-effect-preview" id="situationEffectPreview">${esc(effectDescription(spec))}</div><p class="situation-muted">同一目标不可重复叠加同类事态。最多同时进行 ${situationUI.limit} 个。施加后在列表单击它，才会切换焦点。</p><button class="primary" type="submit">施加事件</button></form><p id="situationFormMessage" class="situation-result-message" aria-live="polite"></p>`;
  $('situationDetailBody').scrollTop=0;
}
async function sendSituation(payload){
  if(situationUI.busy)return null;situationUI.busy=true;
  const submit=$('situationDetailBody').querySelector('button[type=submit]');if(submit)submit.disabled=true;
  const message=$('situationFormMessage');if(message){message.textContent='正在提交…';message.classList.remove('situation-form-error');}
  try{
    const response=await fetch('/api/situations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=monthlyView(await response.json());if(!response.ok||!data.ok)throw Error(data.error||'事态操作未成功');
    await poll(true);return data.situation;
  }catch(error){if(message?.isConnected){message.textContent=error.message;message.classList.add('situation-form-error');}else showToast(error.message,true);return null;}
  finally{situationUI.busy=false;if(submit?.isConnected)submit.disabled=false;}
}
async function refreshSituations(){
  if(!STATE)return;
  const world=STATE.current_save_id||'unsaved';
  if(situationUI.world!==world){
    situationUI.world=world;situationUI.detail=null;situationUI.detailKey='';situationUI.signature='';
    try{situationUI.focus=localStorage.getItem('eos-situation-focus:'+world)||null;}catch(_error){situationUI.focus=null;}
  }
  if(situationUI.focus&&!focusedSituation()){situationUI.focus=null;situationUI.detail=null;persistSituationFocus();}
  const signature=JSON.stringify(situationItems());
  if(signature!==situationUI.signature){situationUI.signature=signature;if(!$('situationHub').hidden)renderSituationList();}
  refreshSituationChrome();await loadSituationDetail();
}
function locateSituation(){
  const item=focusedSituation();if(!item)return;
  const country=STATE.countries[item.country_id];const center=country?.cities?.[0]?.center;if(!center){showToast('目标国家已退出世界',true);return;}
  const scale=fitScale*zoom;let left=0;
  const panel=!$('situationDetail').hidden?$('situationDetail'):!$('situationHub').hidden?$('situationHub'):null;
  if(panel&&innerWidth>600)left=panel.getBoundingClientRect().right-mapPanel.getBoundingClientRect().left+12;
  panX=(left+mapPanel.clientWidth)/2-baseOffX-cx(center)*scale;
  panY=mapPanel.clientHeight*.56-baseOffY-cy(center)*scale;
  constrainMapView(left,50,mapPanel.clientWidth,mapPanel.clientHeight-48);render(true);
}
function drawSituationOverlay(scale){
  const item=focusedSituation();if(!item||!STATE?.countries[item.country_id])return;
  const c=STATE.countries[item.country_id],capital=c.cities?.[0]?.center;if(!capital)return;
  ctx.save();ctx.fillStyle='#e4bb5b';ctx.globalAlpha=item.status==='active'?.17:.07;
  for(const coord of c.tiles||[]){hexPath(cx(coord),cy(coord),.94);ctx.fill();}
  ctx.globalAlpha=.95;ctx.strokeStyle='#f2cf83';ctx.lineWidth=1.6/scale;ctx.setLineDash([4/scale,4/scale]);
  ctx.beginPath();ctx.arc(cx(capital),cy(capital),1.05,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
  if(item.partner_id){const partner=STATE.countries[item.partner_id]?.cities?.[0]?.center;if(partner){ctx.beginPath();ctx.moveTo(cx(capital),cy(capital));ctx.lineTo(cx(partner),cy(partner));ctx.stroke();}}
  ctx.restore();
}
$('situationFocusBar').onclick=async()=>{const id=situationUI.focus;await openDeck('situations',true);if(id)selectSituation(id);};
$('realmHome').onclick=()=>activeDeck==='situations'&&!STATE?.player_country?openDeck('situations',true):strategyOpenRealm();
document.addEventListener('click',event=>{
  const section=event.target.closest('[data-sit-section]'),category=event.target.closest('[data-sit-category]'),preset=event.target.closest('[data-sit-preset]'),item=event.target.closest('[data-sit-id]'),tab=event.target.closest('[data-sit-tab]'),action=event.target.closest('[data-sit-action]');
  if(section){situationUI.section=section.dataset.sitSection;hideSituationDetail();renderSituationList();}
  else if(category){situationUI.category=category.dataset.sitCategory;renderSituationList();}
  else if(preset)openSituationPreset(preset.dataset.sitPreset);
  else if(item)selectSituation(item.dataset.sitId);
  else if(tab){situationUI.detailTab=tab.dataset.sitTab;situationUI.ending=false;renderSituationDetail();$('situationDetailBody').scrollTop=0;}
  else if(action){switch(action.dataset.sitAction){
    case'close':closeSituationHub();setRail('world');refreshSituationChrome();break;
    case'back':case'detail-close':hideSituationDetail();renderSituationList();break;
    case'categories':situationUI.category=null;hideSituationDetail();renderSituationList();break;
    case'locate':locateSituation();break;
    case'command-locate':locateSituation();break;
    case'command-history':case'command-adjust':case'command-overview':if(situationUI.focus){situationUI.preset=null;situationUI.detailTab=action.dataset.sitAction==='command-history'?'history':action.dataset.sitAction==='command-adjust'?'adjust':'overview';showSituationDetail();renderSituationDetail();loadSituationDetail();$('situationDetailBody').scrollTop=0;}break;
    case'unfocus':situationUI.focus=null;situationUI.detail=null;persistSituationFocus();hideSituationDetail();refreshSituationChrome();renderSituationList();render(true);break;
    case'end':situationUI.ending=true;renderSituationDetail();break;
    case'end-cancel':situationUI.ending=false;renderSituationDetail();break;
    case'end-confirm':if(!situationUI.busy)sendSituation({operation:'end',id:situationUI.focus}).then(item=>{if(item){if(situationUI.focus===item.id&&!situationUI.preset){situationUI.detail=item;situationUI.detailTab='overview';situationUI.ending=false;situationUI.section='archive';renderSituationList();renderSituationDetail();$('situationDetailBody').scrollTop=0;}showToast('事态已结束，编年已保存');}});break;
  }}
  if(activeDeck==='situations')renderSituationCommands();
});
$('situationDetailBody').addEventListener('change',event=>{
  if(event.target.name!=='intensity')return;
  const spec=situationUI.presets.find(item=>item.id===(situationUI.preset||situationUI.detail?.preset_id));
  if(spec&&$('situationEffectPreview'))$('situationEffectPreview').textContent=effectDescription(spec,Number(event.target.value));
});
$('situationDetailBody').addEventListener('submit',async event=>{
  const form=event.target;if(!['situationCreateForm','situationAdjustForm'].includes(form.id))return;
  event.preventDefault();if(situationUI.busy||!form.reportValidity())return;
  const values=Object.fromEntries(new FormData(form));values.intensity=Number(values.intensity);
  if(form.id==='situationCreateForm'){
    values.duration_months=Number(values.duration_months);values.preset_id=situationUI.preset;const submittedPreset=situationUI.preset;
    const item=await sendSituation({operation:'create',event:values});
    if(item){if(situationUI.preset===submittedPreset){situationUI.section='active';hideSituationDetail();renderSituationList();}showToast('事件已施加；单击列表中的事态可设为焦点');}
  }else{
    values.remaining_months=Number(values.remaining_months);
    const submittedId=situationUI.focus;const item=await sendSituation({operation:'update',id:submittedId,changes:values});
    if(item){if(situationUI.focus===submittedId&&!situationUI.preset){situationUI.detail=item;renderSituationDetail();const message=$('situationFormMessage');if(message)message.textContent='调整已保存；后续结算按新设置推进。';}else showToast('事态调整已保存');}
  }
});
