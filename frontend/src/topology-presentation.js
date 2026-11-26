const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));
const copy=value=>JSON.parse(JSON.stringify(value));

export const DEFAULT_PRESENTATION_CANVAS={width:1000,height:620};
export const DEFAULT_PRESENTATION_COORDINATES={
 unit:"px",origin:"top_left",x_axis:"right",y_axis:"down",scale:1,offset_x:0,offset_y:0,
};

export function createDefaultPresentation(definition){
 const nodes=Array.isArray(definition?.nodes)?definition.nodes:[];
 const links=Array.isArray(definition?.links)?definition.links:[];
 return {
  schema_version:"1.0",layout_origin:"NETREGRESS",
  coordinate_space:{...DEFAULT_PRESENTATION_COORDINATES},
  canvas:{...DEFAULT_PRESENTATION_CANVAS},grid:{enabled:true,snap:false,size:25},
  layers:[],
  nodes:nodes.map(node=>({node_id:node.id,x:Number(node.x)||0,y:Number(node.y)||0,width:136,height:68,label:node.name||node.id,z_index:0})),
  links:links.map(link=>({link_id:link.id,route_style:"direct",z_index:0})),
  drawings:[],
 };
}

export function presentationPointToCanvas(x,y,coordinateSpace={},canvas=DEFAULT_PRESENTATION_CANVAS){
 const width=Number(canvas?.width)||1000,height=Number(canvas?.height)||620;
 const origin=coordinateSpace?.origin||"top_left",axisX=coordinateSpace?.x_axis||"right",axisY=coordinateSpace?.y_axis||"down";
 let canvasX=Number(x)||0,canvasY=Number(y)||0;
 if(origin==="center"){
  canvasX=width/2+(axisX==="left"?-canvasX:canvasX);
  canvasY=height/2+(axisY==="up"?-canvasY:canvasY);
 }else{
  if(axisX==="left")canvasX=width-canvasX;
  if(axisY==="up")canvasY=height-canvasY;
 }
 return {x:canvasX,y:canvasY};
}

export function canvasPointToPresentation(x,y,coordinateSpace={},canvas=DEFAULT_PRESENTATION_CANVAS){
 const width=Number(canvas?.width)||1000,height=Number(canvas?.height)||620;
 const origin=coordinateSpace?.origin||"top_left",axisX=coordinateSpace?.x_axis||"right",axisY=coordinateSpace?.y_axis||"down";
 let nativeX=Number(x)||0,nativeY=Number(y)||0;
 if(origin==="center"){
  nativeX=(nativeX-width/2)*(axisX==="left"?-1:1);
  nativeY=(nativeY-height/2)*(axisY==="up"?-1:1);
 }else{
  if(axisX==="left")nativeX=width-nativeX;
  if(axisY==="up")nativeY=height-nativeY;
 }
 return {x:nativeX,y:nativeY};
}

export function resolveTopologyPresentation(definition,presentation){
 const source=presentation||createDefaultPresentation(definition);
 const coordinateSpace=source.coordinate_space||DEFAULT_PRESENTATION_COORDINATES;
 const canvas=source.canvas||DEFAULT_PRESENTATION_CANVAS;
 const rawNodes=new Map((source.nodes||[]).map(item=>[item.node_id,item]));
 const rawLinks=new Map((source.links||[]).map(item=>[item.link_id,item]));
 const nodes=(definition?.nodes||[]).map(node=>{
  const saved=rawNodes.get(node.id)||{node_id:node.id,x:node.x,y:node.y,width:136,height:68,label:node.name||node.id,z_index:0};
  const layout=source.layout_origin==="NATIVE"?saved:{...saved,x:node.x,y:node.y,label:node.name||node.id};
  const point=presentationPointToCanvas(layout.x,layout.y,coordinateSpace,canvas);
  return {...node,layout,canvasX:point.x,canvasY:point.y,width:Number(layout.width)||136,height:Number(layout.height)||68,rotation:Number(layout.rotation)||0,displayLabel:layout.label||node.name||node.id};
 });
 const nodeById=Object.fromEntries(nodes.map(node=>[node.id,node]));
 const links=(definition?.links||[]).map(link=>({...link,layout:rawLinks.get(link.id)||{link_id:link.id,route_style:"direct"}}));
 const drawings=(source.drawings||[]).map(drawing=>{
  const point=presentationPointToCanvas(drawing.x,drawing.y,coordinateSpace,canvas);
  return {...drawing,canvasX:point.x,canvasY:point.y,canvasPoints:(drawing.points||[]).map(item=>presentationPointToCanvas(item.x,item.y,coordinateSpace,canvas))};
 });
 return {source,coordinateSpace,canvas,grid:source.grid||{enabled:false,snap:false,size:25},layers:source.layers||[],nodes,nodeById,links,drawings,layoutOrigin:source.layout_origin||"NETREGRESS"};
}

export function fitPresentationViewport(nodes){
 if(!Array.isArray(nodes)||!nodes.length)return {x:0,y:0,width:1000,height:620};
 const minX=Math.min(...nodes.map(node=>node.canvasX-node.width/2));
 const maxX=Math.max(...nodes.map(node=>node.canvasX+node.width/2));
 const minY=Math.min(...nodes.map(node=>node.canvasY-node.height/2));
 const maxY=Math.max(...nodes.map(node=>node.canvasY+node.height/2));
 const spanX=Math.max(1,maxX-minX),spanY=Math.max(1,maxY-minY);
 const aspect=1000/620,margin=Math.max(40,Math.max(spanX,spanY)*0.12);
 const width=Math.max(250,spanX+margin*2,(spanY+margin*2)*aspect),height=width/aspect;
 return {x:(minX+maxX-width)/2,y:(minY+maxY-height)/2,width,height};
}

