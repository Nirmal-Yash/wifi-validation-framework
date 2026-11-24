import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import NetworkIntentPage from "@/pages/network-intent";

vi.mock("@/api",()=>({api:{
 topologies:vi.fn(),
 topologyRevisions:vi.fn(),
 networkIntentProfiles:vi.fn(),
 createNetworkIntentProfile:vi.fn(),
 networkIntentProfile:vi.fn(),
 networkIntentRevisions:vi.fn(),
 createNetworkIntentRevision:vi.fn(),
 publishNetworkIntentRevision:vi.fn(),
 rollbackNetworkIntentRevision:vi.fn(),
 validateNetworkIntent:vi.fn(),
 devices:vi.fn(),
 deviceCapabilityReports:vi.fn(),
 networkConfigAdapters:vi.fn(),
 compileNetworkIntentRevision:vi.fn(),
}}));

vi.mock("@/components/workspace-context",()=>({
 useWorkspace:()=>({activeOrganizationId:"org-1",activeProjectId:"project-1",activeLabId:"lab-1"}),
}));

const topologyProfile={
 profile_id:"topology-1",project_id:"project-1",name:"Primary fabric",
 scope_type:"LAB",scope_id:"lab-1",lab_id:"lab-1",status:"ACTIVE",
};
const topologyRevision={
 revision_id:"topology-revision-1",profile_id:"topology-1",revision_number:1,
 status:"PUBLISHED",content_sha256:"a".repeat(64),
 definition:{nodes:[{id:"router-a",name:"Router A",node_type:"ROUTER",interfaces:[]}],
             links:[]},
};
const device={
 device_id:"device-1",project_id:"project-1",lab_id:"lab-1",device_key:"router-east",
 name:"Router East",vendor:"Cisco",model:"IOS-XE",status:"ACTIVE",
};
const intentProfile={
 profile_id:"intent-profile-1",project_id:"project-1",topology_profile_id:"topology-1",
 name:"Primary network intent",scope_type:"LAB",scope_id:"lab-1",status:"ACTIVE",
};
let createdProfile=false;
let savedRevision=null;
let publishedRevision=null;
let rolledBackRevision=null;
let compilationResult=null;
const validationResult={
 valid:false,capability_status:"UNKNOWN",ready_for_compilation:false,
 topology_revision_id:"topology-revision-1",intent_sha256:"b".repeat(64),
 required_capabilities:{"router-a":["addressing.ipv4","interfaces.admin_state"]},
 diagnostics:[{
  code:"CAPABILITY_REPORT_MISSING",severity:"ERROR",logical_node_id:"router-a",
  device_id:"device-1",message:"No adapter-observed capability report exists for Device device-1",
 }],
};

