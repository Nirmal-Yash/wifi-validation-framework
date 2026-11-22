import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import TopologyStudioPage from "@/pages/topologies";

vi.mock("@/api",()=>({api:{
 workspaceProjects:vi.fn(),
 topologies:vi.fn(),
 topologyRevisions:vi.fn(),
 validateTopology:vi.fn(),
 createTopologyRevision:vi.fn(),
 publishTopologyRevision:vi.fn(),
}}));
vi.mock("@/components/workspace-context",()=>({
 useWorkspace:()=>({activeOrganizationId:"org-1",activeProjectId:"project-1",selectProject:()=>{}}),
}));

const definition={
 nodes:[
  {id:"router-a",name:"Router A",node_type:"ROUTER",template_id:"tpl-router",x:120,y:180,properties:{}},
  {id:"switch-a",name:"Switch A",node_type:"SWITCH",template_id:"tpl-switch",x:420,y:180,properties:{}},
 ],
 links:[{id:"link-a",source_node_id:"router-a",source_adapter:0,source_port:0,target_node_id:"switch-a",target_adapter:0,target_port:1}],
};
const profile={profile_id:"profile-a",project_id:"project-1",name:"Lab fabric",scope_type:"PROJECT",scope_id:"project-1",status:"ACTIVE"};
const revision={revision_id:"revision-a",profile_id:"profile-a",revision_number:1,status:"DRAFT",content_sha256:"a".repeat(64),definition};

describe("visual topology studio editing workflow",()=>{
 let client;
 beforeEach(()=>{
  vi.clearAllMocks();
  api.workspaceProjects.mockResolvedValue({items:[{project_id:"project-1",name:"Project One",slug:"project-one"}]});
  api.topologies.mockResolvedValue({items:[profile]});
  api.topologyRevisions.mockResolvedValue({items:[revision]});
  api.validateTopology.mockResolvedValue({valid:true,node_count:2,link_count:1,content_sha256:"b".repeat(64)});
  api.createTopologyRevision.mockResolvedValue({...revision,revision_id:"revision-b",revision_number:2});
  api.publishTopologyRevision.mockResolvedValue({...revision,status:"PUBLISHED"});
  client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
 });
 afterEach(()=>{cleanup();client?.clear();});

 function renderPage(user={username:"owner",role:"OWNER",permissions:[
  "topology.read","topology.manage","topology.publish","topology.apply",
  "topology.provider.manage","topology.provider.operate",
 ]}){
  return render(<QueryClientProvider client={client}>
   <TopologyStudioPage user={user}/>
  </QueryClientProvider>);
 }

 it("exposes accessible canvas editing controls and keyboard guidance",async()=>{
  renderPage();
  expect(await screen.findByRole("button",{name:"Select node Router A"})).toBeTruthy();
  expect(screen.getByRole("button",{name:"Undo"})).toBeTruthy();
  expect(screen.getByRole("button",{name:"Redo"})).toBeTruthy();
  expect(screen.getByRole("button",{name:"Copy"})).toBeTruthy();
  expect(screen.getByRole("button",{name:"Paste"})).toBeTruthy();
  expect(screen.getByText(/Ctrl\/Cmd\+Z undo/)).toBeTruthy();
 });

 it("supports multi-selection, copy/paste and undo/redo keyboard commands",async()=>{
  renderPage();
  await screen.findByRole("button",{name:"Select node Router A"});
  fireEvent.keyDown(window,{key:"a",ctrlKey:true});
  expect(screen.getByRole("button",{name:"Select node Router A"}).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("button",{name:"Select node Switch A"}).getAttribute("aria-pressed")).toBe("true");

  fireEvent.keyDown(window,{key:"c",ctrlKey:true});
  fireEvent.keyDown(window,{key:"v",ctrlKey:true});
  await waitFor(()=>expect(screen.getAllByRole("button",{name:/Select node/})).toHaveLength(4));
  expect(screen.getByRole("button",{name:"Select node Router A copy"})).toBeTruthy();
  fireEvent.keyDown(window,{key:"z",ctrlKey:true});
  await waitFor(()=>expect(screen.getAllByRole("button",{name:/Select node/})).toHaveLength(2));
  fireEvent.keyDown(window,{key:"z",ctrlKey:true,shiftKey:true});
  await waitFor(()=>expect(screen.getAllByRole("button",{name:/Select node/})).toHaveLength(4));
 });

 it("selects and edits a visual link without editing topology JSON",async()=>{
  renderPage();
  const link=await screen.findByRole("button",{name:/Select link link-a/});
  fireEvent.click(link);
  expect(screen.getByText("Selected link · link-a")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Edit target port"),{target:{value:"7"}});
  fireEvent.click(screen.getByRole("button",{name:"Save link endpoint changes"}));
  expect(screen.getByLabelText("Edit target port").value).toBe("7");
 });

 it("runs canonical backend validation from the visible editor action",async()=>{
  renderPage();
  await screen.findByRole("button",{name:"Validate current draft"});
  fireEvent.click(screen.getByRole("button",{name:"Validate current draft"}));
  await waitFor(()=>expect(api.validateTopology).toHaveBeenCalledWith({
   project_id:"project-1",profile_id:"profile-a",definition,
  }));
  expect(await screen.findByText(/2 nodes · 1 links · SHA-256/)).toBeTruthy();
 });

 it("validates before saving a new immutable revision",async()=>{
  renderPage();
  fireEvent.click(await screen.findByRole("button",{name:"Validate and save new draft revision"}));
  await waitFor(()=>expect(api.validateTopology).toHaveBeenCalledTimes(1));
  await waitFor(()=>expect(api.createTopologyRevision).toHaveBeenCalledWith("profile-a",{definition}));
 });
});


 it("keeps a Project-scoped topology viewer read-only on the canvas",async()=>{
  renderPage({username:"viewer",role:"VIEWER",permissions:["topology.read"]});
  expect(await screen.findByRole("button",{name:"Select node Router A"})).toBeTruthy();
  fireEvent.keyDown(window,{key:"a",ctrlKey:true});
  fireEvent.keyDown(window,{key:"v",ctrlKey:true});
  fireEvent.keyDown(window,{key:"Delete"});
  expect(screen.getAllByRole("button",{name:/Select node/})).toHaveLength(2);
  expect(screen.getByRole("button",{name:"Paste"}).disabled).toBe(true);
  expect(screen.getByRole("button",{name:"Delete selected"}).disabled).toBe(true);
  expect(screen.queryByRole("button",{name:"Validate current draft"})).toBeNull();
 });
