import React,{useEffect,useState} from "react";
import {
  Activity,BarChart3,ChevronRight,ClipboardList,FileText,GitCompare,
  Gauge,LayoutDashboard,LogOut,Menu,PanelLeft,Settings,ShieldCheck,
  Wifi,X,
} from "lucide-react";
import {navigate} from "../router";
import {canAdmin,canExecute} from "../utils";
import {Button,IconButton} from "./ui";

const groups=[
  {title:"Operate",items:[
    ["dashboard","/","Overview",LayoutDashboard],
    ["runs","/runs","Run history",ClipboardList],
    ["artifacts","/artifacts","Evidence",FileText],
    ["readiness","/readiness","Readiness",ShieldCheck],
  ]},
  {title:"Analyze",items:[
    ["regressions","/regressions","Regressions",GitCompare],
    ["performance","/performance","Performance",BarChart3],
    ["telemetry","/telemetry","WiFi telemetry",Wifi],
    ["lab-health","/lab-health","Lab health",Activity],
  ]},
  {title:"Govern",items:[
    ["baselines","/baselines","Baselines",Gauge],
    ["operations","/operations","Operations",Settings],
  ]},
];

const pageMeta={
  dashboard:{group:"Operate",title:"Overview"},
  runs:{group:"Operate",title:"Run history"},
  run:{group:"Operate",title:"Run detail"},
  test:{group:"Operate",title:"Test detail"},
  artifacts:{group:"Operate",title:"Evidence"},
  readiness:{group:"Operate",title:"Readiness"},
  regressions:{group:"Analyze",title:"Regressions"},
  performance:{group:"Analyze",title:"Performance"},
  telemetry:{group:"Analyze",title:"WiFi telemetry"},
  "lab-health":{group:"Analyze",title:"Lab health"},
  baselines:{group:"Govern",title:"Baselines"},
  operations:{group:"Govern",title:"Operations"},
};

function NavLink({routeKey,href,label,Icon,active,onNavigate}){
 return <a href={href} className={"nav-link "+(active?"active":"")} onClick={event=>{event.preventDefault();onNavigate(href);}} aria-current={active?"page":undefined}>
  <Icon size={17} strokeWidth={1.8} aria-hidden="true"/>
  <span>{label}</span>
  {active?<span className="nav-active-mark" aria-hidden="true"/>:null}
 </a>;
}

export default function AppShell({user,routeName,onLogout,children}){
 const[mobileNavOpen,setMobileNavOpen]=useState(false);
 const meta=pageMeta[routeName]||{group:"Operate",title:"Runner"};
 const visibleGroups=groups.map(group=>({...group,items:group.items
  .filter(([key])=>(key!=="baselines"||canAdmin(user.role)))
  .filter(([key])=>(key!=="operations"||canExecute(user.role)))
 })).filter(group=>group.items.length);
 const go=href=>{navigate(href);setMobileNavOpen(false);};
 useEffect(()=>{
  const closeOnEscape=event=>{if(event.key==="Escape")setMobileNavOpen(false);};
  window.addEventListener("keydown",closeOnEscape);
  document.body.classList.toggle("nav-open",mobileNavOpen);
  return()=>{window.removeEventListener("keydown",closeOnEscape);document.body.classList.remove("nav-open");};
 },[mobileNavOpen]);
 const routeMatches=(key)=>routeName===key||(key==="runs"&&["run","test"].includes(routeName));
 const initials=String(user.username||"owner").slice(0,2).toUpperCase();

 return <div className={"app-shell "+(mobileNavOpen?"mobile-nav-open":"")}>
  <a className="skip-link" href="#main-content">Skip to main content</a>
  {mobileNavOpen?<button type="button" className="sidebar-backdrop" aria-label="Close navigation menu" onClick={()=>setMobileNavOpen(false)}/>:null}
  <aside className={"sidebar "+(mobileNavOpen?"is-open":"")} aria-label="Main sidebar">
   <div className="brand">
    <div className="brand-mark" aria-hidden="true">NR</div>
    <div className="brand-wordmark"><strong>NetRegress</strong><span>Validation Runner</span></div>
    <IconButton label="Close navigation" className="sidebar-close" onClick={()=>setMobileNavOpen(false)}><X size={17}/></IconButton>
   </div>
   <div className="workspace-switcher"><span className="workspace-avatar"><PanelLeft size={16}/></span><span><strong>Local workspace</strong><small>Standalone Runner</small></span><ChevronRight size={15} aria-hidden="true"/></div>
   <nav className="sidebar-nav" aria-label="Primary navigation">
    {visibleGroups.map(group=><div className="nav-group" key={group.title}>
     <span className="nav-group-title">{group.title}</span>
     {group.items.map(([key,href,label,Icon])=><NavLink key={key} routeKey={key} href={href} label={label} Icon={Icon} active={routeMatches(key)} onNavigate={go}/>)}
    </div>)}
   </nav>
   <div className="sidebar-bottom">
    <div className="runner-presence"><span className="presence-indicator" aria-hidden="true"/><div><strong>Runner session</strong><span>Authenticated locally</span></div><span className="presence-label">ON</span></div>
    <div className="sidebar-footer">
     <span className="user-avatar" aria-hidden="true">{initials}</span>
     <div className="user-identity"><strong>{user.username}</strong><span>{user.role}</span></div>
     <IconButton label="Sign out" onClick={onLogout}><LogOut size={17}/></IconButton>
    </div>
   </div>
  </aside>
  <main className="content" id="main-content" tabIndex="-1">
   <header className="topbar">
    <div className="topbar-left">
     <IconButton label="Open navigation" className="mobile-nav-trigger" onClick={()=>setMobileNavOpen(true)}><Menu size={19}/></IconButton>
     <div className="topbar-breadcrumb"><span>NetRegress</span><ChevronRight size={13} aria-hidden="true"/><span>{meta.group}</span><ChevronRight size={13} aria-hidden="true"/><strong>{meta.title}</strong></div>
    </div>
    <div className="topbar-meta">
     <span className="environment-pill"><span className="presence-indicator" aria-hidden="true"/>Local Runner</span>
     <span className="role-pill"><ShieldCheck size={14} aria-hidden="true"/>{user.role}</span>
    </div>
   </header>
   <h1 className="sr-only">{meta.title}</h1>
   <div className="content-body">{children}</div>
  </main>
 </div>;
}
