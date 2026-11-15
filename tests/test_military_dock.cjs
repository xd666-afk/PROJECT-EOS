// Run with: node --test tests/test_military_dock.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'..','dashboard.html'),'utf8');
const quoteSource=html.slice(html.indexOf('function militaryRecruitQuote('),html.indexOf('function renderMilitaryCommand('));
function setup(){
  const c={treasury:40,food:100};
  const option={unlocked:true,room:12,cost_treasury:12.5,cost_food:3,reason:'财政不足'};
  const context={STATE:{military_specs:{recruit_batch_max:4,barracks:{garrison_capacity:4}}}};
  vm.createContext(context);vm.runInContext(quoteSource,context);
  return {c,option,quote:context.militaryRecruitQuote};
}
test('a player who cannot afford four units can still recruit one',()=>{
  const {c,option,quote}=setup();
  assert.equal(quote(c,null,option,1).enabled,true);
  assert.equal(quote(c,null,option,4).enabled,false);
  assert.equal(quote(c,null,option,4).cost,50);
  assert.equal(quote(c,null,option,4).food,12);
});
test('technology, national roster, camp capacity and food gates remain visible',()=>{
  const {c,option,quote}=setup();
  assert.equal(quote(c,null,{...option,unlocked:false,reason:'需要科技'},1).reason,'需要科技');
  assert.equal(quote(c,null,{...option,room:0},1).enabled,false);
  assert.equal(quote(c,{tile_room:0},option,1).reason,'驻格容量不足');
  assert.equal(quote({...c,food:2},null,option,1).reason,'粮食不足');
  assert.equal(quote(c,{barracks:false,strength:4},option,1).enabled,true);
});
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


test('attack can be confirmed while the route quote is still pending',async()=>{
  const elements=new Map(),orders=[],requests=[];
  let resolveQuote;
  const quote=new Promise(resolve=>{resolveQuote=resolve;});
  const node=()=>({children:[],append(...items){this.children.push(...items);},
    add(option){if(!this.value)this.value=option.value;},
    showModal(){this.open=true;},close(){this.open=false;},
    addEventListener(){},querySelectorAll(){
      return [...(this.innerHTML||'').matchAll(/name="([A-Z_]+)" min="0" max="(\d+)"/g)]
        .map(([,name,max])=>this.inputs?.[name]||{name,max,value:'0',nextElementSibling:{}});
    }});
  const get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
  const context={$:get,document:{createElement:node},URLSearchParams,AbortController,
    Option:function(text,value){this.value=value;},unitName:x=>x,esc:x=>x,fmtInt:x=>x,fmtNum:x=>x,
    tileEnemyCamps:()=>[],STATE:{player_country:'A',countries:{A:{deployment:{used:0,limit:1},
      cities:[{city_id:'C',name:'City',center:[0,0],reserve_units:{MILITIA:120,ARCHER:4}}]}}},
    fetch:url=>{requests.push(url);return quote;},
    submitPlayerAction:async action=>{orders.push(JSON.parse(JSON.stringify(action)));return true;}};
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('function openTileDispatch('),html.indexOf('function routHexText(')),context);
  context.openTileDispatch('attack',{col:2,row:3,owner:'B'});
  assert.equal(get('tileDispatchDialog').open,true);
  assert.match(get('tileDispatchPreview').textContent,/正在计算/);
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
  assert.equal(orders[0].units.MILITIA,100);
  assert.equal(get('tileDispatchDialog').open,false);
  resolveQuote({ok:true,json:async()=>({ok:true,days:4,cost:3})});
  await new Promise(setImmediate);
  assert.doesNotMatch(get('tileDispatchPreview').textContent,/行军成本/);
});

test('tile shows the intent before exposing individual army rows',()=>{
  const context={STATE:{player_country:'A'},tileGarrisonAt:()=>[],countryMeta:id=>({name:id}),esc:x=>x};
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
  assert.match(context.tileStrikeCard({...tile,owner:'B'},{at_war:false}),/宣战/);
  assert.match(context.tileStrikeCard({...tile,owner:'B'},{at_war:true,strikes:[{army_id:'A1'}]}),/进攻/);
});