export function zoomPresentationViewport(viewport,factor,anchorX=0.5,anchorY=0.5){
 const width=clamp(viewport.width*factor,80,50000),height=width*(viewport.height/viewport.width);
 const xAnchor=clamp(anchorX,0,1),yAnchor=clamp(anchorY,0,1);
 const worldX=viewport.x+viewport.width*xAnchor,worldY=viewport.y+viewport.height*yAnchor;
 return {x:worldX-width*xAnchor,y:worldY-height*yAnchor,width,height};
}

export function movePresentationNodes(presentation,nodeIds,deltaX,deltaY){
 const result=copy(presentation||{}),selected=new Set(nodeIds||[]);
 const coordinateSpace=result.coordinate_space||DEFAULT_PRESENTATION_COORDINATES,canvas=result.canvas||DEFAULT_PRESENTATION_CANVAS;
 result.nodes=(result.nodes||[]).map(item=>{
  if(!selected.has(item.node_id))return item;
  const current=presentationPointToCanvas(item.x,item.y,coordinateSpace,canvas);
  let nextCanvas={x:current.x+deltaX,y:current.y+deltaY};
  if(result.grid?.enabled&&result.grid?.snap){
   const size=Math.max(1,Number(result.grid.size)||25);
   nextCanvas={x:Math.round(nextCanvas.x/size)*size,y:Math.round(nextCanvas.y/size)*size};
  }
  const next=canvasPointToPresentation(nextCanvas.x,nextCanvas.y,coordinateSpace,canvas);
  return {...item,x:next.x,y:next.y};
 });
 return result;
}

export function updatePresentationNodePosition(presentation,nodeId,axis,canvasValue){
 const result=copy(presentation||{}),coordinateSpace=result.coordinate_space||DEFAULT_PRESENTATION_COORDINATES,canvas=result.canvas||DEFAULT_PRESENTATION_CANVAS;
 result.nodes=(result.nodes||[]).map(item=>{
  if(item.node_id!==nodeId)return item;
  const point=presentationPointToCanvas(item.x,item.y,coordinateSpace,canvas);
  const next=canvasPointToPresentation(axis==="x"?canvasValue:point.x,axis==="y"?canvasValue:point.y,coordinateSpace,canvas);
  return {...item,x:next.x,y:next.y};
 });
 return result;
}

export function presentationPortPoint(node,interfaceItem,otherNode){
 const layout=node?.layout||{},width=node?.width||136,height=node?.height||68,ports=layout.ports||[];
 const port=ports.find(item=>(interfaceItem?.name&&item.interface_name===interfaceItem.name)||(item.adapter===interfaceItem?.adapter&&item.port===interfaceItem?.port));
 let local;
 if(port&&Number.isFinite(Number(port.anchor_x))&&Number.isFinite(Number(port.anchor_y))){
  local={x:-width/2+Number(port.anchor_x)*width,y:-height/2+Number(port.anchor_y)*height};
 }else{
  const direction=(otherNode?.canvasX??node.canvasX)>=node.canvasX?1:-1,side=String(port?.side||"").toUpperCase();
  if(["W","WEST"].includes(side))local={x:-width/2,y:0};
  else if(["E","EAST"].includes(side))local={x:width/2,y:0};
  else if(["N","NORTH"].includes(side))local={x:0,y:-height/2};
  else if(["S","SOUTH"].includes(side))local={x:0,y:height/2};
  else local={x:direction*width/2,y:0};
 }
 const radians=(Number(node?.rotation)||0)*Math.PI/180;
 const cosine=Math.cos(radians),sine=Math.sin(radians);
 return {
  x:node.canvasX+local.x*cosine-local.y*sine,
  y:node.canvasY+local.x*sine+local.y*cosine,
 };
}

export function presentationLinkPath(source,target,link,coordinateSpace,canvas){
 const route=link?.layout||{},points=(route.points||[]).map(item=>presentationPointToCanvas(item.x,item.y,coordinateSpace,canvas));
 if(points.length>=2)return "M "+points.map(item=>item.x+" "+item.y).join(" L ");
 const a=presentationPortPoint(source,{name:link.source_interface_name,adapter:link.source_adapter,port:link.source_port},target);
 const b=presentationPortPoint(target,{name:link.target_interface_name,adapter:link.target_adapter,port:link.target_port},source);
 const style=String(route.route_style||"direct").toLowerCase();
 if(style==="orthogonal"){const middle=(a.x+b.x)/2;return "M "+a.x+" "+a.y+" H "+middle+" V "+b.y+" H "+b.x;}
 if(style==="curved"){const middle=(a.x+b.x)/2;return "M "+a.x+" "+a.y+" Q "+middle+" "+(Math.min(a.y,b.y)-Math.abs(b.y-a.y)*0.25)+" "+b.x+" "+b.y;}
 return "M "+a.x+" "+a.y+" L "+b.x+" "+b.y;
}

export function presentationLayerVisible(item,layers){
 if(!item?.layer_id)return true;
 const layer=(layers||[]).find(candidate=>candidate.id===item.layer_id);
 return layer?layer.visible!==false:true;
}
export function presentationLayerLocked(item,layers){
 if(!item?.layer_id)return false;
 return Boolean((layers||[]).find(candidate=>candidate.id===item.layer_id)?.locked);
}
