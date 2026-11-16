/* Satellite control areas follow current ownership, including enclaves and holes. */
let territoryCache={world:null,key:null,regions:[]};
function territoryStateKey(){
  return STATE?Object.entries(STATE.countries).map(([id,c])=>id+':'+(c.tiles||[]).map(p=>p.join(',')).join(';')).join('|'):'static';
}
function buildTerritoryGeometry(owners){
  const groups=new Map();
  for(const [key,id] of Object.entries(owners)){
    if(!id)continue;
    if(!groups.has(id))groups.set(id,[]);
    groups.get(id).push(key.split(',').map(Number));
  }
  return Array.from(groups,([id,tiles])=>{
    const edges=[];
    for(const tile of tiles){
      const dirs=tile[1]&1?HEX_DIR_ODD:HEX_DIR_EVEN;
      // Screen neighbor order is E, NE, NW, W, SW, SE.
      dirs.forEach(([dx,dy],index)=>{
        if(owners[(tile[0]+dx)+','+(tile[1]+dy)]===id)return;
        const angle=-index*Math.PI/3,x=cx(tile),y=cy(tile);
        edges.push([x+Math.cos(angle-Math.PI/6),y+Math.sin(angle-Math.PI/6),
                    x+Math.cos(angle+Math.PI/6),y+Math.sin(angle+Math.PI/6)]);
      });
    }
    // Label the largest connected component, choosing an owned tile near its center.
    const remaining=new Set(tiles.map(p=>p.join(',')));let largest=[];
    while(remaining.size){
      const first=remaining.values().next().value,queue=[first.split(',').map(Number)];remaining.delete(first);
      for(let i=0;i<queue.length;i++){
        const p=queue[i],dirs=p[1]&1?HEX_DIR_ODD:HEX_DIR_EVEN;
        for(const [dx,dy] of dirs){const key=(p[0]+dx)+','+(p[1]+dy);if(remaining.delete(key))queue.push([p[0]+dx,p[1]+dy]);}
      }
      if(queue.length>largest.length)largest=queue;
    }
    const x=largest.reduce((sum,p)=>sum+cx(p),0)/largest.length,y=largest.reduce((sum,p)=>sum+cy(p),0)/largest.length;
    const anchor=largest.reduce((best,p)=>Math.hypot(cx(p)-x,cy(p)-y)<Math.hypot(cx(best)-x,cy(best)-y)?p:best,largest[0]);
    return {id,tiles,edges,anchor,count:tiles.length};
  });
}
function satelliteTerritories(owners){
  const key=territoryStateKey();
  if(territoryCache.world!==WORLD||territoryCache.key!==key){
    territoryCache={world:WORLD,key,regions:buildTerritoryGeometry(owners)};
  }
  return territoryCache.regions;
}
function drawSatelliteTerritories(scale,owners,viewport){
  const regions=satelliteTerritories(owners);ctx.save();
  for(const region of regions){
    ctx.fillStyle=countryColor(region.id);ctx.globalAlpha=region.id===selectedCountry ? .32 : .25;
    ctx.beginPath();
    for(const tile of region.tiles){
      const x=cx(tile),y=cy(tile);
      if(x<viewport.left-2||x>viewport.right+2||y<viewport.top-2||y>viewport.bottom+2)continue;
      for(let i=0;i<6;i++){const a=(60*i-30)*Math.PI/180,px=x+Math.cos(a),py=y+Math.sin(a);if(i===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);}ctx.closePath();
    }
    ctx.fill();ctx.globalAlpha=1;ctx.beginPath();
    for(const [x1,y1,x2,y2] of region.edges){
      if(Math.max(x1,x2)<viewport.left-2||Math.min(x1,x2)>viewport.right+2||Math.max(y1,y2)<viewport.top-2||Math.min(y1,y2)>viewport.bottom+2)continue;
      ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);
    }
    ctx.lineJoin='round';ctx.lineCap='round';ctx.strokeStyle='#09151d';ctx.lineWidth=3.6/scale;ctx.stroke();
    ctx.strokeStyle=countryColor(region.id);ctx.lineWidth=(region.id===selectedCountry?2.2:1.7)/scale;ctx.stroke();
  }
  ctx.restore();
}
function drawSatelliteControlLabels(scale,owners){
  const regions=satelliteTerritories(owners).slice().sort((a,b)=>Number(b.id===selectedCountry)-Number(a.id===selectedCountry)||b.count-a.count);
  const occupied=[],w=mapPanel.clientWidth,h=mapPanel.clientHeight;ctx.save();ctx.textAlign='center';ctx.textBaseline='middle';
  for(const region of regions){
    const name=countryMeta(region.id)?.name||region.id,text=name+' · '+region.count+' 格';
    ctx.font=`600 ${11/scale}px system-ui`;const width=ctx.measureText(text).width*scale+12;
    const sx=baseOffX+panX+cx(region.anchor)*scale,sy=baseOffY+panY+cy(region.anchor)*scale;
    const box={left:sx-width/2,right:sx+width/2,top:sy-35-scale,bottom:sy-13-scale};
    if(box.right<0||box.left>w||box.bottom<0||box.top>h||occupied.some(b=>box.left<b.right+5&&box.right>b.left-5&&box.top<b.bottom+4&&box.bottom>b.top-4))continue;
    occupied.push(box);
    const x=(box.left-baseOffX-panX)/scale,y=(box.top-baseOffY-panY)/scale;
    ctx.fillStyle='rgba(9,24,32,.88)';ctx.fillRect(x,y,width/scale,22/scale);
    ctx.fillStyle=countryColor(region.id);ctx.fillRect(x,y,3/scale,22/scale);
    ctx.fillStyle='#f0e8d1';ctx.fillText(text,cx(region.anchor),(box.top+11-baseOffY-panY)/scale);
  }
  ctx.restore();
}
