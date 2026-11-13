import React from "react";
import {
 Activity,BarChart3,ChevronDown,ChevronRight,ClipboardList,FileArchive,
 FileCheck2,GitCompare,LayoutDashboard,LogOut,SlidersHorizontal,Wifi,ShieldCheck,Users,KeyRound,Settings2,
} from "lucide-react";
import {navigate} from "@/router";
import {canAdmin,canExecute,canPerform} from "@/permissions";
import {DropdownMenu,DropdownMenuContent,DropdownMenuItem,DropdownMenuLabel,DropdownMenuSeparator,DropdownMenuTrigger} from "@/components/ui/dropdown-menu";
import {
 Sidebar,SidebarContent,SidebarFooter,SidebarGroup,SidebarGroupLabel,
 SidebarHeader,SidebarInset,SidebarMenu,SidebarMenuButton,SidebarMenuItem,
 SidebarProvider,SidebarTrigger,
} from "@/components/ui/sidebar";
import {ThemeToggle} from "@/components/theme-toggle";

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
export default function AppShell({user,routeName,onLogout,children}){
 const meta=pageMeta[routeName]||{section:"Workspace",title:"Runner",description:"NetRegress standalone validation operations."};
 const visibleGroups=navGroups.map(group=>({
  ...group,
  items:group.items.filter(([key])=>key!=="baselines"||canPerform(user,"baselines.manage")).filter(([key])=>key!=="operations"||canExecute(user)).filter(([key])=>key!=="administration"||canPerform(user,"users.read")||canPerform(user,"roles.read")||canPerform(user,"permissions.read")||canPerform(user,"audit.read")),
 })).filter(group=>group.items.length);
 const activeKey=routeName==="run"||routeName==="test"?"runs":routeName;
 const go=(event,href)=>{event.preventDefault();navigate(href);};
 return <SidebarProvider>
  <a className="skip-link" href="#main-content">Skip to main content</a>
  <Sidebar>
   <SidebarHeader><Brand/><SidebarTrigger/></SidebarHeader>
   <div className="workspace-card">
    <span className="workspace-icon"><Activity size={16}/></span>
    <span className="workspace-copy"><strong>Reference workspace</strong><small>Local network environment</small></span>
    <span className="workspace-status" title="Local session">LOCAL</span>
   </div>
   <SidebarContent>
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
    <div className="topbar-end"><span className="local-pill"><span className="presence-indicator"/>Local runtime</span><span className="topbar-divider"/><ThemeToggle/><UserMenu user={user} onLogout={onLogout}/></div>
   </header>
   <main id="main-content" className="content-body" tabIndex="-1">
    <div className="content-intro"><div><div className="eyebrow">{meta.section}</div><h1>{meta.title}</h1><p>{meta.description}</p></div><div className="content-intro-meta"><span className="role-chip">{user.role}</span></div></div>
    <div className="page-content" key={routeName+window.location.pathname+window.location.search}>{children}</div>
   </main>
   <footer className="app-footer"><span>NetRegress · Network validation platform</span><span>Local-first · Evidence-led validation</span></footer>
  </SidebarInset>
 </SidebarProvider>;
}
