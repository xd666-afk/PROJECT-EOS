/* Object selection and commands. RuleEngine remains the only state writer. */
let strategyCommand='inspect',strategyBusy=false,diplomacyFocus=null;

function governingRealm(){return STATE?.countries?.[STATE.player_country]?STATE.player_country:selectedCountry;}
function controlledArmy(){return STATE?.countries?.[STATE.player_country]?.armies?.find(a=>a.army_id===selectedArmy&&a.strength>0)||null;}
function strategyCity(tile){return tile?.owner?STATE?.countries?.[tile.owner]?.cities?.find(c=>c.center[0]===tile.col&&c.center[1]===tile.row):null;}
function signedValue(value){return `${value>=0?'+':''}${fmtNum(value,2)}`;}

function renderStrategyHeader(){
  if(!STATE)return;
  const id=governingRealm(),c=STATE.countries[id];if(!c)return;
  const meta=countryMeta(id),economy=c.last_economy||{},playing=!!STATE.countries[STATE.player_country];
  document.documentElement.style.setProperty('--accent',countryColor(id));
  $('realmEmblem').textContent=id;$('realmName').textContent=meta?.name||id;
  $('realmHome').title=`${playing?'正在治理':'正在查看'} ${meta?.name||id} · 点击打开国家概览`;
  $('eraLine').textContent=`${c.era?.short||'文明'} · ${playing?'玩家执政':'观战视角'}`;
  $('powerBar').innerHTML=`
    <button class="hud-stat" data-hud="finance" title="打开国家财政，查看每日收支与税率"><small>国库 · 民政结余</small><strong>${fmtNum(c.treasury,1)}<i class="${(economy.treasury_income||0)>=0?'gain':'loss'}">${signedValue(economy.treasury_income||0)} / 日</i></strong></button>
    <button class="hud-stat" data-hud="food" title="查看各城粮仓与运输"><small>粮食 · 仓容 ${fmtNum(c.food_capacity,0)}</small><strong>${fmtNum(c.food,1)}<i>粮食物流</i></strong></button>
    <button class="hud-stat" data-hud="population" title="查看城市人口与治理"><small>人口 · ${c.cities?.length||0} 座城市</small><strong>${fmtInt(c.population)}</strong></button>
    <button class="hud-stat" data-hud="stability" title="查看稳定、政策与国家概况"><small>稳定度</small><strong>${fmtNum(c.stability,0)}<i>${c.stability<35?'动荡':c.stability>65?'安定':'平稳'}</i></strong></button>`;
  $('timeState').textContent=STATE.paused?'实时演进 · 已暂停':'实时演进 · 运行中';
  $('nextPlan').textContent=`第 ${STATE.day} 日 · ${STATE.paused?'等待指令':STATE.speed+' 日 / 秒'}`;
  $('stepBtn').textContent='推进 1 日';$('pauseBtn').title='空格：暂停 / 继续';
}

function commandButton(key,label,detail='',options={}){
  return `<button data-command="${key}" class="${options.primary?'primary ':''}${options.active?'on':''}" ${options.disabled||strategyBusy?'disabled':''}${options.title?` title="${esc(options.title)}"`:''}><b>${esc(label)}</b><small>${esc(detail||' ')}</small></button>`;
}

