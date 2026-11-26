import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import {ConfigurationPage} from "@/pages/configuration";

vi.mock("@/api",()=>({api:{
 workspaceProjects:vi.fn(),
 configurationSchemas:vi.fn(),
 configurationProfiles:vi.fn(),
 configurationAssignments:vi.fn(),
 configurationRevisions:vi.fn(),
 devices:vi.fn(),
 credentials:vi.fn(),
 configurationDeploymentHistory:vi.fn(),
 registerConfigurationSchema:vi.fn(),
 createConfigurationProfile:vi.fn(),
 createConfigurationRevision:vi.fn(),
 publishConfigurationRevision:vi.fn(),
 applyConfigurationRevision:vi.fn(),
 rollbackConfigurationRevision:vi.fn(),
 importConfigurationYaml:vi.fn(),
 resolveConfiguration:vi.fn(),
}}));

vi.mock("@/components/workspace-context",()=>({
 useWorkspace:()=>({
  activeOrganizationId:"org-demo",
  activeProjectId:"project-demo",
  activeLabId:"lab-demo",
  selectProject:vi.fn(),
 }),
}));

describe("Configuration Profiles workspace",()=>{
 let queryClient;
 const user={username:"owner",role:"OWNER",permissions:[
  "workspace.read","configurations.read","configurations.manage",
  "configurations.publish","configurations.deploy","devices.read",
 ]};

 beforeEach(()=>{
  vi.clearAllMocks();
  queryClient=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
  api.workspaceProjects.mockResolvedValue({items:[
   {project_id:"project-demo",organization_id:"org-demo",name:"Demo Project"},
  ]});
  api.configurationSchemas.mockResolvedValue({items:[
   {schema_record_id:"schema-demo",schema_id:"demo.wifi.v1",version:1,name:"Demo Wi-Fi"},
  ]});
  api.configurationProfiles.mockResolvedValue({items:[]});
  api.configurationAssignments.mockResolvedValue({items:[]});
  api.devices.mockResolvedValue({items:[]});
 });

 afterEach(()=>{cleanup();queryClient?.clear();});

 function renderPage(){
  return render(<QueryClientProvider client={queryClient}>
   <ConfigurationPage user={user}/>
  </QueryClientProvider>);
 }

 it("renders Configuration Profiles and its schema/profile workflows without crashing",async()=>{
  renderPage();
  expect(await screen.findByText("Versioned, schema-validated configuration")).toBeTruthy();
  expect(await screen.findByText("Schema registry")).toBeTruthy();
  expect(await screen.findByText("Create a profile")).toBeTruthy();
  expect(screen.getByLabelText("Selected profile")).toBeTruthy();
  expect(screen.getByLabelText("Configuration values (JSON)")).toBeTruthy();
  expect(screen.getByText("Assignment and effective preview")).toBeTruthy();
 });

 it("keeps the page visible and shows a recoverable error when profiles cannot load",async()=>{
  api.configurationProfiles.mockRejectedValue(new Error("Configuration profile service unavailable"));
  renderPage();
  expect(await screen.findByText("Versioned, schema-validated configuration")).toBeTruthy();
  expect(await screen.findByText("Configuration profile service unavailable")).toBeTruthy();
  expect(screen.getByText("Schema registry")).toBeTruthy();
 });

 it("shows schema validation feedback instead of failing during render or submit",async()=>{
  renderPage();
  const schemaEditor=await screen.findByLabelText("Schema JSON");
  fireEvent.change(schemaEditor,{target:{value:"{"}});
  fireEvent.click(screen.getByRole("button",{name:"Register schema v1"}));
  expect(await screen.findByText("Schema definition must be valid JSON.")).toBeTruthy();
 });
});
