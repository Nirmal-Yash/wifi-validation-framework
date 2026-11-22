import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import DashboardPage from "@/pages/dashboard";
import {WorkspaceProvider} from "@/components/workspace-context";

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
  topology:{access:"AVAILABLE",profiles:2,profiles_by_status:{ACTIVE:2},revisions:3,revisions_by_status:{PUBLISHED:2,DRAFT:1},apply_records:1,apply_by_status:{APPLIED:1},source:["topology_profiles","topology_revisions","topology_apply_records"],observed_at:timestamp,source_updated_at:timestamp},
  providers:{access:"AVAILABLE",items:[{lab_id:"lab-a",provider_id:"gns3",binding_status:"CONFIGURED",connection_health:"UNKNOWN",last_health_check_at:null,source:["labs","gns3_lab_bindings"],source_updated_at:timestamp}],configured:1,health:"UNKNOWN",source:["labs","gns3_lab_bindings"],observed_at:timestamp,source_updated_at:timestamp},
  pipelines:{access:"AVAILABLE",total:1,active:1,by_status:{ACTIVE:1},executions:2,executions_by_status:{QUEUED:1,RECOVERY_REQUIRED:1},queued:1,running:0,recovery_required:1,source:["pipeline_definitions","pipeline_executions"],observed_at:timestamp,source_updated_at:timestamp},
  runs:{total:3,by_lifecycle:{COMPLETED:2,RUNNING:1},by_outcome:{VALIDATED:1,REJECTED:1,PENDING:1},active:1,source:"runs",observed_at:timestamp,source_updated_at:timestamp},
  performance:{status:"UNAVAILABLE",reason:"No current Project/Lab-scoped network performance observation is available from the operations query.",source:null,observed_at:null},
 };
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
  api.workspaceProjects.mockResolvedValue({items:[{project_id:"project-a",name:"Project Alpha"}]});
  api.workspaceLabs.mockResolvedValue({items:[{lab_id:"lab-a",name:"Lab A"}]});
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
  expect(screen.getByText(/Rejected/i)).toBeTruthy();
  expect(screen.getByText(/Connection health remains unknown/i)).toBeTruthy();
  expect(screen.getAllByText(/Unavailable/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Source updated/i).length).toBeGreaterThan(0);
  expect(api.operationsOverview).toHaveBeenCalledWith("project-a","lab-a");
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