function refreshStrategyUI(){
  if(!STATE||!$('commandActions'))return;
  renderStrategyHeader();
  if(strategyCommand==='road'&&!roadPlan)strategyCommand='inspect';
  const tile=selectedTileData(),city=strategyCity(tile),army=controlledArmy();
  const controlled=STATE.countries[STATE.player_country]?STATE.player_country:null,owned=!!controlled&&tile?.owner===controlled;
  if(roadPlan&&roadPlan.actor!==controlled){roadPlan=null;strategyCommand='inspect';}
  const country=STATE.countries[governingRealm()];
  let summary='',hint='',buttons=[];
  if(tile){
    const owner=countryMeta(tile.owner)?.name||tile.owner||'无主地';
    summary=`<span class="eyebrow"><i class="summary-mark"></i>${esc(owner)} · ${tile.col}, ${tile.row}</span><b>${esc(city?.name||BIOME_NAMES[tile.biome]||tile.biome)}</b><p>${esc(army?`${army.army_id} · ${army.strength} 支${army.march?` · 在途 ${army.march.days_left} 天`:''}`:tile.river?'河道地块':roadCellAt(tile.col,tile.row)?'道路与设施可共存':tile.land?'陆地':'水域')}</p>`;
  }else{
    summary=`<span class="eyebrow">${controlled?'正在治理':'观战视角'}</span><b>${esc(countryMeta(governingRealm())?.name||governingRealm()||'世界地图')}</b><p>${country?.tiles?.length||0} 格领土 · ${country?.cities?.length||0} 座城市<br>点击地图上的城市、军队或地块</p>`;
  }
  if(roadPlan?.actor===controlled){
    strategyCommand='road';
    const quote=roadPlan.quote,valid=tile?.owner===controlled&&roadPlan.end?.[0]===tile?.col&&roadPlan.end?.[1]===tile?.row;
    const ready=quote&&valid&&!roadPlan.loading&&!roadPlan.error&&quote.affordable&&quote.segments.length>0;
    hint=roadPlan.error||`道路起点 ${roadPlan.start.join(', ')} · ${quote&&valid?`${quote.segments.length} 格新建，${fmtNum(quote.cost,1)} 财政，${quote.estimated_days??'待定'} 日`:'点击本国另一格陆地选择终点'}`;
    buttons=[commandButton('confirm-road','整段开工',quote&&valid?`${fmtNum(quote.cost,1)} 财政 · 依次施工`:'等待路线报价',{primary:true,disabled:!ready}),commandButton('cancel','取消规划','Esc')];
  }else if(strategyCommand==='move'&&army){
    const frame=tile&&tilePrice(tile)?.march,row=frame?.rows?.find(r=>r.army_id===army.army_id);
    const ready=row?.reachable&&row.reason!=='ALREADY_THERE'&&!army.march;
    hint=army.march?`这支军队正在行军，剩余 ${army.march.days_left} 天`:
      !tile?'在地图点选目的地，路径与天数会在确认前显示':
      !row?'正在核对这支军队到目的地的路线…':row.reason==='ALREADY_THERE'?'请选择与军队当前位置不同的目的地':marchRowLine(row,frame?.cap);
    buttons=[commandButton('confirm-move','确认移动',ready?`${row.days} 天 · ${fmtNum(row.cost,2)} 移动成本`:'选择可达目的地',{primary:true,disabled:!ready}),commandButton('locate-army','定位军队',army.army_id),commandButton('cancel','取消选点','Esc')];
  }else{
    if(strategyCommand==='move'&&!army)strategyCommand='inspect';
    hint=controlled?(tile?owned?'本国地块 · 选择命令后查看条件与费用':tile.owner?'外国领土 · 查看关系或打开外交':'无主地 · 查看建城条件':'地图选对象，底部下命令；空格暂停 / 继续'):'观战模式 · 可查看信息，接管国家后下令';
    if(tile){
      if(owned){
        buttons.push(commandButton('build','建设','B · 设施与修筑条件',{active:inspectorMode==='build'&&strategyCommand==='build'}));
        if(tile.land)buttons.push(commandButton('road','修筑道路','R · 选择起终点'));
        const camp=(STATE.countries[controlled]?.barracks||[]).find(c=>c.tile[0]===tile.col&&c.tile[1]===tile.row);
        if(camp)buttons.push(commandButton('recruit','募兵',camp.recruiting?'查看练兵进度':'兵种与数量'));
      }
      if(army){
        buttons.push(commandButton('move','移动',army.march?`在途 ${army.march.days_left} 天`:`M · ${army.army_id}`,{disabled:!!army.march}));
        if(army.march)buttons.push(commandButton('locate-army','定位军队',army.army_id));
      }
      if(city)buttons.push(commandButton('city','城市治理',city.name));
      if(!tile.owner&&controlled&&tile.land)buttons.push(commandButton('settle','建立新城','查看人口与财政条件'));
      if(tile.owner&&tile.owner!==controlled)buttons.push(commandButton('diplomacy','外交',`与 ${countryMeta(tile.owner)?.name||tile.owner}`));
      if(tile.owner&&tile.owner!==controlled&&army)buttons.push(commandButton('attack','进攻选项','查看宣战、目标与战果预估'));
      buttons.push(commandButton('info','地块详情','设施、粮仓与地形'));
    }else{
      buttons=[commandButton('finance','国家财政','税率与每日收支'),commandButton('cities','城市','粮仓与地方治理'),commandButton('armies','军队','选择军队与兵营'),commandButton('research','科技','选择研究分支'),commandButton('diplomacy','外交','关系与提案')];
    }
    if(tile)buttons.push(commandButton('clear','取消选择','返回国家视角'));
  }
  if(window.matchMedia('(max-width:600px)').matches&&(strategyCommand==='move'||roadPlan)){
    $('worldRight').classList.add('collapsed');$('worldLeft').classList.add('collapsed');
    document.body.classList.remove('right-panel-open');$('leftReopen').hidden=false;
  }
  $('selectionSummary').innerHTML=summary;$('commandHint').textContent=hint;$('commandHint').title=hint;
  $('commandActions').innerHTML=buttons.join('');
  if(!$('nationModal').hidden&&nationTab==='finance')renderStrategyFinance();
}

