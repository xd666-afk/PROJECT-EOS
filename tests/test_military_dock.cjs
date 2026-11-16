// Run with: node --test tests/test_military_dock.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'..','dashboard.html'),'utf8');
function dock(paused){
  function parent(){return {appendChild(node){node.parentNode=this;}};}
  const home=parent(),host=parent();
  const nodes={'panel-tile':{parentNode:home},militaryTileHost:host,militaryModal:{hidden:true}};
  const classes=new Set(),calls=[];
  const context={STATE:{paused},selectedTile:null,selectedCountry:'A',militaryResume:false,militaryTileHome:null,
    $:id=>nodes[id],countryMeta:()=>({capital:{col:2,row:3}}),
    document:{body:{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)}}},
    setRail:()=>{},showToast:()=>{},renderRight:()=>{},renderMilitary:()=>{},resize:()=>{},loadCampaignQuotes:()=>{},
    control:async action=>{calls.push(action);}};
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('async function openMilitary(){'),html.indexOf('function renderMilitary(){')),context);
  return {context,nodes,home,host,classes,calls};
}
test('opening and closing reuses the same tile card and restores its original parent',async()=>{
  const {context,nodes,home,host,classes,calls}=dock(true);
  const tile=nodes['panel-tile'];
  await context.openMilitary();
  assert.equal(tile.parentNode,host);assert.equal(nodes.militaryModal.hidden,false);
  assert.equal(classes.has('military-open'),true);
  assert.equal(context.selectedTile.join(','),'2,3');
  await context.closeMilitary();
  assert.equal(tile.parentNode,home);assert.equal(nodes.militaryModal.hidden,true);
  assert.equal(classes.size,0);assert.deepEqual(calls,[]);
});
test('a running game pauses for orders and resumes on leaving',async()=>{
  const {context,calls}=dock(false);
  context.selectedTile=[7,8];
  await context.openMilitary();await context.closeMilitary();
  assert.deepEqual(calls,['pause','resume']);
  assert.equal(context.selectedTile.join(','),'7,8');
});
test('military dock retains all existing advanced commands',()=>{
  for(const command of ['data-camp-toggle','data-camp-target','data-siege-city','data-siege-march',
    'data-mass','data-field-strike','data-mil-peace','data-build','data-march-army'])assert.ok(html.includes(command),command);
  assert.ok(html.includes("!spec.on_city_center||tileIsCenter(tile)"));
  assert.ok(html.includes('data-building="BARRACKS"'));
  assert.ok(html.includes('data-building="WALL"'));
});

test('barracks need a selected troop before recruitment can start',()=>{
  const context={esc:x=>x,fmtNum:x=>x};
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('function campUnitRow('),html.indexOf('function tileBarracksCard(')),context);
  const report={tile:[2,3],army_id:'A1',unit:'MILITIA',price:260,wage:0.01,
    strength:0,label:'民兵',raised:0,stall:'PAUSED'};
  const options=[{unit:'MILITIA',label:'民兵',unlocked:true}];
  const stopped=context.barracksPanel(report,options,true);
  assert.match(stopped,/请先选择训练兵种/);
  assert.match(stopped,/data-on="1" disabled>开始招募/);
  assert.match(context.barracksPanel({...report,preferred:'MILITIA'},options,true),/data-on="1" >开始招募/);
  assert.match(context.barracksPanel({...report,recruiting:true,stall:'',days_left:200},options,true),/暂停招募/);
});