describe("Network Intent v1.0 page",()=>{
 let queryClient;
 beforeEach(()=>{
  vi.clearAllMocks();
  createdProfile=false;
  savedRevision=null;
  publishedRevision=null;
  rolledBackRevision=null;
  compilationResult=null;
  queryClient=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
  api.topologies.mockResolvedValue({items:[topologyProfile]});
  api.topologyRevisions.mockResolvedValue({items:[topologyRevision]});
  api.networkIntentProfiles.mockImplementation(async()=>({items:createdProfile?[intentProfile]:[]}));
  api.createNetworkIntentProfile.mockImplementation(async payload=>{
   expect(payload.project_id).toBe("project-1");
   expect(payload.topology_profile_id).toBe("topology-1");
   createdProfile=true;
   return intentProfile;
  });
  api.networkIntentRevisions.mockImplementation(async()=>({items:[publishedRevision||savedRevision,rolledBackRevision].filter(Boolean)}));
  api.createNetworkIntentRevision.mockImplementation(async(_profileId,payload)=>{
   savedRevision={
    revision_id:"intent-revision-1",profile_id:"intent-profile-1",revision_number:1,
    topology_revision_id:"topology-revision-1",status:"DRAFT",
    intent_sha256:"c".repeat(64),definition:payload.definition,provenance:payload.provenance,
   };
   return savedRevision;
  });
  api.publishNetworkIntentRevision.mockImplementation(async(_profileId,payload)=>{
   expect(payload.revision_id).toBe("intent-revision-1");
   publishedRevision={...savedRevision,status:"PUBLISHED",published_at:"2026-11-23T12:00:00+00:00"};
   return publishedRevision;
  });
  api.rollbackNetworkIntentRevision.mockImplementation(async(_profileId,payload)=>{
   expect(payload.source_revision_id).toBe("intent-revision-1");
   rolledBackRevision={...savedRevision,revision_id:"intent-revision-2",revision_number:2,status:"DRAFT",
           parent_revision_id:"intent-revision-1",provenance:{source:"rollback"}};
   return rolledBackRevision;
  });
  api.validateNetworkIntent.mockResolvedValue(validationResult);
  api.devices.mockResolvedValue({items:[device]});
  api.deviceCapabilityReports.mockResolvedValue({items:[{
   report_id:"capability-1",project_id:"project-1",device_id:"device-1",provider_id:"gns3",
   platform:"Cisco IOS XE",software_version:"17.12",adapter_name:"gns3-capability-probe",
   adapter_version:"1.0",observed_at:"2026-11-23T10:00:00+00:00",
   capability_sha256:"d".repeat(64),
   capabilities:{"addressing.ipv4":{status:"SUPPORTED"},"routing.ospf":{status:"UNSUPPORTED"}},
  }]});
  api.networkConfigAdapters.mockResolvedValue({items:[
   {adapter_id:"linux_frr",name:"Linux + FRRouting",version:"1.0.0",platform_family:"Linux/FRR",supported_versions:"FRR 7–10",output_format:"systemd-networkd + FRR + nftables"},
   {adapter_id:"cisco_iosxe",name:"Cisco IOS / IOS-XE",version:"1.0.0",platform_family:"Cisco IOS/IOS-XE",supported_versions:"IOS 15.x; IOS-XE 16.x–17.x",output_format:"IOS/IOS-XE CLI"},
   {adapter_id:"arista_eos",name:"Arista EOS",version:"1.0.0",platform_family:"Arista EOS",supported_versions:"EOS 4.x",output_format:"EOS CLI"},
   {adapter_id:"juniper_junos",name:"Juniper Junos",version:"1.0.0",platform_family:"Juniper Junos",supported_versions:"Junos 18.x–24.x",output_format:"Junos hierarchical set commands"},
   {adapter_id:"paloalto_panos",name:"Palo Alto PAN-OS",version:"1.0.0",platform_family:"Palo Alto PAN-OS",supported_versions:"PAN-OS 10.x–12.x",output_format:"PAN-OS set CLI"},
  ]});
  api.compileNetworkIntentRevision.mockImplementation(async()=>compilationResult||{
   status:"COMPILED",compilation_id:"ncc-preview-001",compile_only:true,
   application_performed:false,ready_for_application:false,
   adapters:[{adapter_id:"cisco_iosxe",name:"Cisco IOS / IOS-XE",version:"1.0.0",output_format:"IOS/IOS-XE CLI"}],
   change_summary:{new:1,changed:0,unchanged:0},diagnostics:[],
   artifacts:[{path:"targets/router-a-device-1/running-config.txt",change_type:"NEW",sha256:"f".repeat(64),content:"hostname Router East\\n",diff:"+hostname Router East\\n"}],
   orphaned_baseline_files:[],
  });
 });
 afterEach(()=>{cleanup();queryClient?.clear();});

 function renderPage(user={username:"owner",role:"OWNER",permissions:[
  "network_intent.read","network_intent.manage","network_intent.publish","devices.read","topology.read",
 ]}){
  return render(<QueryClientProvider client={queryClient}>
   <NetworkIntentPage user={user}/>
  </QueryClientProvider>);
 }

 async function createProfile(){
  renderPage();
  await screen.findByRole("option",{name:/Primary fabric/});
  fireEvent.change(screen.getByLabelText("Bound topology profile"),{target:{value:"topology-1"}});
  fireEvent.change(screen.getByLabelText("Network intent profile name"),{target:{value:"Primary network intent"}});
  fireEvent.click(screen.getByRole("button",{name:"Create intent profile"}));
  await waitFor(()=>expect(api.createNetworkIntentProfile).toHaveBeenCalledTimes(1));
  await screen.findByRole("option",{name:/Primary network intent/});
  await waitFor(()=>expect(screen.getByLabelText("Network intent topology revision").value).toBe("topology-revision-1"));
 }

 it("creates a topology-bound profile and adds a logical-node to managed-Device binding",async()=>{
  await createProfile();
  await screen.findByRole("option",{name:/Router A/});
  await screen.findByRole("option",{name:/Router East/});
  fireEvent.change(screen.getByLabelText("Intent logical node"),{target:{value:"router-a"}});
  fireEvent.change(screen.getByLabelText("Intent target Device"),{target:{value:"device-1"}});
  fireEvent.click(screen.getByRole("button",{name:"Add target binding to JSON"}));
  const editor=screen.getByLabelText("Canonical network intent JSON");
  await waitFor(()=>expect(JSON.parse(editor.value).targets).toEqual([
   {logical_node_id:"router-a",device_id:"device-1"},
  ]));
  expect(await screen.findByText(/Target binding added to the editable intent document/)).toBeTruthy();
 });

 it("validates, saves, publishes and rolls back immutable intent revisions",async()=>{
  await createProfile();
  const editor=screen.getByLabelText("Canonical network intent JSON");
  const draft={
   schema_version:"1.0",
   targets:[{logical_node_id:"router-a",device_id:"device-1"}],
   segments:[],interfaces:[{logical_node_id:"router-a",name:"eth0",admin_state:"UP",mode:"ROUTED",addresses:["192.0.2.1/24"]}],
   static_routes:[],ospf:[],bgp:[],aggregations:[],firewall_zones:[],firewall_rules:[],
   service_references:[],linux_bridges:[],linux_vlan_interfaces:[],
  };
  fireEvent.change(editor,{target:{value:JSON.stringify(draft,null,2)}});
  fireEvent.click(screen.getByRole("button",{name:"Validate intent"}));
  await waitFor(()=>expect(api.validateNetworkIntent).toHaveBeenCalledTimes(1));
  expect(api.validateNetworkIntent.mock.calls[0][0].topology_revision_id).toBe("topology-revision-1");
  expect(await screen.findByText(/CAPABILITY_REPORT_MISSING/)).toBeTruthy();

  fireEvent.click(screen.getByRole("button",{name:"Save DRAFT revision"}));
  await waitFor(()=>expect(api.createNetworkIntentRevision).toHaveBeenCalledTimes(1));
  expect(api.createNetworkIntentRevision.mock.calls[0][1].definition.targets).toEqual(draft.targets);
  await waitFor(()=>expect(screen.getByLabelText("Network intent revision").value).toBe("intent-revision-1"));
  fireEvent.click(screen.getByRole("button",{name:"Publish revision"}));
  await waitFor(()=>expect(api.publishNetworkIntentRevision).toHaveBeenCalledTimes(1));
  expect(await screen.findByText(/Network Intent revision published/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"Create rollback draft"}));
  await waitFor(()=>expect(api.rollbackNetworkIntentRevision).toHaveBeenCalledTimes(1));
  expect(await screen.findByText(/Rollback created a new DRAFT revision/)).toBeTruthy();
  await waitFor(()=>expect(screen.getByLabelText("Network intent revision").value).toBe("intent-revision-2"));
 });


 it("lists registered vendors and compiles a published revision as a non-applying preview",async()=>{
  await createProfile();
  const editor=screen.getByLabelText("Canonical network intent JSON");
  const draft={
   schema_version:"1.0",
   targets:[{logical_node_id:"router-a",device_id:"device-1"}],
   segments:[],interfaces:[{logical_node_id:"router-a",name:"eth0",admin_state:"UP",mode:"ROUTED",addresses:["192.0.2.1/24"]}],
   static_routes:[],ospf:[],bgp:[],aggregations:[],firewall_zones:[],firewall_rules:[],
   service_references:[],linux_bridges:[],linux_vlan_interfaces:[],
  };
  fireEvent.change(editor,{target:{value:JSON.stringify(draft,null,2)}});
  fireEvent.click(screen.getByRole("button",{name:"Save DRAFT revision"}));
  await waitFor(()=>expect(api.createNetworkIntentRevision).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button",{name:"Publish revision"}));
  await waitFor(()=>expect(api.publishNetworkIntentRevision).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("Linux + FRRouting")).toBeTruthy();
  expect(screen.getAllByText("Arista EOS").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button",{name:"Compile vendor preview"}));
  await waitFor(()=>expect(api.compileNetworkIntentRevision).toHaveBeenCalledWith("intent-profile-1","intent-revision-1"));
  expect(await screen.findByText(/Device application: not performed/)).toBeTruthy();
  expect(screen.getByText(/targets\/router-a-device-1\/running-config.txt/)).toBeTruthy();
 });

 it("lists the selected Device's adapter-observed capability provenance",async()=>{
  await createProfile();
  fireEvent.change(screen.getByLabelText("Intent target Device"),{target:{value:"device-1"}});
  expect(await screen.findByText("Cisco IOS XE")).toBeTruthy();
  expect(screen.getByText(/gns3-capability-probe/)).toBeTruthy();
  expect(screen.getByText(/dddddddddddd/)).toBeTruthy();
 });

 it("keeps the editor and mutations unavailable to a read-only user",async()=>{
  renderPage({username:"viewer",role:"VIEWER",permissions:["network_intent.read","devices.read","topology.read"]});
  expect(await screen.findByRole("option",{name:/Primary fabric/})).toBeTruthy();
  expect(screen.queryByRole("button",{name:"Create intent profile"})).toBeNull();
  expect(screen.getByLabelText("Canonical network intent JSON").disabled).toBe(true);
  expect(screen.queryByRole("button",{name:"Save DRAFT revision"})).toBeNull();
 });
});
