const clone=value=>JSON.parse(JSON.stringify(value??{nodes:[],links:[]}));
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));

export function moveTopologyNodes(definition,nodeIds,deltaX,deltaY){
 const selected=new Set(nodeIds||[]);
 return {
  ...definition,
  nodes:(definition?.nodes||[]).map(node=>selected.has(node.id)?{
   ...node,
   x:clamp(Math.round((Number(node.x)||0)+(Number(deltaX)||0)),0,10000),
   y:clamp(Math.round((Number(node.y)||0)+(Number(deltaY)||0)),0,10000),
  }:node),
 };
}

export function removeTopologySelection(definition,nodeIds=[],linkId=""){
 const removed=new Set(nodeIds);
 return {
  nodes:(definition?.nodes||[]).filter(node=>!removed.has(node.id)),
  links:(definition?.links||[]).filter(link=>
   link.id!==linkId&&!removed.has(link.source_node_id)&&!removed.has(link.target_node_id)
  ),
 };
}

export function copyTopologySelection(definition,nodeIds=[],linkId=""){
 const ids=new Set(nodeIds);
 const selectedLink=(definition?.links||[]).find(link=>link.id===linkId);
 if(selectedLink){
  ids.add(selectedLink.source_node_id);
  ids.add(selectedLink.target_node_id);
 }
 const nodes=(definition?.nodes||[]).filter(node=>ids.has(node.id)).map(clone);
 const links=(definition?.links||[]).filter(link=>
  ids.has(link.source_node_id)&&ids.has(link.target_node_id)&&
  (!selectedLink||link.id===selectedLink.id||nodeIds.length>0)
 ).map(clone);
 return {nodes,links};
}

export function pasteTopologySelection(definition,clipboard,{offset=40,idFactory}={}){
 if(typeof idFactory!=="function")throw new TypeError("idFactory is required");
 const copied=clone(clipboard||{nodes:[],links:[]});
 if(!copied.nodes.length)return {definition:clone(definition),nodeIds:[]};
 if((definition?.nodes||[]).length+copied.nodes.length>128)throw new Error("The topology node limit is 128.");
 if((definition?.links||[]).length+copied.links.length>512)throw new Error("The topology link limit is 512.");
 const idMap=new Map(copied.nodes.map(node=>[node.id,idFactory("node")]));
 const nodes=copied.nodes.map(node=>({
  ...node,
  id:idMap.get(node.id),
  name:String(node.name||"Node")+" copy",
  x:clamp(Math.round((Number(node.x)||0)+offset),0,10000),
  y:clamp(Math.round((Number(node.y)||0)+offset),0,10000),
  properties:{...(node.properties||{})},
 }));
 const links=copied.links.map(link=>({
  ...link,
  id:idFactory("link"),
  source_node_id:idMap.get(link.source_node_id),
  target_node_id:idMap.get(link.target_node_id),
 }));
 return {
  definition:{nodes:[...(definition?.nodes||[]),...nodes],links:[...(definition?.links||[]),...links]},
  nodeIds:nodes.map(node=>node.id),
 };
}

export function createTopologyHistory(initial,maxEntries=60){
 let current=clone(initial),past=[],future=[];
 const equal=(left,right)=>JSON.stringify(left)===JSON.stringify(right);
 return {
  get canUndo(){return past.length>0;},
  get canRedo(){return future.length>0;},
  get current(){return clone(current);},
  commit(next,previous=current){
   const candidate=clone(next);
   if(equal(previous,candidate))return clone(current);
   past.push(clone(previous));
   if(past.length>maxEntries)past.shift();
   future=[];
   current=candidate;
   return clone(current);
  },
  undo(){
   if(!past.length)return null;
   future.push(clone(current));
   current=past.pop();
   return clone(current);
  },
  redo(){
   if(!future.length)return null;
   past.push(clone(current));
   current=future.pop();
   return clone(current);
  },
  reset(next){
   current=clone(next);past=[];future=[];
   return clone(current);
  },
  replace(next){
   current=clone(next);
   return clone(current);
  },
 };
}


export function autoLayoutTopology(definition, options = {}) {
 const nodes=(definition?.nodes||[]).map(clone).sort((a,b)=>String(a.id).localeCompare(String(b.id)));
 const links=(definition?.links||[]).map(clone);
 if(nodes.length<2)return clone(definition||{nodes:[],links:[]});
 const adjacency=new Map(nodes.map(node=>[node.id,new Set()]));
 for(const link of links){
  if(adjacency.has(link.source_node_id)&&adjacency.has(link.target_node_id)){
   adjacency.get(link.source_node_id).add(link.target_node_id);
   adjacency.get(link.target_node_id).add(link.source_node_id);
  }
 }
 const visited=new Set(),components=[];
 for(const node of nodes){
  if(visited.has(node.id))continue;
  const queue=[node.id],component=[];
  visited.add(node.id);
  while(queue.length){
   const current=queue.shift();
   component.push(current);
   for(const neighbor of [...(adjacency.get(current)||[])].sort()){
    if(!visited.has(neighbor)){visited.add(neighbor);queue.push(neighbor);}
   }
  }
  const root=[...component].sort((a,b)=>
   (adjacency.get(b)?.size||0)-(adjacency.get(a)?.size||0)||a.localeCompare(b)
  )[0];
  const levels=new Map([[root,0]]),walk=[root];
  for(let index=0;index<walk.length;index++){
   const current=walk[index];
   for(const neighbor of [...(adjacency.get(current)||[])].sort()){
    if(!levels.has(neighbor)){levels.set(neighbor,levels.get(current)+1);walk.push(neighbor);}
   }
  }
  const buckets=new Map();
  for(const id of component){
   const level=levels.get(id)||0;
   if(!buckets.has(level))buckets.set(level,[]);
   buckets.get(level).push(id);
  }
  for(const bucket of buckets.values())bucket.sort();
  components.push({levels:buckets,depth:Math.max(...buckets.keys())});
 }
 const total=nodes.length;
 const maxDepth=Math.max(...components.map(component=>component.depth));
 const vertical=maxDepth>18;
 const columns=Math.max(1,Math.min(Math.ceil(Math.sqrt(total)),Math.floor(9600/176)));
 const columnGap=Math.min(options.columnGap||250,Math.max(150,Math.floor(9600/Math.max(1,columns-1))));
 const rowGap=Math.max(74,Math.min(options.rowGap||170,Math.floor(9600/total)));
 const positions=new Map();
 let rowOffset=0;
 for(const component of components){
  const levels=[...component.levels.keys()].sort((a,b)=>a-b);
  for(const level of levels){
   const ids=component.levels.get(level);
   ids.forEach((id,index)=>{
    const column=index%columns;
    const subRow=Math.floor(index/columns);
    positions.set(id,{
     x:Math.min(10000,160+(vertical?0:level*250)+column*columnGap),
     y:Math.min(10000,120+rowOffset+subRow*rowGap),
    });
   });
   rowOffset+=Math.ceil(ids.length/columns)*rowGap;
  }
 }
 return {
  ...clone(definition),
  nodes:nodes.map(node=>({...node,...(positions.get(node.id)||{x:node.x,y:node.y})})),
  links,
 };
}
