import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import DashboardPage from "@/pages/dashboard";
import {WorkspaceProvider,useWorkspace} from "@/components/workspace-context";

vi.mock("@/api",()=>({api:{
 workspaceOrganizations:vi.fn(),
 workspaceProjects:vi.fn(),
 workspaceLabs:vi.fn(),
 runs:vi.fn(),
 operationsOverview:vi.fn(),
 readiness:vi.fn(),
}}));
vi.mock("@/router",()=>({navigate:vi.fn()}));

const timestamp="2026-11-22T10:00:00+00:00";

function overviewData(){
 return {
  observed_at:timestamp,
  scope:{project:{project_id:"project-a",organization_id:"org-a",name:"Project Alpha",status:"ACTIVE",source:"projects",observed_at:timestamp,source_updated_at:timestamp},lab_id:"lab-a"},
  labs:{total:3,in_scope:1,by_status:{ACTIVE:1},items:[{lab_id:"lab-a",name:"Lab A",provider_id:"gns3",status:"ACTIVE",topology_version:2,source_updated_at:timestamp}],source:"labs",observed_at:timestamp,source_updated_at:timestamp},
  devices:{access:"AVAILABLE",total:2,active:1,archived:1,by_status:{ACTIVE:1,ARCHIVED:1},source:"devices",observed_at:timestamp,source_updated_at:timestamp},
  topology:{access:"AVAILABLE",profiles:2,profiles_by_status:{ACTIVE:2},revisions:3,revisions_by_status:{PUBLISHED:2,DRAFT:1},latest_published_revisions:[{profile_id:"top-a",profile_name:"Core",revision_id:"rev-a",revision_number:3,published_at:timestamp}],apply_records:1,apply_by_status:{APPLIED:1},source:["topology_profiles","topology_revisions","topology_apply_records"],observed_at:timestamp,source_updated_at:timestamp},
  providers:{access:"AVAILABLE",items:[{lab_id:"lab-a",provider_id:"gns3",binding_status:"CONFIGURED",connection_health:"UNKNOWN",last_health_check_at:null,source:["labs","gns3_lab_bindings"],source_updated_at:timestamp}],configured:1,health:"UNKNOWN",source:["labs","gns3_lab_bindings"],observed_at:timestamp,source_updated_at:timestamp},
  pipelines:{access:"AVAILABLE",total:1,active:1,by_status:{ACTIVE:1},executions:3,executions_by_status:{QUEUED:1,CANCELLING:1,RECOVERY_REQUIRED:1},queued:1,running:0,cancelling:1,active_executions:2,recovery_required:1,steps:3,steps_by_status:{SUCCEEDED:1,FAILED:1,RECOVERY_REQUIRED:1},active_steps:0,failed_steps:1,recovery_required_steps:1,source:["pipeline_definitions","pipeline_executions","pipeline_steps"],observed_at:timestamp,source_updated_at:timestamp},
  runs:{total:3,by_lifecycle:{COMPLETED:2,RUNNING:1},by_outcome:{VALIDATED:1,REJECTED:1,PENDING:1},active:1,source:"runs",observed_at:timestamp,source_updated_at:timestamp},
  configuration:{access:"AVAILABLE",deployments:2,by_status:{APPLIED:1,FAILED:1},applying:0,applied:1,partial:0,failed:1,latest:{deployment_id:"deploy-a",device_id:"router-a",lab_id:"lab-a",status:"FAILED",created_at:timestamp,completed_at:timestamp},source:"device_configuration_deployments",observed_at:timestamp,source_updated_at:timestamp},
  evidence:{access:"AVAILABLE",telemetry_artifacts:2,lab_health_snapshots:1,valid_wifi_telemetry_artifacts:2,wifi_metrics:[{metric:"rssi_dbm",unit:"dBm",interface:"wlan0",sample_count:2,mean_value:-52,min_value:-54,max_value:-50,latest_value:-50,captured_at:timestamp,run_id:"run-a",environment_class:"VIRTUAL_WIFI"}],by_type:{TELEMETRY:2,LAB_HEALTH_SNAPSHOT:1},source:["artifacts","runs"],observed_at:timestamp,source_updated_at:timestamp},
  performance:{access:"AVAILABLE",status:"AVAILABLE",reason:null,metrics:[{name:"throughput",unit:"Mbps",value:95.5,mean_value:95.5,min_value:95.5,max_value:95.5,sample_count:1,authoritative:true,captured_at:timestamp,run_id:"run-a",test_id:"wifi.throughput.minimum"}],source:["runs","test_results","metrics","samples"],observed_at:timestamp,source_updated_at:timestamp},
  network_health:{access:"AVAILABLE",provider_health:"UNKNOWN",device_reachability:{status:"UNAVAILABLE",reason:"No current device reachability probe is available."},configuration_sync:{status:"UNAVAILABLE",reason:"No current desired-versus-observed configuration drift source exists."},infrastructure_resources:{status:"UNAVAILABLE",reason:"No OpenTofu resource observation is currently recorded."},source:["labs","devices","device_configuration_deployments"],observed_at:timestamp,source_updated_at:timestamp},
  action_items:{access:"AVAILABLE",topology_apply_failures:1,configuration_deployment_failures:1,pipeline_recovery_required:1,regressions:{status:"UNAVAILABLE",reason:"Blocking regression totals require an explicit baseline/current Run comparison.",source:null,observed_at:timestamp},configuration_drift:{status:"UNAVAILABLE",reason:"No current desired-versus-observed comparison is persisted.",source:null,observed_at:timestamp},provider_sync_errors:{status:"UNAVAILABLE",reason:"No separate provider synchronization observation is persisted.",source:null,observed_at:timestamp},source:["topology_apply_records","device_configuration_deployments","pipeline_executions"],observed_at:timestamp},
 };
}

