import React from "react";
import {useAsyncLoader} from "@/hooks";
import {api} from "@/api";
import {GlobalSearch} from "@/components/global-search";
import {
 Activity,BarChart3,ChevronDown,ChevronRight,ClipboardList,FileArchive,Workflow,RefreshCw,
 FileCheck2,GitCompare,LayoutDashboard,LogOut,SlidersHorizontal,Wifi,ShieldCheck,Users,KeyRound,Settings2,Router,
} from "lucide-react";
import {navigate} from "@/router";
import {canAccessRoute,canExecute,canPerform} from "@/permissions";
import {DropdownMenu,DropdownMenuContent,DropdownMenuItem,DropdownMenuLabel,DropdownMenuSeparator,DropdownMenuTrigger} from "@/components/ui/dropdown-menu";
import {
 Sidebar,SidebarContent,SidebarFooter,SidebarGroup,SidebarGroupLabel,
 SidebarHeader,SidebarInset,SidebarMenu,SidebarMenuButton,SidebarMenuItem,
 SidebarProvider,SidebarTrigger,
} from "@/components/ui/sidebar";
import {ThemeToggle} from "@/components/theme-toggle";
import {WorkspaceProvider,useWorkspace} from "@/components/workspace-context";

const navGroups=[
 {title:"Workspace",items:[
  ["dashboard","/","Overview",LayoutDashboard],
  ["runs","/runs","Validation runs",ClipboardList],
  ["artifacts","/artifacts","Evidence library",FileArchive],
  ["readiness","/readiness","System readiness",ShieldCheck],
  ["workspace","/workspace","Projects & labs",LayoutDashboard],
 ]},
 {title:"Configuration",items:[
  ["credentials","/credentials","Credentials",KeyRound],
  ["configuration","/configuration","Configuration profiles",Settings2],
  ["devices","/devices","Device inventory",Router],
  ["topologies","/topologies","Topology studio",Workflow],
  ["pipelines","/pipelines","Pipelines",Workflow],
 ]},
 {title:"Quality",items:[
  ["regressions","/regressions","Regression analysis",GitCompare],
  ["performance","/performance","Performance",BarChart3],
  ["telemetry","/telemetry","WiFi telemetry",Wifi],
  ["lab-health","/lab-health","Lab health",Activity],
 ]},
 {title:"Administration",items:[
  ["administration","/administration","Users & roles",Users],
 ]},
 {title:"Governance",items:[
  ["baselines","/baselines","Baselines",FileCheck2],
  ["operations","/operations","Operations",SlidersHorizontal],
 ]},
];
const pageMeta={
 dashboard:{section:"Workspace",title:"Workspace overview",description:"Inspect lab readiness, validation activity and evidence from one local workspace."},
 runs:{section:"Lab execution",title:"Validation runs",description:"Launch approved validation work and inspect persisted execution outcomes."},
 run:{section:"Lab execution",title:"Run detail",description:"Execution state, evidence, telemetry and effective configuration."},
 test:{section:"Lab execution",title:"Test detail",description:"Test contract, measurements and evidence semantics."},
 artifacts:{section:"Lab execution",title:"Evidence library",description:"Browse integrity-verified artifacts registered by the local Runner."},
 readiness:{section:"Lab execution",title:"System readiness",description:"Inspect local runtime and lab checks before starting validation work."},
 regressions:{section:"Quality",title:"Regression analysis",description:"Compare persisted Runs and understand the evidence behind each classification."},
 performance:{section:"Quality",title:"Performance",description:"Track valid measurements over time without mixing metrics or units."},
 telemetry:{section:"Quality",title:"WiFi telemetry",description:"Explore environment-aware network observations from persisted evidence."},
 "lab-health":{section:"Quality",title:"Lab health",description:"Inspect read-only snapshots of the execution environment."},
 administration:{section:"Administration",title:"Users and roles",description:"Administer local accounts, scoped roles, permissions and audit history."},
 credentials:{section:"Configuration",title:"Credential vault",description:"Store device credentials outside the database, verify SSH access, rotate secrets and revoke access."},
 configuration:{section:"Configuration",title:"Configuration profiles",description:"Manage typed schemas, versioned profiles, published revisions, assignments and effective configuration previews."},
 devices:{section:"Configuration",title:"Device inventory",description:"Manage Project/Lab-scoped network devices and link each device to an OS-vault credential reference."},
 topologies:{section:"Configuration",title:"Topology studio",description:"Design versioned network topologies with logical nodes, adapters, ports and links before any explicit provider apply."},
 pipelines:{section:"Operations",title:"Pipelines",description:"Create versioned Project/Lab workflows, queue approved operations, monitor execution and review recovery."},
 baselines:{section:"Governance",title:"Baselines",description:"Promote trusted Run evidence into reusable validation baselines."},
 operations:{section:"Governance",title:"Operations",description:"Perform explicitly authorized firmware and release-governance actions."},
};
function Brand(){
 return <a href="/" className="brand" onClick={event=>{event.preventDefault();navigate("/");}}>
  <span className="brand-mark">NR</span>
  <span className="brand-wordmark"><strong>NetRegress</strong><small>NETWORK LAB PLATFORM</small></span>
 </a>;
}
function UserMenu({user,onLogout}){
 const initials=String(user?.username||"owner").slice(0,2).toUpperCase();
 return <DropdownMenu>
  <DropdownMenuTrigger asChild><button className="profile-trigger" aria-label="Open account menu">
   <span className="user-avatar">{initials}</span>
   <span className="profile-copy"><strong>{user.username}</strong><small>{user.role}</small></span>
   <ChevronDown size={15} aria-hidden="true"/>
  </button></DropdownMenuTrigger>
  <DropdownMenuContent align="end" className="profile-menu">
   <DropdownMenuLabel><span className="profile-menu-label">Signed in as</span><strong>{user.username}</strong><small>{user.role} · Local workspace</small></DropdownMenuLabel>
   <DropdownMenuSeparator/>
   <DropdownMenuItem onSelect={onLogout} variant="destructive"><LogOut size={15}/>Sign out</DropdownMenuItem>
  </DropdownMenuContent>
 </DropdownMenu>;
}
function ProviderConnectivityIndicator({workspace,user}){
 const lab=workspace.selectedLab;
 const canRead=canPerform(user,"topology.read");
 const providerId=String(canRead?lab?.provider_id||"": "").trim().toLowerCase();
 const binding=useAsyncLoader(
  ()=>api.topologyProviderBinding(lab.lab_id),
  [lab?.lab_id,providerId],
  {enabled:Boolean(lab?.lab_id&&providerId==="gns3"&&canRead),queryKey:"shell-provider-binding",staleTime:30000},
 );
 let label="Provider · select Lab";
 let detail="Choose a Lab to inspect its provider binding.";
 if(lab&&!canRead){
  label="Provider · restricted";
  detail="Provider details require topology read permission.";
 }else if(lab&&!providerId){
  label="Provider · not assigned";
  detail="No provider is assigned to the selected Lab.";
 }else if(providerId==="gns3"){
  if(binding.loading&&!binding.data){label="GNS3 · loading binding";detail="Reading saved binding metadata only.";}
  else if(binding.error){label="GNS3 · binding unavailable";detail="Saved binding metadata could not be read; connectivity is not verified.";}
  else if(binding.data?.binding){label="GNS3 · bound · health unknown";detail="A saved binding is configuration metadata, not a live controller health check.";}
  else{label="GNS3 · not bound";detail="No active GNS3 binding is saved for this Lab.";}
 }else if(lab){
  label=providerId.toUpperCase()+" · health unknown";
  detail="This shell does not infer connectivity for the selected provider.";
 }
 return <span className="provider-connectivity" role="status" aria-label={label} title={detail}>
  <span className="provider-connectivity-indicator" aria-hidden="true"/>
  <span>{label}</span>
 </span>;
}

