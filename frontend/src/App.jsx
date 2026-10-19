import React,{useEffect,useState} from "react";
import {api} from "./api";
import {navigate,routeFor} from "./router";
import {useRoute} from "./hooks";
import AppShell from "./components/layout";
import {Button,LoadingState} from "./components/ui";
import LoginPage from "./pages/auth";
import DashboardPage from "./pages/dashboard";
import RunsPage from "./pages/runs";
import RunDetailPage from "./pages/run";
import TestDetailPage from "./pages/test";
import {RegressionPage,PerformancePage,TelemetryPage} from "./pages/quality";
import {ArtifactsPage,LabHealthPage,ReadinessPage,BaselinesPage,OperationsPage} from "./pages/system";
import {canAdmin,canExecute} from "./utils";
import {ArrowLeft} from "lucide-react";

function NotFound(){return <div className="state-card empty"><h2>Page not found</h2><p>The requested NetRegress route does not exist.</p><Button variant="outline" onClick={()=>navigate("/")}><ArrowLeft size={15}/>Return to overview</Button></div>;}

function RunnerConnectionError({error,onRetry}){
 return <div className="login-shell"><section className="login-panel" role="alert" aria-labelledby="runner-connection-heading">
  <div className="brand brand-centered"><div className="brand-mark" aria-hidden="true">NR</div><div><strong>NetRegress</strong><span>Validation Runner</span></div></div>
  <h1 id="runner-connection-heading">Runner connection problem</h1>
  <p className="muted">The web UI cannot reach the Flask Runner API. This is a service/proxy issue, not a bad username or password.</p>
  <p>{error?.message || "The Runner API did not respond."}</p>
  <p className="muted">Start the backend and UI together from the repository root:</p>
  <p><code>./scripts/start_dashboard.sh</code></p>
  <Button onClick={onRetry}>Retry connection</Button>
 </section></div>;
}

export default function App(){
 const routeState=useRoute(),[user,setUser]=useState(undefined),[bootError,setBootError]=useState(null);
 const restoreSession=async()=>{
  setBootError(null);
  try{
   const profile=await api.me();
   if(!profile||!profile.username)throw new Error("The Runner returned an invalid session profile. Check that the backend and proxy use the same port.");
   setUser(profile);
  }catch(error){
   setUser(null);
   if(error.status!==401)setBootError(error);
  }
 };
 useEffect(()=>{void restoreSession();},[]);
 if(user===undefined)return <LoadingState label="Loading NetRegress…"/>;
 if(bootError)return <RunnerConnectionError error={bootError} onRetry={()=>{setUser(undefined);void restoreSession();}}/>;
 if(!user)return <LoginPage onLogin={setUser}/>;
 const route=routeFor(routeState.value);
 let page;
 switch(route.name){
  case"dashboard":page=<DashboardPage user={user}/>;break;
  case"runs":page=<RunsPage user={user}/>;break;
  case"run":page=<RunDetailPage runId={route.runId} user={user}/>;break;
  case"test":page=<TestDetailPage runId={route.runId} testResultId={route.testResultId}/>;break;
  case"regressions":page=<RegressionPage/>;break;
  case"performance":page=<PerformancePage/>;break;
  case"telemetry":page=<TelemetryPage/>;break;
  case"lab-health":page=<LabHealthPage/>;break;
  case"artifacts":page=<ArtifactsPage/>;break;
  case"baselines":page=canAdmin(user.role)?<BaselinesPage/>:<NotFound/>;break;
  case"operations":page=canExecute(user.role)?<OperationsPage/>:<NotFound/>;break;
  case"readiness":page=<ReadinessPage/>;break;
  default:page=<NotFound/>;
 }
 const logout=async()=>{try{await api.logout();}finally{setUser(null);navigate("/");}};
 return <AppShell user={user} routeName={route.name} onLogout={logout}>{page}</AppShell>;
}
