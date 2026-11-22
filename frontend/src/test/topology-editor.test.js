import {describe,expect,it} from "vitest";
import {
 copyTopologySelection,createTopologyHistory,moveTopologyNodes,
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