function AppShellContent({user,routeName,onLogout,children}){
 const meta=pageMeta[routeName]||{section:"Workspace",title:"Runner",description:"NetRegress standalone validation operations."};
 const workspace=useWorkspace();
 const visibleGroups=navGroups.map(group=>({
  ...group,
  items:group.items.filter(([key])=>canAccessRoute(user,key)),
 })).filter(group=>group.items.length);
 const searchItems=visibleGroups.flatMap(group=>group.items.map(([key,href,label])=>({key,href,label,group:group.title})));
 const activeKey=routeName==="run"||routeName==="test"?"runs":routeName;
 const go=(event,href)=>{event.preventDefault();navigate(href);};
 return <SidebarProvider>
  <a className="skip-link" href="#main-content">Skip to main content</a>
  <Sidebar>
   <SidebarHeader><Brand/><SidebarTrigger/></SidebarHeader>
   <div className="workspace-card" role="group" aria-label="Current workspace">
    <span className="workspace-icon"><Activity size={16}/></span>
    <span className="workspace-copy">
     <strong title={workspace.selectedOrganization?.name||"No Organization selected"}>{workspace.selectedOrganization?.name||(workspace.organizationsLoading?"Loading workspace…":"Choose Organization")}</strong>
     <small title={[workspace.selectedProject?.name,workspace.selectedLab?.name].filter(Boolean).join(" · ")}>
      {workspace.selectedProject?.name||"No Project selected"}{workspace.selectedLab?.name?" · "+workspace.selectedLab.name:""}
     </small>
    </span>
    <span className="workspace-status" title="Standalone local application">LOCAL MODE</span>
   </div>
   <SidebarContent role="navigation" aria-label="Primary navigation">
    {visibleGroups.map(group=><SidebarGroup key={group.title}>
     <SidebarGroupLabel>{group.title}</SidebarGroupLabel>
     <SidebarMenu>{group.items.map(([key,href,label,Icon])=><SidebarMenuItem key={key}>
      <SidebarMenuButton href={href} tooltip={label} isActive={activeKey===key} onClick={event=>go(event,href)}>
       <Icon size={17} strokeWidth={1.8} aria-hidden="true"/><span>{label}</span>
      </SidebarMenuButton>
     </SidebarMenuItem>)}</SidebarMenu>
    </SidebarGroup>)}
   </SidebarContent>
   <SidebarFooter>
    <div className="sidebar-security-note"><span className="security-indicator"/><span><strong>Session protected</strong><small>{user.role} · Authenticated local session</small></span></div>
   </SidebarFooter>
  </Sidebar>
  <SidebarInset>
   <header className="topbar">
    <div className="topbar-start"><SidebarTrigger/><div className="breadcrumbs"><span>NetRegress</span><ChevronRight size={13}/><span>{meta.section}</span><ChevronRight size={13}/><strong>{meta.title}</strong></div></div>
    <div className="workspace-context-controls" aria-label="Active workspace context" aria-busy={workspace.loading}>
     <label><span>Organization</span><select aria-label="Active organization" value={workspace.activeOrganizationId} onChange={event=>workspace.selectOrganization(event.target.value)} disabled={workspace.organizationsLoading||!workspace.organizations.length}>
      <option value="">{workspace.organizationsLoading?"Loading organizations…":workspace.organizations.length?"Select organization":"No organizations available"}</option>
      {workspace.organizations.map(item=><option key={item.organization_id} value={item.organization_id}>{item.name}</option>)}
     </select></label>
     <label><span>Project</span><select aria-label="Active project" value={workspace.activeProjectId} onChange={event=>workspace.selectProject(event.target.value)} disabled={!workspace.activeOrganizationId||workspace.projectsLoading||!workspace.projects.length}>
      <option value="">{!workspace.activeOrganizationId?"Select organization first":workspace.projectsLoading?"Loading projects…":workspace.projects.length?"Select project":"No projects available"}</option>
      {workspace.projects.map(item=><option key={item.project_id} value={item.project_id}>{item.name}</option>)}
     </select></label>
     <label><span>Lab</span><select aria-label="Active lab" value={workspace.activeLabId} onChange={event=>workspace.selectLab(event.target.value)} disabled={!workspace.activeProjectId||workspace.labsLoading||!workspace.labs.length}>
      <option value="">{!workspace.activeProjectId?"Select project first":workspace.labsLoading?"Loading labs…":workspace.labs.length?"No lab selected":"No labs available"}</option>
      {workspace.labs.map(item=><option key={item.lab_id} value={item.lab_id}>{item.name}</option>)}
     </select></label>
    </div>
    <div className="topbar-end">
     <GlobalSearch navigationItems={searchItems} workspace={workspace}/>
     <ProviderConnectivityIndicator workspace={workspace} user={user}/>
     {workspace.error?<span className="workspace-context-error" role="status"><span>{workspace.error}</span><button type="button" onClick={workspace.retry} aria-label="Retry loading workspace context" title="Retry workspace context"><RefreshCw size={13}/>Retry</button></span>:null}
     <span className="local-pill" title="Standalone local application runtime">Local runtime</span><span className="topbar-divider"/><ThemeToggle/><UserMenu user={user} onLogout={onLogout}/>
    </div>
   </header>
   <main id="main-content" className="content-body" tabIndex="-1">
    <div className="content-intro"><div><div className="eyebrow">{meta.section}</div><h1>{meta.title}</h1><p>{meta.description}</p></div><div className="content-intro-meta"><span className="role-chip">{user.role}</span></div></div>
    <div className="page-content" key={routeName+window.location.pathname+window.location.search}>{children}</div>
   </main>
   <footer className="app-footer"><span>NetRegress · Network validation platform</span><span>Local-first · Evidence-led validation</span></footer>
  </SidebarInset>
 </SidebarProvider>;
}

export default function AppShell(props){
 return <WorkspaceProvider key={props.user?.username||"anonymous"} user={props.user}><AppShellContent {...props}/></WorkspaceProvider>;
}