function selectStrategyTile(coord){
  if(!STATE||!getTile(...coord))return;
  if(strategyCommand!=='move'&&!roadPlan)pickMapArmy(coord);
  selectedTile=[...coord];
  const owner=selectedTileData()?.owner;
  if(strategyCommand!=='move'&&!roadPlan){
    selectedCountry=STATE.countries[owner]?owner:governingRealm();
    inspectorMode=controlledArmy()&&controlledArmy().tile?.join(',')===coord.join(',')?'orders':'info';
  }
  renderTop();renderCountries();renderRight();render(true);showDetailTab();
}

async function strategyOpenRealm(tab='overview'){
  const id=governingRealm();if(!id)return;
  selectedCountry=id;renderTop();renderCountries();renderRight();
  await openDeck('nation',true);setNationTab(tab);
}

async function strategyOpenDiplomacy(target=null){
  diplomacyFocus=target;
  selectedCountry=governingRealm();renderTop();renderCountries();renderRight();
  await openDeck('diplo',true);diploFilter='relations';
  for(const b of document.querySelectorAll('#diploTabs button'))b.classList.toggle('on',b.dataset.diploFilter==='relations');
  renderDiplomacy();
  for(const section of document.querySelectorAll('#diploBody [data-diplo-section]'))section.hidden=section.dataset.diploSection!=='relations';
}

function showStrategyInspector(mode){
  inspectorMode=mode;renderRight();showDetailTab();
  const scroller=$('worldRight').querySelector('.scroll');if(scroller)scroller.scrollTop=0;
}

async function runStrategyCommand(command){
  if(!STATE||strategyBusy)return;
  if(activeDeck!=='world'&&['clear','build','settle','info','recruit','attack','road','move','locate-army','armies'].includes(command))await closeAllDecks();
  const tile=selectedTileData(),army=controlledArmy();
  if(command==='cancel'){
    strategyCommand='inspect';roadPlan=null;refreshStrategyUI();renderRight();render(true);return;
  }
  if(command==='clear'){
    strategyCommand='inspect';roadPlan=null;selectedTile=null;selectedArmy=null;
    if(STATE.player_country)selectedCountry=STATE.player_country;
    setSidePanel('right',false);setSidePanel('left',true);renderTop();renderCountries();renderRight();render(true);return;
  }
  if(command==='finance')return strategyOpenRealm('finance');
  if(command==='research'){
    selectedCountry=governingRealm();return openDeck('tech',true);
  }
  if(command==='cities'){
    selectedCountry=governingRealm();return openDeck('city',true);
  }
  if(command==='armies'){
    selectedCountry=governingRealm();selectedTile=null;objectTab='armies';setSidePanel('right',false);setSidePanel('left',true);renderCountries();renderRight();return;
  }
  if(command==='diplomacy')return strategyOpenDiplomacy(tile?.owner&&tile.owner!==STATE.player_country?tile.owner:null);
  if(command==='city'&&tile){
    const city=strategyCity(tile);if(!city)return;
    selectedCountry=tile.owner;await openDeck('city',true);openCityDetail(city.city_id);return;
  }
  if(command==='build'||command==='settle'){
    strategyCommand='build';showStrategyInspector('build');return;
  }
  if(command==='info')return showStrategyInspector('info');
  if(command==='recruit'||command==='attack'){
    showStrategyInspector('orders');
    const section=command==='recruit'?document.querySelector('#panel-tile .barracks-panel'):document.querySelector('#panel-tile [data-field-war],#panel-tile [data-strike]');
    section?.scrollIntoView({block:'nearest'});return;
  }
  if(command==='road'&&tile){
    if(!STATE.player_country||tile.owner!==STATE.player_country)return;
    strategyCommand='road';roadPlan={actor:STATE.player_country,start:[tile.col,tile.row],quote:null};showStrategyInspector('build');render(true);return;
  }
  if(command==='confirm-road'){
    const button=$('roadConfirmBtn');if(button&&!button.disabled)button.click();return;
  }
  if(command==='move'&&army){
    strategyCommand='move';showStrategyInspector('orders');refreshStrategyUI();render(true);return;
  }
  if(command==='locate-army'&&army?.tile){
    focusTile(...army.tile);return;
  }
  if(command==='confirm-move'&&army&&tile){
    const row=tilePrice(tile)?.march?.rows?.find(r=>r.army_id===army.army_id);
    if(!row?.reachable||row.reason==='ALREADY_THERE'||army.march)return;
    strategyBusy=true;refreshStrategyUI();
    try{
      const data=await submitPlayerAction({type:'MILITARY',operation:'MARCH',army_id:army.army_id,tile:{col:tile.col,row:tile.row}},'行军令已下达，军队将随时间移动');
      if(data?.ok)strategyCommand='inspect';
    }finally{strategyBusy=false;refreshStrategyUI();render(true);}
  }
}