function DashboardScopeHarness(){
 const workspace=useWorkspace();
 return <>
  <button type="button" onClick={()=>workspace.selectLab("lab-b")}>Switch to Lab B</button>
  <button type="button" onClick={()=>workspace.selectProject("project-b")}>Switch to Project B</button>
  <DashboardPage user={{username:"ops-admin",role:"OWNER",permissions:["workspace.read","runs.execute"]}}/>
 </>;
}

function renderDashboard(queryClient){
 return render(
  <QueryClientProvider client={queryClient}>
   <WorkspaceProvider user={{username:"ops-admin"}}>
    <DashboardPage user={{username:"ops-admin",role:"OWNER",permissions:["workspace.read","runs.execute"]}}/>
   </WorkspaceProvider>
  </QueryClientProvider>
 );
}

describe("Project/Lab operations overview",()=>{
 let queryClient;
 beforeEach(()=>{
  vi.clearAllMocks();
  globalThis.sessionStorage.clear();
  globalThis.sessionStorage.setItem("netregress.workspace.ops-admin",JSON.stringify({organizationId:"org-a",projectId:"project-a",labId:"lab-a"}));
  api.workspaceOrganizations.mockResolvedValue({items:[{organization_id:"org-a",name:"Org A"}]});
  api.workspaceProjects.mockResolvedValue({items:[{project_id:"project-a",name:"Project Alpha"},{project_id:"project-b",name:"Project Beta"}]});
  api.workspaceLabs.mockImplementation(async projectId=>({items:projectId==="project-a"?[{lab_id:"lab-a",name:"Lab A"},{lab_id:"lab-b",name:"Lab B"}]:[{lab_id:"lab-b",name:"Lab B"}]}));
  api.runs.mockResolvedValue({items:[],total:0,page:1,limit:8,pages:0});
  api.operationsOverview.mockResolvedValue(overviewData());
  api.readiness.mockResolvedValue({status:"ready",summary:"Runner is ready",checks:[]});
  queryClient=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
 });
 afterEach(()=>{
  cleanup();
  queryClient?.clear();
 });

 it("renders persisted Project/Lab metrics, freshness, outcomes and honest unknown states",async()=>{
  renderDashboard(queryClient);
  expect(await screen.findByText("Project Alpha")).toBeTruthy();
  await waitFor(()=>expect(api.operationsOverview).toHaveBeenCalledWith("project-a","lab-a"));
  expect(screen.getByText("Project and Lab scope")).toBeTruthy();
  expect(screen.getByText("Device inventory")).toBeTruthy();
  expect(screen.getByText("Topology inventory")).toBeTruthy();
  expect(screen.getByText("Pipeline execution state")).toBeTruthy();
  expect(screen.getByText("Business outcomes")).toBeTruthy();
  expect(screen.getByText("Organization")).toBeTruthy();
  expect(screen.getByText("Selected Lab")).toBeTruthy();
  expect(screen.getByText("Profiles · ACTIVE")).toBeTruthy();
  expect(screen.getByText("Revisions · PUBLISHED")).toBeTruthy();
  expect(screen.getByText("Executions · CANCELLING")).toBeTruthy();
  expect(screen.getByText("Active Runs")).toBeTruthy();
  expect(screen.getByText("Configuration deployments")).toBeTruthy();
  expect(screen.getByText("Evidence inventory")).toBeTruthy();
  expect(screen.getByText("Network health")).toBeTruthy();
  expect(screen.getByText("Action items")).toBeTruthy();
  expect(screen.getByText("Latest published · Core")).toBeTruthy();
  expect(screen.getByText("Steps · RECOVERY REQUIRED")).toBeTruthy();
  expect(screen.getByText("95.5 Mbps")).toBeTruthy();
  expect(screen.getByText("rssi dbm")).toBeTruthy();
  expect(screen.getByText("Mean -52 dBm · 2 samples · Run run-a")).toBeTruthy();
  expect(screen.getByText("deploy-a")).toBeTruthy();
  expect(screen.getByText("Telemetry artifacts")).toBeTruthy();
  expect(screen.getByText("Lab health snapshots")).toBeTruthy();
  expect(screen.getByText("Device reachability")).toBeTruthy();
  expect(screen.getByText("Regressions")).toBeTruthy();
  expect(screen.getByText("REJECTED")).toBeTruthy();
  expect(screen.getByText(/Connection health remains unknown/i)).toBeTruthy();
  expect(screen.getAllByText(/Unavailable/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Source updated/i).length).toBeGreaterThan(0);
  expect(api.operationsOverview).toHaveBeenCalledWith("project-a","lab-a");
  expect(api.runs).toHaveBeenCalledWith({limit:8,project_id:"project-a",lab:"lab-a"});
 });

 it("reloads dashboard data for the selected Lab and Project",async()=>{
  api.operationsOverview.mockImplementation(async(projectId,labId)=>{
   const data=overviewData();
   data.scope.project.project_id=projectId;
   data.scope.project.name=projectId==="project-b"?"Project Beta":"Project Alpha";
   data.scope.lab_id=labId||null;
   data.labs.total=projectId==="project-b"?1:3;
   data.labs.in_scope=labId?1:data.labs.total;
   return data;
  });
  render(
   <QueryClientProvider client={queryClient}>
    <WorkspaceProvider user={{username:"ops-admin"}}>
     <DashboardScopeHarness/>
    </WorkspaceProvider>
   </QueryClientProvider>
  );
  expect(await screen.findByText("Project Alpha")).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"Switch to Lab B"}));
  await waitFor(()=>expect(api.operationsOverview).toHaveBeenLastCalledWith("project-a","lab-b"));
  fireEvent.click(screen.getByRole("button",{name:"Switch to Project B"}));
  expect(await screen.findByText("Project Beta")).toBeTruthy();
  await waitFor(()=>expect(api.operationsOverview).toHaveBeenLastCalledWith("project-b",undefined));
  await waitFor(()=>expect(api.runs).toHaveBeenLastCalledWith({limit:8,project_id:"project-b"}));
 });

 it("renders permission-restricted domains without showing missing aggregates as zero",async()=>{
  api.runs.mockRejectedValue(new Error("permission required: runs.read"));
  api.operationsOverview.mockResolvedValue({
   ...overviewData(),
   devices:{access:"RESTRICTED",total:null,active:null,archived:null,by_status:null,source:null,observed_at:null,source_updated_at:null},
   topology:{access:"RESTRICTED",profiles:null,profiles_by_status:null,revisions:null,revisions_by_status:null,latest_published_revisions:null,apply_records:null,apply_by_status:null,source:null,observed_at:null,source_updated_at:null},
   providers:{access:"RESTRICTED",items:[],configured:null,health:"UNKNOWN",source:null,observed_at:null,source_updated_at:null},
   pipelines:{access:"RESTRICTED",total:null,by_status:null,executions:null,executions_by_status:null,queued:null,running:null,cancelling:null,active_executions:null,recovery_required:null,steps:null,steps_by_status:null,active_steps:null,failed_steps:null,recovery_required_steps:null,source:null,observed_at:null,source_updated_at:null},
   runs:{access:"RESTRICTED",total:null,by_lifecycle:null,by_outcome:null,active:null,source:null,observed_at:null,source_updated_at:null},
   configuration:{access:"RESTRICTED",deployments:null,by_status:null,applying:null,applied:null,partial:null,failed:null,latest:null,source:null,observed_at:null,source_updated_at:null},
   evidence:{access:"RESTRICTED",telemetry_artifacts:null,lab_health_snapshots:null,by_type:null,source:null,observed_at:null,source_updated_at:null},
   performance:{access:"RESTRICTED",status:"RESTRICTED",reason:null,metrics:null,source:null,observed_at:null,source_updated_at:null},
   network_health:{access:"AVAILABLE",provider_health:"RESTRICTED",device_reachability:{status:"RESTRICTED",reason:null},configuration_sync:{status:"RESTRICTED",reason:null},infrastructure_resources:{status:"UNAVAILABLE",reason:"No resource observation."},observed_at:timestamp},
   action_items:{access:"AVAILABLE",topology_apply_failures:null,configuration_deployment_failures:null,pipeline_recovery_required:null,regressions:{status:"UNAVAILABLE"},configuration_drift:{status:"RESTRICTED"},provider_sync_errors:{status:"UNAVAILABLE"},observed_at:timestamp},
  });
  renderDashboard(queryClient);
  expect(await screen.findByText("Project and Lab scope")).toBeTruthy();
  expect(screen.getByText("Device inventory counts are restricted by Project permissions.")).toBeTruthy();
  expect(screen.getByText("Topology and provider metadata require topology read permission.")).toBeTruthy();
  expect(screen.getByText("Configuration deployment history requires configurations.read permission.")).toBeTruthy();
  expect(screen.getByText("Evidence inventory requires evidence.read permission.")).toBeTruthy();
  expect(screen.getByText("Performance observations require performance.read permission.")).toBeTruthy();
  expect(screen.getByText("Run lifecycle and business-outcome totals require runs.read permission.")).toBeTruthy();
 });

 it("keeps operations visible when the separate Run list request fails",async()=>{
  api.runs.mockRejectedValue(new Error("Run list unavailable"));
  renderDashboard(queryClient);
  expect(await screen.findByText("Project Alpha")).toBeTruthy();
  expect(await screen.findByText("Run list unavailable")).toBeTruthy();
  expect(screen.getByText("Project and Lab scope")).toBeTruthy();
  expect(screen.getByText("Network operations")).toBeTruthy();
  expect(api.operationsOverview).toHaveBeenCalledWith("project-a","lab-a");
 });

 it("does not issue an unscoped Run list request when no Project is selected",async()=>{
  globalThis.sessionStorage.setItem("netregress.workspace.ops-admin",JSON.stringify({organizationId:"",projectId:"",labId:""}));
  api.workspaceOrganizations.mockResolvedValue({items:[]});
  renderDashboard(queryClient);
  expect(await screen.findByText("No Project selected")).toBeTruthy();
  expect(api.runs).not.toHaveBeenCalled();
  expect(api.operationsOverview).not.toHaveBeenCalled();
 });

 it("shows an API error and retries the read-only overview",async()=>{
  let labRequestFailurePending=true;
  api.operationsOverview.mockImplementation(async(_projectId,labId)=>{
   if(labId==="lab-a"&&labRequestFailurePending){
    labRequestFailurePending=false;
    throw new Error("operations endpoint temporarily unavailable");
   }
   return overviewData();
  });
  renderDashboard(queryClient);
  expect(await screen.findByText("operations endpoint temporarily unavailable")).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:/try again/i}));
  expect(await screen.findByText("Project and Lab scope")).toBeTruthy();
  await waitFor(()=>expect(api.operationsOverview.mock.calls.filter(([,labId])=>labId==="lab-a")).toHaveLength(2));
 });
});
