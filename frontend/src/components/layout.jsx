import React from "react";
import {navigate} from "../router";
import {canAdmin,canExecute} from "../utils";
import {Button} from "./ui";

const groups=[
 {title:"Operate",items:[["dashboard","/","Dashboard"],["runs","/runs","Runs"],["artifacts","/artifacts","Artifacts"],["readiness","/readiness","Readiness"]]},
 {title:"Analyze",items:[["regressions","/regressions","Regressions"],["performance","/performance","Performance"],["telemetry","/telemetry","Telemetry"],["lab-health","/lab-health","Lab Health"]]},
 {title:"Govern",items:[["baselines","/baselines","Baselines"],["operations","/operations","Operations"]]}
];

function NavLink({href,label,active}) {
 return <a href={href} className={"nav-link "+(active?"active":"")} onClick={event=>{event.preventDefault();navigate(href);}} aria-current={active?"page":undefined}>{label}</a>;
}

export default function AppShell({user,routeName,onLogout,children}) {
 const visibleGroups=groups.map(group=>({...group,items:group.items.filter(([key])=>(key!=="baselines"||canAdmin(user.role))).filter(([key])=>(key!=="operations"||canExecute(user.role)))})).filter(group=>group.items.length);
 return <div className="app-shell">
  <a className="skip-link" href="#main-content">Skip to main content</a>
  <aside className="sidebar">
   <div className="brand"><div className="brand-mark" aria-hidden="true">NR</div><div><strong>NetRegress</strong><span>Validation Runner</span></div></div>
   <nav aria-label="Primary navigation">{visibleGroups.map(group=><div className="nav-group" key={group.title}><span className="nav-group-title">{group.title}</span>{group.items.map(([key,href,label])=><NavLink key={key} href={href} label={label} active={routeName===key}/>)}</div>)}</nav>
   <div className="sidebar-footer"><div className="identity"><strong>{user.username}</strong><span>{user.role}</span></div><Button variant="secondary" onClick={onLogout}>Sign out</Button></div>
  </aside>
  <main className="content" id="main-content" tabIndex="-1">
   <header className="topbar">
    <div><div className="eyebrow">NETREGRESS / STANDALONE RUNNER</div><h1>Validation operations</h1></div>
    <div className="topbar-meta"><span className="environment-pill">Local Runner</span><span className="role-pill"><span className="role-dot" aria-hidden="true"/>{user.role}</span></div>
   </header>
   <div className="content-body">{children}</div>
  </main>
 </div>;
}