function renderStrategyFinance(){
  const host=$('nationFinance'),country=STATE?.countries?.[selectedCountry];if(!host||!country)return;
  const active=document.activeElement;
  if(host.dataset.realm===selectedCountry&&active&&host.contains(active)&&['INPUT','SELECT'].includes(active.tagName))return;
  host.dataset.realm=selectedCountry;
  const economy=country.last_economy||{},own=STATE.player_country===selectedCountry,disabled=own?'':'disabled';
  const income=(economy.tax_income||0)+(economy.mine_income||0),expense=(economy.upkeep||0)+(economy.city_service_spend||0);
  const line=(name,value,sign='')=>`<div class="finance-line"><span>${name}</span><b class="${sign==='-'?'loss':sign==='+'?'gain':''}">${sign}${fmtNum(value||0,3)}</b></div>`;
  host.innerHTML=`${own?'':`<div class="foreign-context">${STATE.player_country?'正在查看其他国家的财政，治理权仍属于 '+esc(countryMeta(STATE.player_country)?.name||STATE.player_country):'观战视角 · 接管国家后可调整财政与劳力'}</div>`}
    <p class="finance-note">${esc(countryMeta(selectedCountry)?.name||selectedCountry)} · 当前国库 ${fmtNum(country.treasury,2)} · 第 ${STATE.day} 日。下列是最近一次每日结算；军费和外交支出单独列示。</p>
    <div class="finance-ledger">
      <section class="finance-card"><h3>每日收入</h3>${line('税收',economy.tax_income,'+')}${line('矿业收入',economy.mine_income,'+')}${line('收入合计',income,'+')}</section>
      <section class="finance-card"><h3>每日民政支出</h3>${line('设施维护',economy.upkeep,'-')}${line('城市服务',economy.city_service_spend,'-')}${line('民政支出合计',expense,'-')}</section>
      <section class="finance-card wide"><h3>民政结余 · ${signedValue(economy.treasury_income||0)} / 日</h3><p class="finance-note">民政结余不含军费、募兵和外交交易。军费见军事面板，单次支出见命令回执。</p>${line('粮食生产',economy.food_production)}${line('粮食消费',economy.food_consumption)}${line('物流损耗',economy.food_logistics_loss)}</section>
      <section class="finance-card finance-form"><h3>税率</h3><label>征收比例 <b id="financeTaxValue">${Math.round(country.tax_rate*100)}%</b><input id="financeTaxRate" aria-label="税率" type="range" min="0" max="${Math.round(STATE.maximum_tax_rate*100)}" step="1" value="${Math.round(country.tax_rate*100)}" ${disabled}></label><p class="finance-note">从下一次每日结算生效；较高税率也会影响产出与稳定。</p><button id="financeTaxApply" ${disabled}>应用税率</button></section>
      <section class="finance-card finance-form"><h3>全国劳动力</h3><label>农业比例 %<input id="financeAgriculture" aria-label="农业劳动力" type="number" min="0" max="100" step="1" value="${Math.round(country.workers.agriculture*100)}" ${disabled}></label><label>矿业比例 %<input id="financeMining" aria-label="矿业劳动力" type="number" min="0" max="100" step="1" value="${Math.round(country.workers.mining*100)}" ${disabled}></label><p class="finance-note" id="financeConstruction"></p><button id="financeWorkersApply" ${disabled}>应用劳动力分配</button></section>
      <section class="finance-card wide"><h3>城市地方预算</h3>${(country.cities||[]).map(city=>`<div class="finance-city"><span><b>${esc(city.name)}</b>${esc(city.budget_label||city.budget)} · 收支 ${signedValue(city.local_net||0)} / 日</span><button data-finance-city="${city.city_id}">进入治理</button></div>`).join('')}</section>
    </div>`;
  $('financeTaxRate').oninput=()=>{$('financeTaxValue').textContent=$('financeTaxRate').value+'%';};
  const allocations=()=>{
    const farm=Number($('financeAgriculture').value),mine=Number($('financeMining').value);
    const valid=Number.isInteger(farm)&&Number.isInteger(mine)&&farm>=0&&mine>=0&&farm+mine<=100;
    $('financeConstruction').textContent=valid?`建筑劳动力 ${100-farm-mine}% · 总计 100%`:'农业与矿业合计必须在 0–100% 之间';
    $('financeWorkersApply').disabled=!own||!valid;
    return valid?{agriculture:farm/100,mining:mine/100,construction:(100-farm-mine)/100}:null;
  };
  $('financeAgriculture').oninput=allocations;$('financeMining').oninput=allocations;allocations();
  const realm=selectedCountry;
  $('financeTaxApply').onclick=async()=>{
    if(STATE.player_country!==realm)return;
    const rate=Number($('financeTaxRate').value)/100;
    $('financeTaxApply').disabled=true;await submitPlayerAction({type:'SET_TAX',rate},'税率已调整，将进入下一次每日结算');renderStrategyFinance();
  };
  $('financeWorkersApply').onclick=async()=>{
    const workers=allocations();if(STATE.player_country!==realm||!workers)return;
    $('financeWorkersApply').disabled=true;await submitPlayerAction({type:'ALLOCATE_WORKERS',...workers},'劳动力已调整');renderStrategyFinance();
  };
  for(const button of host.querySelectorAll('[data-finance-city]'))button.onclick=async()=>{
    await openDeck('city',true);openCityDetail(button.dataset.financeCity);
  };
}

