import {describe,expect,it} from "vitest";
import {
 autoLayoutTopology,copyTopologySelection,createTopologyHistory,moveTopologyNodes,
 pasteTopologySelection,removeTopologySelection,
} from "../topology-editor";

const definition=()=>({
 nodes:[
  {id:"router-a",name:"Router A",node_type:"ROUTER",template_id:"tpl-router",x:100,y:120,properties:{}},
  {id:"switch-a",name:"Switch A",node_type:"SWITCH",template_id:"tpl-switch",x:300,y:120,properties:{}},
  {id:"client-a",name:"Client A",node_type:"CLIENT",template_id:"tpl-client",x:500,y:120,properties:{}},
 ],
 links:[
  {id:"link-a",source_node_id:"router-a",source_adapter:0,source_port:0,target_node_id:"switch-a",target_adapter:0,target_port:1},
  {id:"link-b",source_node_id:"switch-a",source_adapter:0,source_port:2,target_node_id:"client-a",target_adapter:0,target_port:0},
 ],
});

describe("visual topology editing primitives",()=>{
 it("moves a selected group and clamps every coordinate to the canonical canvas",()=>{
  const next=moveTopologyNodes(definition(),["router-a","switch-a"],-500,10000);
  expect(next.nodes[0]).toMatchObject({x:0,y:10000});
  expect(next.nodes[1]).toMatchObject({x:0,y:10000});
  expect(next.nodes[2]).toMatchObject({x:500,y:120});
 });

 it("copies a selected node group with only internal links",()=>{
  const copied=copyTopologySelection(definition(),["router-a","switch-a"]);
  expect(copied.nodes.map(item=>item.id)).toEqual(["router-a","switch-a"]);
  expect(copied.links.map(item=>item.id)).toEqual(["link-a"]);
 });

 it("copies a selected link together with its endpoint nodes",()=>{
  const copied=copyTopologySelection(definition(),[],"link-b");
  expect(copied.nodes.map(item=>item.id)).toEqual(["switch-a","client-a"]);
  expect(copied.links.map(item=>item.id)).toEqual(["link-b"]);
 });

 it("pastes nodes and links with remapped IDs and offset positions",()=>{
  let nextId=0;
  const result=pasteTopologySelection(
   definition(),copyTopologySelection(definition(),["router-a","switch-a"]),
   {offset:40,idFactory:kind=>kind+"-copy-"+(++nextId)}
  );
  expect(result.nodeIds).toEqual(["node-copy-1","node-copy-2"]);
  expect(result.definition.nodes.slice(-2).map(item=>[item.x,item.y])).toEqual([[140,160],[340,160]]);
  expect(result.definition.links.at(-1)).toMatchObject({
   id:"link-copy-3",source_node_id:"node-copy-1",target_node_id:"node-copy-2",
  });
 });

 it("deletes selected nodes and their incident links without disturbing unrelated records",()=>{
  const next=removeTopologySelection(definition(),["switch-a"]);
  expect(next.nodes.map(item=>item.id)).toEqual(["router-a","client-a"]);
  expect(next.links).toEqual([]);
 });

 it("supports bounded undo and redo with a fresh history on revision switch",()=>{
  const history=createTopologyHistory(definition(),2);
  const first={...definition(),nodes:[...definition().nodes,{id:"new-a",name:"New A"}]};
  history.commit(first);
  const second={...first,nodes:first.nodes.map(item=>item.id==="new-a"?{...item,name:"New B"}:item)};
  history.commit(second);
  expect(history.canUndo).toBe(true);
  expect(history.undo().nodes.at(-1).name).toBe("New A");
  expect(history.canRedo).toBe(true);
  expect(history.redo().nodes.at(-1).name).toBe("New B");
  history.reset(definition());
  expect(history.canUndo).toBe(false);
  expect(history.canRedo).toBe(false);
 });
});


describe("automatic topology layout",()=>{
 it("lays out connected nodes deterministically without changing links or node metadata",()=>{
  const source=definition();
  source.nodes[0].vendor="Cisco";
  source.nodes[0].interfaces=[{name:"Gi0/0",adapter:0,port:0}];
  const first=autoLayoutTopology(source);
  const second=autoLayoutTopology(source);
  expect(first).toEqual(second);
  expect(first.links).toEqual(source.links);
  const router=first.nodes.find(node=>node.id==="router-a");
  expect(router.vendor).toBe("Cisco");
  expect(router.interfaces).toEqual(source.nodes[0].interfaces);
  expect(first.nodes.map(node=>[node.x,node.y])).not.toEqual(source.nodes.map(node=>[node.x,node.y]));
 });
 it("keeps large and disconnected topologies within canonical canvas bounds",()=>{
  const nodes=Array.from({length:128},(_,index)=>({
   id:"node-"+index,name:"Node "+index,node_type:"OTHER",template_id:"",
   x:0,y:0,properties:{},
  }));
  const links=nodes.slice(1).map((node,index)=>({
   id:"link-"+index,source_node_id:nodes[index].id,source_adapter:0,source_port:0,
   target_node_id:node.id,target_adapter:0,target_port:0,
  }));
  const arranged=autoLayoutTopology({nodes,links});
  const coordinates=arranged.nodes.map(node=>[node.x,node.y]);
  expect(arranged.nodes).toHaveLength(128);
  expect(new Set(coordinates.map(point=>point.join(":"))).size).toBe(128);
  for(const node of arranged.nodes){
   expect(node.x).toBeGreaterThanOrEqual(0);
   expect(node.x).toBeLessThanOrEqual(10000);
   expect(node.y).toBeGreaterThanOrEqual(0);
   expect(node.y).toBeLessThanOrEqual(10000);
  }
 });
 it("preserves the exact empty definition",()=>{
  expect(autoLayoutTopology({nodes:[],links:[]})).toEqual({nodes:[],links:[]});
 });
});
