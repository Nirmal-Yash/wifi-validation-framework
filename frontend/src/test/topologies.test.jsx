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
 topologyPresentationRevisions:vi.fn(),
 topologyNativeSources:vi.fn(),
 topologyNativeArtifacts:vi.fn(),
 nativeConfigurationSnapshots:vi.fn(),
 nativeTopologyOperations:vi.fn(),
 nativeTopologyReconciliations:vi.fn(),
 importPacketTracerTopology:vi.fn(),
 exportPacketTracerRevision:vi.fn(),
 validateTopology:vi.fn(),
 createTopologyRevision:vi.fn(),
 publishTopologyRevision:vi.fn(),
 createTopology:vi.fn(),
 importNativeTopology:vi.fn(),
 createTopology:vi.fn(),
 importNativeTopology:vi.fn(),
 topologyProviderBinding:vi.fn(),
 devices:vi.fn(),
 credentials:vi.fn(),
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
  api.topologyRevisions.mockImplementation(async profileId=>({
   items:[{...revision,profile_id:profileId,revision_id:profileId==="profile-a"?"revision-a":"revision-"+profileId}],
  }));
  api.topologyPresentationRevisions.mockResolvedValue({items:[]});
  api.topologyNativeSources.mockResolvedValue({items:[]});
  api.topologyNativeArtifacts.mockResolvedValue({items:[]});
  api.nativeConfigurationSnapshots.mockResolvedValue({items:[]});
  api.nativeTopologyOperations.mockResolvedValue({items:[]});
  api.nativeTopologyReconciliations.mockResolvedValue({items:[]});
  api.importPacketTracerTopology.mockResolvedValue({profile:{...profile,profile_id:"profile-pkt",name:"Imported PT"},revision:{...revision,revision_id:"revision-pkt",profile_id:"profile-pkt"},source:{source_id:"source-pkt",filename:"lab.pkt",sha256:"c".repeat(64)},report:{counts:{nodes:2,links:1},warnings:["Provider mapping is required"],unsupported_objects:[]}});
  api.validateTopology.mockResolvedValue({valid:true,node_count:2,link_count:1,content_sha256:"b".repeat(64)});
  api.createTopologyRevision.mockResolvedValue({...revision,revision_id:"revision-b",revision_number:2});
  api.publishTopologyRevision.mockResolvedValue({...revision,status:"PUBLISHED"});
  api.createTopology.mockResolvedValue({profile_id:"profile-demo",project_id:"project-1",name:"Topology Studio Demo"});
  api.importNativeTopology.mockResolvedValue({profile:{...profile,profile_id:"profile-native",name:"Imported GNS3"},revision:{...revision,revision_id:"revision-native",profile_id:"profile-native"},source:{source_id:"source-native",filename:"branch.gns3",sha256:"d".repeat(64)},report:{format_id:"GNS3_PROJECT",format_version:"2.2",counts:{nodes:2,links:1},warnings:[]}});
  api.createTopology.mockResolvedValue({profile_id:"profile-demo",project_id:"project-1",name:"Topology Studio Demo"});
  api.importNativeTopology.mockResolvedValue({profile:{...profile,profile_id:"profile-native",name:"Imported GNS3"},revision:{...revision,revision_id:"revision-native",profile_id:"profile-native"},source:{source_id:"source-native",filename:"branch.gns3",sha256:"d".repeat(64)},report:{format_id:"GNS3_PROJECT",format_version:"2.2",counts:{nodes:2,links:1},warnings:[]}});
  api.topologyProviderBinding.mockResolvedValue({binding:null});
  api.devices.mockResolvedValue({items:[]});
  api.credentials.mockResolvedValue({items:[]});
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

 async function findInitialTopologyNode(){
  // The page selects a profile and revision through dependent async queries.
  // Give slower Linux desktop runners a bounded window for the initial canvas.
  return screen.findByRole("button",{name:"Select node Router A"},{timeout:5000});
 }

 it("shows a canvas preview and imports a native file before any topology profile exists",async()=>{
  api.topologies.mockResolvedValue({items:[]});
  renderPage();
  expect(await screen.findByText("Your topology canvas is ready to start")).toBeTruthy();
  expect(screen.getByRole("img",{name:/Illustrative branch office topology/})).toBeTruthy();
  const file=new File(["valid-fixture"],"branch.gns3",{type:"application/json"});
  const input=screen.getByLabelText("GNS3 CML EVE-NG or Packet Tracer project file");
  Object.defineProperty(input,"files",{value:[file],configurable:true});
  fireEvent.change(input);
  fireEvent.change(screen.getByLabelText("Native topology profile name"),{target:{value:"Branch office native import"}});
  fireEvent.submit(input.closest("form"));
  await waitFor(()=>expect(api.importNativeTopology).toHaveBeenCalledTimes(1));
  const payload=api.importNativeTopology.mock.calls[0][0];
  expect(payload.get("project_id")).toBe("project-1");
  expect(payload.get("name")).toBe("Branch office native import");
  expect(payload.get("file").name).toBe("branch.gns3");
  expect(await screen.findByRole("button",{name:"Select node Router A"})).toBeTruthy();
 });

 it("creates an unsaved five-node demo draft from the empty first-run canvas",async()=>{
  api.topologies.mockResolvedValue({items:[]});
  api.topologyRevisions.mockResolvedValue({items:[]});
  renderPage();
  await screen.findByText("Your topology canvas is ready to start");
  fireEvent.click(screen.getByRole("button",{name:"Create sample profile and open canvas"}));
  await waitFor(()=>expect(api.createTopology).toHaveBeenCalledTimes(1));
  const payload=api.createTopology.mock.calls[0][0];
  expect(payload.project_id).toBe("project-1");
  expect(payload.scope_type).toBe("PROJECT");
  await waitFor(()=>expect(screen.getAllByRole("button",{name:/Select node/})).toHaveLength(5));
  expect(screen.getByText("5 logical nodes · 4 links")).toBeTruthy();
  expect(api.createTopologyRevision).not.toHaveBeenCalled();
 });

 it("imports a Packet Tracer project through the multipart UI and opens its canonical draft",async()=>{
  renderPage();
  await findInitialTopologyNode();
  await waitFor(()=>expect(screen.getByLabelText("Project").disabled).toBe(false));
  expect(screen.getByLabelText("Project").value).toBe("project-1");
  fireEvent.change(screen.getByLabelText("Packet Tracer profile name"),{target:{value:"Imported PT lab"}});
  const file=new File(["native-pkt"],"lab.pkt",{type:"application/octet-stream"});
  const fileInput=screen.getByLabelText("Packet Tracer .pkt file");
  Object.defineProperty(fileInput,"files",{value:[file],configurable:true});
  fireEvent.change(fileInput);
  expect(fileInput.files[0].name).toBe("lab.pkt");
  const importButton=screen.getByRole("button",{name:"Import Packet Tracer project"});
  await waitFor(()=>expect(importButton.disabled).toBe(false));
  fireEvent.submit(fileInput.closest("form"));
  await waitFor(()=>expect(api.importPacketTracerTopology).toHaveBeenCalledTimes(1));
  const form=api.importPacketTracerTopology.mock.calls[0][0];
  expect(form.get("project_id")).toBe("project-1");
  expect(form.get("name")).toBe("Imported PT lab");
  expect(form.get("scope_type")).toBe("PROJECT");
  expect(form.get("file").name).toBe("lab.pkt");
  expect(await screen.findByText(/new immutable native source and a DRAFT topology revision/)).toBeTruthy();
  expect(screen.getByText(/Provider mapping is required/)).toBeTruthy();
 });

 it("exposes accessible canvas editing controls and keyboard guidance",async()=>{
  renderPage();
  expect(await findInitialTopologyNode()).toBeTruthy();
  expect(screen.getByRole("button",{name:"Undo"})).toBeTruthy();
  expect(screen.getByRole("button",{name:"Redo"})).toBeTruthy();
  expect(screen.getByRole("button",{name:"Copy"})).toBeTruthy();
  expect(screen.getByRole("button",{name:"Paste"})).toBeTruthy();
  expect(screen.getByText(/Ctrl\/Cmd\+Z undo/)).toBeTruthy();
 });

 it("supports multi-selection, copy/paste and undo/redo keyboard commands",async()=>{
  renderPage();
  await findInitialTopologyNode();
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
  await findInitialTopologyNode();
  await screen.findByRole("button",{name:"Validate current draft"});
  fireEvent.click(screen.getByRole("button",{name:"Validate current draft"}));
  await waitFor(()=>expect(api.validateTopology).toHaveBeenCalledWith({
   project_id:"project-1",profile_id:"profile-a",definition,
  }));
  expect(await screen.findByText(/2 nodes · 1 links · SHA-256/)).toBeTruthy();
 });

 it("validates before saving a new immutable revision",async()=>{
  renderPage();
  await findInitialTopologyNode();
  fireEvent.click(await screen.findByRole("button",{name:"Validate and save new draft revision"}));
  await waitFor(()=>expect(api.validateTopology).toHaveBeenCalledTimes(1));
  await waitFor(()=>expect(api.createTopologyRevision).toHaveBeenCalledWith("profile-a",{definition}));
 });


 it("keeps a Project-scoped topology viewer read-only on the canvas",async()=>{
  renderPage({username:"viewer",role:"VIEWER",permissions:["topology.read"]});
  expect(await findInitialTopologyNode()).toBeTruthy();
  fireEvent.keyDown(window,{key:"a",ctrlKey:true});
  fireEvent.keyDown(window,{key:"v",ctrlKey:true});
  fireEvent.keyDown(window,{key:"Delete"});
  expect(screen.getAllByRole("button",{name:/Select node/})).toHaveLength(2);
  expect(screen.getByRole("button",{name:"Paste"}).disabled).toBe(true);
  expect(screen.getByRole("button",{name:"Delete selected"}).disabled).toBe(true);
  expect(screen.queryByRole("button",{name:"Validate current draft"})).toBeNull();
  expect(screen.queryByRole("button",{name:"Validate and save new draft revision"})).toBeNull();
  expect(screen.queryByRole("button",{name:"Publish selected revision"})).toBeNull();
 });

 it("shows the categorized device palette and adds provider-independent logical nodes",async()=>{
  renderPage();
  await findInitialTopologyNode();
  expect(screen.getByRole("button",{name:/Cisco IOS Router/})).toBeTruthy();
  expect(screen.getByRole("button",{name:/OpenWrt Access Point/})).toBeTruthy();
  expect(screen.getByRole("button",{name:/Open vSwitch/})).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:/Cisco IOS Router/}));
  const added=await screen.findByRole("button",{name:"Select node Cisco IOS Router 3"});
  fireEvent.keyDown(added,{key:"Enter"});
  expect(screen.getByLabelText("Logical ID").value).toMatch(/^node-/);
  expect(screen.getByLabelText("Provider template ID").value).toBe("");
  expect(screen.getByText("Not mapped")).toBeTruthy();
 });

 it("runs deterministic automatic layout from the canvas toolbar",async()=>{
  renderPage();
  await findInitialTopologyNode();
  fireEvent.click(screen.getByRole("button",{name:"Auto layout"}));
  expect(await screen.findByText("Automatic layered layout applied to the local draft.")).toBeTruthy();
 });

 it("adds typed interfaces and connects selected ports without editing JSON",async()=>{
  renderPage();
  const router=await findInitialTopologyNode();
  fireEvent.keyDown(router,{key:"Enter"});
  const interfaceName=screen.getByLabelText("Interface name");
  fireEvent.change(interfaceName,{target:{value:"GigabitEthernet0/1"}});
  fireEvent.change(screen.getByLabelText("Port"),{target:{value:"2"}});
  fireEvent.click(screen.getByRole("button",{name:"Add interface"}));
  expect(await screen.findByText("GigabitEthernet0/1")).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"Connect port"}));

  const switchNode=screen.getByRole("button",{name:"Select node Switch A"});
  fireEvent.keyDown(switchNode,{key:"Enter"});
  fireEvent.change(screen.getByLabelText("Interface name"),{target:{value:"Ethernet0/2"}});
  fireEvent.change(screen.getByLabelText("Port"),{target:{value:"3"}});
  fireEvent.click(screen.getByRole("button",{name:"Add interface"}));
  expect(await screen.findByText("Ethernet0/2")).toBeTruthy();

  fireEvent.click(screen.getByRole("button",{name:"Connect port"}));
  expect(await screen.findAllByRole("button",{name:/Select link link-/})).toHaveLength(2);
  expect(screen.getByText("Link properties")).toBeTruthy();
  expect(screen.getByLabelText("Link type").value).toBe("ETHERNET");
 });

 it("exposes the six bottom-console tabs and keeps console actions behind existing permissions",async()=>{
  renderPage();
  await findInitialTopologyNode();
  const tabs=screen.getAllByRole("tab");
  expect(tabs.map(tab=>tab.textContent)).toEqual([
   "Validation","Provider operations","Logs","Apply history","Reconciliation","Warnings",
  ]);
  fireEvent.click(screen.getByRole("tab",{name:"Logs"}));
  expect(screen.getByText(/Session activity for this editor only/)).toBeTruthy();
  fireEvent.click(screen.getByRole("tab",{name:"Warnings"}));
  expect(screen.getByText(/No local topology warnings/)).toBeTruthy();
 });


 it("offers the CML adapter on Lab-scoped provider bindings",async()=>{
  const labProfile={...profile,scope_type:"LAB",scope_id:"lab-1",lab_id:"lab-1"};
  api.topologies.mockResolvedValue({items:[labProfile]});
  api.devices.mockResolvedValue({items:[{device_id:"cml-controller",name:"CML controller",host:"192.168.1.20"}]});
  api.credentials.mockResolvedValue({items:[{credential_id:"vault-cml",credential_type:"API_TOKEN",status:"ACTIVE",label:"CML API"}]});
  renderPage();
  await findInitialTopologyNode();
  fireEvent.change(screen.getByLabelText("Profile"),{target:{value:"profile-a"}});
  await waitFor(()=>expect(api.topologyProviderBinding).toHaveBeenCalledWith("lab-1"));
  fireEvent.click(screen.getByRole("tab",{name:"Provider operations"}));
  const provider=await screen.findByLabelText("Provider");
  expect(provider.querySelector('option[value="gns3"]')).toBeTruthy();
  expect(provider.querySelector('option[value="cml"]')).toBeTruthy();
  expect(provider.querySelector('option[value="eve-ng"]')).toBeTruthy();
  fireEvent.change(provider,{target:{value:"cml"}});
  expect(provider.value).toBe("cml");
  expect(screen.getByLabelText("Provider workspace ID")).toBeTruthy();
 });

 it("supports palette drag-and-drop onto the canvas",async()=>{
  renderPage();
  await findInitialTopologyNode();
  const paletteItem=screen.getByRole("button",{name:/Linux Client/});
  const data={values:{},setData(type,value){this.values[type]=value;},getData(type){return this.values[type]||"";}};
  fireEvent.dragStart(paletteItem,{dataTransfer:data});
  const canvas=screen.getByRole("application",{name:/Interactive topology canvas/});
  fireEvent.drop(canvas,{dataTransfer:data,clientX:250,clientY:240});
  expect(await screen.findByRole("button",{name:"Select node Linux Client 3"})).toBeTruthy();
 });
});
