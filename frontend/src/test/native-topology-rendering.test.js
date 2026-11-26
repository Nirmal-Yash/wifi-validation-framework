import {describe,expect,it} from "vitest";
import {
 canvasPointToPresentation,createDefaultPresentation,fitPresentationViewport,movePresentationNodes,
 presentationLayerVisible,presentationLinkPath,presentationPointToCanvas,presentationPortPoint,resolveTopologyPresentation,
 updatePresentationNodePosition,
} from "@/topology-presentation";

const definition={
 nodes:[
  {id:"r1",name:"R1",node_type:"ROUTER",x:0,y:0,interfaces:[{name:"Gi0/0",adapter:0,port:0}]},
  {id:"r2",name:"R2",node_type:"ROUTER",x:200,y:100,interfaces:[{name:"Gi0/0",adapter:0,port:0}]},
 ],
 links:[{id:"l1",source_node_id:"r1",source_adapter:0,source_port:0,source_interface_name:"Gi0/0",target_node_id:"r2",target_adapter:0,target_port:0,target_interface_name:"Gi0/0"}],
};

describe("native topology presentation model",()=>{
 it("uses native positions and object geometry without mutating canonical topology",()=>{
  const presentation={layout_origin:"NATIVE",coordinate_space:{unit:"px",origin:"top_left",x_axis:"right",y_axis:"down",scale:1,offset_x:100,offset_y:50},canvas:{width:1200,height:800},nodes:[
   {node_id:"r1",x:150,y:170,width:92,height:58,label:"Core"},{node_id:"r2",x:650,y:420,width:110,height:74,label:"Edge"},
  ],links:[{link_id:"l1",route_style:"orthogonal"}]};
  const model=resolveTopologyPresentation(definition,presentation);
  expect(model.nodes[0]).toMatchObject({canvasX:150,canvasY:170,width:92,height:58,displayLabel:"Core"});
  expect(model.links[0].layout.route_style).toBe("orthogonal");
  expect(definition.nodes[0]).toMatchObject({x:0,y:0});
 });
 it("converts auto-layout canvas points back into native coordinate systems",()=>{
  const coordinateSpace={unit:"native",origin:"bottom_left",x_axis:"right",y_axis:"up"};
  const canvas={width:1200,height:800};
  const point=canvasPointToPresentation(320,240,coordinateSpace,canvas);
  expect(presentationPointToCanvas(point.x,point.y,coordinateSpace,canvas)).toEqual({x:320,y:240});
 });
 it("round-trips bottom-left and centered coordinate systems",()=>{
  for(const coordinateSpace of [{origin:"bottom_left",x_axis:"right",y_axis:"up"},{origin:"center",x_axis:"left",y_axis:"up"}]){
   const canvas={width:1200,height:800},point=presentationPointToCanvas(120,240,coordinateSpace,canvas);
   expect(canvasPointToPresentation(point.x,point.y,coordinateSpace,canvas)).toEqual({x:120,y:240});
  }
 });
 it("moves only selected presentation nodes and supports coordinate edits",()=>{
  const source=createDefaultPresentation(definition),moved=movePresentationNodes(source,["r1"],40,-20);
  expect(moved.nodes[0]).toMatchObject({x:40,y:-20});
  expect(moved.nodes[1]).toMatchObject({x:200,y:100});
  expect(updatePresentationNodePosition(moved,"r2","x",360).nodes[1].x).toBe(360);
  expect(definition.nodes[1].x).toBe(200);
 });
 it("fits negative and positive native coordinates without clamping",()=>{
  const viewport=fitPresentationViewport([{canvasX:-350,canvasY:-140,width:100,height:60},{canvasX:700,canvasY:420,width:100,height:60}]);
  expect(viewport.x).toBeLessThan(-350);expect(viewport.y).toBeLessThan(-140);expect(viewport.width).toBeGreaterThan(1050);
 });
 it("renders orthogonal paths and native route points",()=>{
  const model=resolveTopologyPresentation(definition,{coordinate_space:{origin:"top_left",x_axis:"right",y_axis:"down"},nodes:[
   {node_id:"r1",x:100,y:100,width:100,height:60,ports:[{interface_name:"Gi0/0",anchor_x:1,anchor_y:0.5}]},{node_id:"r2",x:400,y:200,width:100,height:60},
  ],links:[{link_id:"l1",route_style:"orthogonal"}]});
  expect(presentationLinkPath(model.nodes[0],model.nodes[1],model.links[0],model.coordinateSpace,model.canvas)).toContain(" H ");
  expect(presentationLinkPath(model.nodes[0],model.nodes[1],{layout:{points:[{x:10,y:10},{x:20,y:40}]}},model.coordinateSpace,model.canvas)).toBe("M 10 10 L 20 40");
 });
 it("snaps native presentation movement to the configured grid without changing topology",()=>{
  const source=createDefaultPresentation(definition);
  source.grid={enabled:true,snap:true,size:25};
  const moved=movePresentationNodes(source,["r1"],37,13);
  expect(moved.nodes[0]).toMatchObject({x:25,y:25});
  expect(definition.nodes[0]).toMatchObject({x:0,y:0});
 });
 it("rotates native port anchors with their node geometry",()=>{
  const node={canvasX:100,canvasY:100,width:100,height:50,rotation:90,layout:{ports:[{interface_name:"Gi0/0",anchor_x:1,anchor_y:0.5}]}};
  expect(presentationPortPoint(node,{name:"Gi0/0",adapter:0,port:0})).toMatchObject({x:100,y:150});
 });
 it("respects hidden and locked presentation layers",()=>{
  expect(presentationLayerVisible({layer_id:"hidden"},[{id:"hidden",visible:false,locked:true}])).toBe(false);
 });
});
