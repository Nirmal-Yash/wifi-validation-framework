import React from "react";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import AppShell from "@/components/layout";

vi.mock("@/api",()=>({api:{
 workspaceOrganizations:vi.fn(),
 workspaceProjects:vi.fn(),
 workspaceLabs:vi.fn(),
}}));

describe("shared application shell",()=>{
 beforeEach(()=>{
  vi.clearAllMocks();
  globalThis.sessionStorage.clear();
  api.workspaceOrganizations.mockResolvedValue({items:[{organization_id:"org-a",name:"Organization A"}]});
  api.workspaceProjects.mockResolvedValue({items:[{project_id:"project-a",name:"Project A"}]});
  api.workspaceLabs.mockResolvedValue({items:[{lab_id:"lab-a",name:"Lab A"}]});
 });
 afterEach(()=>cleanup());

 it("exposes labelled navigation, active route and current workspace selectors",async()=>{
  render(<AppShell user={{username:"owner",role:"OWNER",permissions:["workspace.read"]}} routeName="dashboard" onLogout={vi.fn()}>
   <h2>Page content</h2>
  </AppShell>);
  expect(screen.getByRole("navigation",{name:"Primary navigation"})).toBeTruthy();
  expect(screen.getByRole("link",{name:"Overview"}).getAttribute("aria-current")).toBe("page");
  expect(screen.getByLabelText("Active organization")).toBeTruthy();
  expect(screen.getByLabelText("Active project")).toBeTruthy();
  expect(screen.getByLabelText("Active lab")).toBeTruthy();
  expect(await screen.findByRole("option",{name:"Lab A"})).toBeTruthy();
  const summary=screen.getByRole("group",{name:"Current workspace"});
  await waitFor(()=>expect(summary.textContent).toContain("Project A"));
  expect(summary.textContent).toContain("Organization A");
 });
 it("updates Project and Lab choices when Organization changes",async()=>{
  api.workspaceOrganizations.mockResolvedValue({items:[
   {organization_id:"org-a",name:"Organization A"},{organization_id:"org-b",name:"Organization B"}
  ]});
  api.workspaceProjects.mockImplementation(async({organization_id})=>({items:[
   {project_id:"project-"+organization_id,name:"Project "+organization_id}
  ]}));
  api.workspaceLabs.mockImplementation(async projectId=>({items:[{lab_id:"lab-"+projectId,name:"Lab "+projectId}]}));
  render(<AppShell user={{username:"owner",role:"OWNER",permissions:["workspace.read"]}} routeName="dashboard" onLogout={vi.fn()}>
   <h2>Page content</h2>
  </AppShell>);
  expect(await screen.findByRole("option",{name:"Lab project-org-a"})).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Active organization"),{target:{value:"org-b"}});
  expect(await screen.findByRole("option",{name:"Project org-b"})).toBeTruthy();
  expect(await screen.findByRole("option",{name:"Lab project-org-b"})).toBeTruthy();
  await waitFor(()=>expect(screen.getByLabelText("Active project").value).toBe("project-org-b"));
 });
});