// Keep the existing time controls as a single set of DOM nodes, always on screen.
$('hudUtilities').append(document.querySelector('.hud-actions'));
$('timeDock').append(document.querySelector('.timebox'));
$('realmHome').onclick=()=>strategyOpenRealm();
document.addEventListener('click',async event=>{
  const command=event.target.closest('[data-command]');if(command){runStrategyCommand(command.dataset.command);return;}
  const stat=event.target.closest('[data-hud]');if(!stat)return;
  if(stat.dataset.hud==='finance')strategyOpenRealm('finance');
  else if(stat.dataset.hud==='stability')strategyOpenRealm();
  else if(stat.dataset.hud==='food'){
    await closeAllDecks();strategyCommand='inspect';roadPlan=null;selectedTile=null;
    selectedCountry=governingRealm();objectTab='cities';setSidePanel('right',false);setSidePanel('left',true);mapMode='logistics';
    for(const button of document.querySelectorAll('[data-layer]'))button.classList.toggle('on',button.dataset.layer===mapMode);
    renderCountries();renderRight();updateMapLegend();render(true);
  }else runStrategyCommand('cities');
});
canvas.addEventListener('contextmenu',event=>{
  event.preventDefault();const army=controlledArmy(),coord=nearestTile(event.clientX,event.clientY);
  if(!army||army.march||!coord)return;
  strategyCommand='move';selectStrategyTile(coord);
});
document.addEventListener('keydown',event=>{
  if(!gameLoaded||!STATE||event.repeat)return;
  if(event.target.closest('input,select,textarea,[contenteditable=true]'))return;
  if(event.key==='Escape'&&activeDeck==='world'&&(roadPlan||strategyCommand==='move')){
    event.preventDefault();event.stopImmediatePropagation();runStrategyCommand('cancel');return;
  }
  if(event.code==='Space'){
    if(!$('pauseMenu').hidden)return;
    event.preventDefault();event.stopImmediatePropagation();control(STATE.paused?'resume':'pause');return;
  }
  if(activeDeck!=='world'||event.ctrlKey||event.metaKey||event.altKey)return;
  const key=event.key.toLowerCase(),command={b:'build',r:'road',m:'move',f:'diplomacy'}[key];
  if(command&&(selectedTile||key==='f')){event.preventDefault();runStrategyCommand(command);}
},true);

const compactStrategyLayout=window.matchMedia('(max-width:600px)');
function adaptStrategyViewport(){
  if(compactStrategyLayout.matches){setSidePanel('left',false);setSidePanel('right',false);}
}
compactStrategyLayout.addEventListener('change',adaptStrategyViewport);
adaptStrategyViewport();
