import React from "react";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api} from "@/api";
import AppShell from "@/components/layout";

vi.mock("@/api",()=>({api:{
 workspaceOrganizations:vi.fn(),
 workspaceProjects:vi.fn(),
 workspaceLabs:vi.fn(),
 topologyProviderBinding:vi.fn(),
}}));

describe("shared application shell",()=>{
 beforeEach(()=>{
  vi.clearAllMocks();
  globalThis.sessionStorage.clear();
  api.workspaceOrganizations.mockResolvedValue({items:[{organization_id:"org-a",name:"Organization A"}]});
  api.workspaceProjects.mockResolvedValue({items:[{project_id:"project-a",name:"Project A"}]});
  api.workspaceLabs.mockResolvedValue({items:[{lab_id:"lab-a",name:"Lab A",provider_id:"gns3"}]});
  api.topologyProviderBinding.mockResolvedValue({binding:{binding_id:"binding-a",lab_id:"lab-a",status:"ACTIVE"}});
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
  expect(await screen.findByText("GNS3 · bound · health unknown")).toBeTruthy();
  expect(screen.getByRole("button",{name:"Search pages and workspace"})).toBeTruthy();
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

 it("searches only visible modules and active workspace entries",async()=>{
  render(<AppShell user={{username:"viewer",role:"VIEWER",permissions:["workspace.read","topology.read"]}} routeName="dashboard" onLogout={vi.fn()}>
   <h2>Page content</h2>
  </AppShell>);
  fireEvent.click(screen.getByRole("button",{name:"Search pages and workspace"}));
  const input=screen.getByRole("searchbox",{name:"Search NetRegress"});
  fireEvent.change(input,{target:{value:"topology"}});
  expect(await screen.findByRole("option",{name:/Topology studio/})).toBeTruthy();
  fireEvent.keyDown(input,{key:"ArrowDown"});
  expect(screen.getByRole("option",{name:/Topology studio/}).getAttribute("aria-selected")).toBe("true");
  expect(screen.queryByRole("option",{name:/Administration/})).toBeNull();
  fireEvent.keyDown(input,{key:"Enter"});
  await waitFor(()=>expect(window.location.pathname).toBe("/topologies"));
 });

 it("opens global search with Ctrl or Cmd+K and closes with Escape",async()=>{
  render(<AppShell user={{username:"owner",role:"OWNER",permissions:["workspace.read"]}} routeName="dashboard" onLogout={vi.fn()}>
   <h2>Page content</h2>
  </AppShell>);
  fireEvent.keyDown(window,{key:"k",ctrlKey:true});
  expect(await screen.findByRole("dialog",{name:"Search NetRegress"})).toBeTruthy();
  fireEvent.keyDown(screen.getByRole("searchbox",{name:"Search NetRegress"}),{key:"Escape"});
  await waitFor(()=>expect(screen.queryByRole("dialog")).toBeNull());
 });

 it("does not claim a provider is connected when only binding metadata exists",async()=>{
  api.topologyProviderBinding.mockResolvedValue({binding:{binding_id:"binding-a",lab_id:"lab-a",status:"ACTIVE"}});
  render(<AppShell user={{username:"viewer",role:"VIEWER",permissions:["workspace.read","topology.read"]}} routeName="dashboard" onLogout={vi.fn()}>
   <h2>Page content</h2>
  </AppShell>);
  expect(await screen.findByRole("status",{name:"GNS3 · bound · health unknown"})).toBeTruthy();
  expect(screen.queryByText(/connected/i)).toBeNull();
 });
