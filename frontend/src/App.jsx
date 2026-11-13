import React from "react";
import {ArrowLeft,ShieldAlert} from "lucide-react";
import {navigate,routeFor} from "@/router";
import {useRoute} from "@/hooks";
import AppShell from "@/components/layout";
import LoginPage from "@/pages/auth";
import DashboardPage from "@/pages/dashboard";
import RunsPage from "@/pages/runs";
import RunDetailPage from "@/pages/run";
import TestDetailPage from "@/pages/test";
import {RegressionPage,PerformancePage,TelemetryPage} from "@/pages/quality";
import {ArtifactsPage,LabHealthPage,ReadinessPage,BaselinesPage,OperationsPage} from "@/pages/system";
import {WorkspacePage,AdministrationPage,AccountAccessPage} from "@/pages/admin";
import {Button,LoadingState,Section} from "@/components/ui";
import {useSession} from "@/auth/session-provider";
import {canAccessRoute} from "@/permissions";

function NotFound(){
 return <Section title="Page not found" subtitle="This route is not part of the NetRegress Runner UI.">
  <Button variant="outline" onClick={()=>navigate("/")}><ArrowLeft size={15}/>Return to overview</Button>
 </Section>;
}
function Forbidden(){
 return <Section title="Access restricted" subtitle="Your current role does not have permission to access this operation.">
  <div className="permission-state"><ShieldAlert size={23}/><div><strong>Insufficient permissions</strong><p>Ask an Owner or Admin to review your assigned role. The Runner API independently enforces every permission.</p></div></div>
  <Button variant="outline" onClick={()=>navigate("/")}>Return to overview</Button>
 </Section>;
}
function RunnerUnavailable({message}){
 return <div className="connection-shell"><section className="connection-panel" role="alert" aria-labelledby="connection-heading">
  <div className="brand"><span className="brand-mark">NR</span><span className="brand-wordmark"><strong>NetRegress</strong><small>VALIDATION RUNNER</small></span></div>
  <h1 id="connection-heading">Runner connection unavailable</h1>
  <p>{message||"The UI cannot reach the Runner API."}</p>
  <p>Start the backend and frontend together from the repository root:</p>
  <p><code>./scripts/start_dashboard.sh</code></p>
  <Button onClick={()=>window.location.reload()}>Retry connection</Button>
 </section></div>;
}

export default function App(){
 const routeState=useRoute();
 const route=routeFor(routeState.value);
 const{status,user,login,logout,sessionNotice,clearNotice}=useSession();
 if(route.name==="account-access")return <AccountAccessPage mode={route.mode}/>;
 if(status==="checking")return <div className="boot-screen"><LoadingState label="Restoring secure Runner session…"/></div>;
 if(status==="anonymous"||status==="authenticating"){
  const unavailable=sessionNotice?.includes("API is unavailable");
  return unavailable?<RunnerUnavailable message={sessionNotice}/>:<LoginPage onLogin={login} notice={sessionNotice} onDismissNotice={clearNotice}/>;
 }
 if(route.name!=="not-found"&&!canAccessRoute(user,route.name)){
  return <AppShell user={user} routeName="dashboard" onLogout={logout}><Forbidden/></AppShell>;
 }
 let page;
 switch(route.name){
  case"dashboard":page=<DashboardPage user={user}/>;break;
  case"runs":page=<RunsPage key={routeState.key} user={user}/>;break;
  case"run":page=<RunDetailPage runId={route.runId} user={user}/>;break;
  case"test":page=<TestDetailPage runId={route.runId} testResultId={route.testResultId}/>;break;
  case"regressions":page=<RegressionPage/>;break;
  case"performance":page=<PerformancePage/>;break;
  case"telemetry":page=<TelemetryPage/>;break;
  case"lab-health":page=<LabHealthPage/>;break;
  case"artifacts":page=<ArtifactsPage/>;break;
  case"baselines":page=<BaselinesPage user={user}/>;break;
  case"operations":page=<OperationsPage user={user}/>;break;
  case"readiness":page=<ReadinessPage/>;break;
  case"workspace":page=<WorkspacePage user={user}/>;break;
  case"administration":page=<AdministrationPage user={user}/>;break;
  default:page=<NotFound/>;break;
 }
 return <AppShell user={user} routeName={route.name} onLogout={logout}>{page}</AppShell>;
}
