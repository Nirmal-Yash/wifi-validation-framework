import React,{useEffect,useState} from "react";
import {api} from "./api";
import {navigate,routeFor} from "./router";
import {useRoute} from "./hooks";
import AppShell from "./components/layout";
import {LoadingState} from "./components/ui";
import LoginPage from "./pages/auth";
import DashboardPage from "./pages/dashboard";
import RunsPage from "./pages/runs";
import RunDetailPage from "./pages/run";
import TestDetailPage from "./pages/test";
import {RegressionPage,PerformancePage,TelemetryPage} from "./pages/quality";
import {ArtifactsPage,LabHealthPage,ReadinessPage,BaselinesPage,OperationsPage} from "./pages/system";
import {canAdmin,canExecute} from "./utils";
function NotFound(){return<div className="state-card"><strong>Page not found</strong><span>The requested NetRegress UI route does not exist.</span><button className="button secondary" onClick={()=>navigate("/")}>Return to dashboard</button></div>;}
export default function App(){
 const routeState=useRoute(),[user,setUser]=useState(undefined),[bootError,setBootError]=useState(null);
 useEffect(()=>{api.me().then(setUser).catch(error=>{if(error.status===401)setUser(null);else{setBootError(error);setUser(null);}});},[]);
 if(user===undefined)return<LoadingState label="Loading NetRegress…"/>;
 if(!user)return<LoginPage onLogin={setUser}/>;
 if(bootError)void bootError;
 const route=routeFor(routeState.value);
 let page;
 switch(route.name){
  case"dashboard":page=<DashboardPage/>;break;
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
 return<AppShell user={user} routeName={route.name} onLogout={logout}>{page}</AppShell>;
}