test('attack can be confirmed while the route quote is still pending',async()=>{
  const elements=new Map(),orders=[],requests=[];
  let resolveQuote;
  const quote=new Promise(resolve=>{resolveQuote=resolve;});
  const node=()=>({children:[],options:[],append(...items){this.children.push(...items);},
    replaceChildren(...items){this.children=items;},
    add(option){this.options.push(option);if(!this.value)this.value=option.value;},
    set selectedIndex(index){this.value=this.options[index]?.value;},
    showModal(){this.open=true;},close(){this.open=false;},
    addEventListener(){},querySelectorAll(){
      return [...(this.innerHTML||'').matchAll(/name="([A-Z_]+)" min="0" max="(\d+)"/g)]
        .map(([,name,max])=>this.inputs?.[name]||{name,max,value:'0',nextElementSibling:{}});
    }});
  const get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
  const context={$:get,document:{createElement:node},URLSearchParams,AbortController,
    Option:function(text,value){this.text=text;this.value=value;},unitName:x=>x,esc:x=>x,fmtInt:x=>x,fmtNum:x=>x,
    numberedArmy:n=>['第一支军队','第二支军队','第三支军队'][n-1],selectedArmy:null,
    tileEnemyCamps:()=>[],STATE:{player_country:'A',countries:{A:{deployment:{used:1,limit:2,slots:[
      {number:1,unlocked:true,army_id:'A1'},{number:2,unlocked:true},{number:3,unlocked:false}]},
      reserve_units:{MILITIA:120,ARCHER:4},
      armies:[{army_id:'A1',tile:[6,7],units:{MILITIA:40}}]}}},
    fetch:url=>{requests.push(url);return quote;},
    submitPlayerAction:async action=>{orders.push(JSON.parse(JSON.stringify(action)));return {ok:true};}};
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('function openTileDispatch('),html.indexOf('function routHexText(')),context);
  context.openTileDispatch('attack',{col:2,row:3,owner:'B'});
  assert.equal(get('tileDispatchDialog').open,true);
  assert.match(get('tileDispatchPreview').textContent,/正在计算/);
  const menu=get('tileDispatchRows').children[0].children[1];
  assert.deepEqual(menu.options.map(option=>[option.text,option.disabled]),[
    ['第一支军队 · 已出征',false],['第二支军队',false],['第三支军队 · 未解锁',true]]);
  const sliders=get('tileDispatchRows').children.at(-1);
  assert.deepEqual(sliders.querySelectorAll('input').map(i=>i.max),['120','4','0','0','0']);
  sliders.inputs={MILITIA:{name:'MILITIA',max:'120',value:'100',nextElementSibling:{}}};
  sliders.oninput();sliders.oninput();
  assert.equal(requests.length,1);
  assert.equal(orders.length,0);
  assert.equal(get('tileDispatchConfirm').disabled,false);
  await get('tileDispatchConfirm').onclick();
  assert.equal(orders[0].operation,'DEPLOY');
  assert.equal(orders[0].target,'B');
  assert.equal(orders[0].slot,2);
  assert.equal(orders[0].units.MILITIA,100);
  assert.equal('city_id' in orders[0],false);
  assert.equal(get('tileDispatchDialog').open,false);
  resolveQuote({ok:true,json:async()=>({ok:true,days:4,cost:3})});
  await new Promise(setImmediate);
  assert.doesNotMatch(get('tileDispatchPreview').textContent,/行军成本/);
  context.selectedArmy='A1';
  context.openTileDispatch('attack',{col:3,row:3,owner:'B'});
  assert.equal(get('tileDispatchRows').children[0].children[1].value,'1');
  assert.match(get('tileDispatchRows').children.at(-1).innerHTML,/max="40" step="1" value="40" disabled/);
  assert.match(requests.at(-1),/slot=1/);
  await get('tileDispatchConfirm').onclick();
  assert.equal(orders[1].operation,'RETASK');
  assert.equal('units' in orders[1],false);
});

test('tile shows the intent before exposing individual army rows',()=>{
  const context={STATE:{player_country:'A',countries:{A:{deployment:{slots:[{unlocked:true}]}}}},tileGarrisonAt:()=>[],countryMeta:id=>({name:id}),esc:x=>x};
  vm.createContext(context);
  const march=html.slice(html.indexOf('function tileMarchCard('),html.indexOf('function tileFieldCard('));
  const attack=html.slice(html.indexOf('function tileStrikeCard('),html.indexOf('function hostilePaceText('));
  vm.runInContext(march+attack,context);
  const tile={col:1,row:2,land:true,owner:null};
  const pricing={march:{rows:[{army_id:'A1',days:6}]},field:[],garrison:[]};
  assert.match(context.tileMarchCard(tile,pricing),/驻守/);
  assert.doesNotMatch(context.tileMarchCard(tile,pricing),/A1|6 日/);
  context.tileGarrisonAt=()=>[{army_id:'A1',country_id:'A',strength:3}];
  assert.match(context.tileMarchCard(tile,pricing),/撤回城内/);
  assert.match(context.tileMarchCard(tile,pricing),/增加援军/);
  assert.match(context.tileStrikeCard({...tile,owner:'B'},{at_war:false}),/宣战/);
  assert.match(context.tileStrikeCard({...tile,owner:'B'},{at_war:true,strikes:[{army_id:'A1'}]}),/进攻/);
});

test('the first deployment stays selected for direct map orders until cleared',async()=>{
  const calls=[],focused=[];
  const realm={armies:[]};
  const context={STATE:{player_country:'A',countries:{A:realm}},selectedArmy:null,
    focusTile:(col,row)=>focused.push([col,row]),tileStrikeKey:'',tileStrikes:null,
    showToast(){},poll:async()=>{},
    fetch:async(_url,options)=>{
      const {action}=JSON.parse(options.body);
      calls.push(action);
      if(action.operation==='DEPLOY')realm.armies.push({army_id:'A1',strength:10,tile:[3,4]});
      return {json:async()=>({ok:true,result:{effects:{army_id:'A1',purpose:'MARCH'}}})};
    }};
  vm.createContext(context);
  const mapOrder=html.slice(html.indexOf('function selectedOrderArmy('),html.indexOf('function threatSignature('));
  const submit=html.slice(html.indexOf('async function submitPlayerAction('),html.indexOf('function submitBuild('));
  vm.runInContext(mapOrder+submit,context);
  await context.submitPlayerAction({type:'MILITARY',operation:'DEPLOY',slot:1},'派兵成功');
  assert.equal(context.selectedArmy,'A1');
  context.commandMapTile(5,6);
  await vm.runInContext('mapOrderQueue',context);
  assert.deepEqual(calls[1],{type:'MILITARY',operation:'AUTO_ORDER',army_id:'A1',tile:{col:5,row:6}});
  context.selectedArmy=null;
  context.commandMapTile(8,9);
  await vm.runInContext('mapOrderQueue',context);
  assert.equal(calls.length,2);
  assert.deepEqual(focused,[[5,6],[8,9]]);
});
