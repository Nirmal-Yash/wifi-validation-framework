import React from "react";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import {WorkspaceProvider,useWorkspace} from "@/components/workspace-context";

vi.mock("@/api",()=>({api:{
 workspaceOrganizations:vi.fn(),workspaceProjects:vi.fn(),workspaceLabs:vi.fn()
}}));

function Harness(){
 const workspace=useWorkspace();
 return <div>
  <select aria-label="Active organization" value={workspace.activeOrganizationId} onChange={event=>workspace.selectOrganization(event.target.value)}>
   {workspace.organizations.map(item=><option key={item.organization_id} value={item.organization_id}>{item.name}</option>)}
  </select>
  <select aria-label="Active project" value={workspace.activeProjectId} onChange={event=>workspace.selectProject(event.target.value)}>
   <option value="">No project</option>
   {workspace.projects.map(item=><option key={item.project_id} value={item.project_id}>{item.name}</option>)}
  </select>
  <select aria-label="Active lab" value={workspace.activeLabId} onChange={event=>workspace.selectLab(event.target.value)}>
   <option value="">No lab</option>
   {workspace.labs.map(item=><option key={item.lab_id} value={item.lab_id}>{item.name}</option>)}
  </select>
  <output>{workspace.activeOrganizationId}|{workspace.activeProjectId}|{workspace.activeLabId}</output>
 </div>;
}
describe("global workspace context",()=>{
 beforeEach(()=>{
  vi.clearAllMocks();globalThis.sessionStorage.clear();
  api.workspaceOrganizations.mockResolvedValue({items:[{organization_id:"org-a",name:"Org A"},{organization_id:"org-b",name:"Org B"}]});
  api.workspaceProjects.mockImplementation(async({organization_id})=>({items:organization_id==="org-a"?[{project_id:"project-a",name:"Project A"}]:[{project_id:"project-b",name:"Project B"}]}));
  api.workspaceLabs.mockImplementation(async projectId=>({items:[{lab_id:"lab-"+projectId,name:"Lab "+projectId}]}));
 });
 afterEach(()=>cleanup());
 it("loads Projects and Labs inside the selected Organization",async()=>{
  render(<WorkspaceProvider user={{username:"owner"}}><Harness/></WorkspaceProvider>);
  expect(await screen.findByRole("option",{name:"Project A"})).toBeTruthy();
  expect(await screen.findByRole("option",{name:"Lab project-a"})).toBeTruthy();
  expect(api.workspaceProjects).toHaveBeenCalledWith({organization_id:"org-a"});
  expect(api.workspaceLabs).toHaveBeenCalledWith("project-a");
 });
 it("restores a valid previously selected Project and Lab for the signed-in user",async()=>{
  globalThis.sessionStorage.setItem("netregress.workspace.owner",JSON.stringify({
   organizationId:"org-b",projectId:"project-b",labId:"lab-project-b"
  }));
  render(<WorkspaceProvider user={{username:"owner"}}><Harness/></WorkspaceProvider>);
  expect(await screen.findByRole("option",{name:"Lab project-b"})).toBeTruthy();
  await waitFor(()=>expect(screen.getByText("org-b|project-b|lab-project-b")).toBeTruthy());
  expect(api.workspaceProjects).toHaveBeenCalledWith({organization_id:"org-b"});
  expect(api.workspaceLabs).toHaveBeenCalledWith("project-b");
 });
 it("clears dependent Project and Lab selection when the Organization changes",async()=>{
  render(<WorkspaceProvider user={{username:"owner"}}><Harness/></WorkspaceProvider>);
  await screen.findByRole("option",{name:"Lab project-a"});
  fireEvent.change(screen.getByLabelText("Active organization"),{target:{value:"org-b"}});
  expect(await screen.findByRole("option",{name:"Project B"})).toBeTruthy();
  expect(await screen.findByRole("option",{name:"Lab project-b"})).toBeTruthy();
  await waitFor(()=>expect(screen.getByText("org-b|project-b|")).toBeTruthy());
  expect(api.workspaceProjects).toHaveBeenLastCalledWith({organization_id:"org-b"});
 });
});
