import React from "react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader} from "../hooks";
import {formatDate,terminalStatuses} from "../utils";
import {DataTable,ErrorState,InlineNotice,LoadingState,Section,StatCard,StatusBadge} from "../components/ui";
export default function DashboardPage(){
 const runs=useAsyncLoader(()=>api.runs({limit:8}),[],{refreshMs:10000});
 const readiness=useAsyncLoader(()=>api.readiness(),[],{refreshMs:30000});
 if(runs.loading&&!runs.data)return<LoadingState label="Loading Runner dashboard…"/>;
 if(runs.error&&!runs.data)return<ErrorState error={runs.error} onRetry={runs.reload}/>;
 const items=runs.data?.items||[],active=items.filter(item=>!terminalStatuses.has(item.lifecycle_status)).length,passed=items.filter(item=>item.business_outcome==="PASS").length,unvalidated=items.filter(item=>item.business_outcome==="UNVALIDATED").length;
 return<div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Overview</div><h2>Runner dashboard</h2><p className="muted">Current operational state, recent validation Runs and Runner readiness.</p></div></div>
  {readiness.data?<InlineNotice tone={readiness.data.status==="ready"?"success":"warning"}>Runner readiness: <strong>{readiness.data.status}</strong> — {readiness.data.summary}</InlineNotice>:readiness.error?<InlineNotice tone="warning">Readiness could not be checked: {readiness.error.message}</InlineNotice>:null}
  <div className="stat-grid"><StatCard label="Recent Runs" value={runs.data?.total??0} hint="Most recent persisted Runs"/><StatCard label="Active" value={active} hint="Non-terminal lifecycle states"/><StatCard label="Recent PASS" value={passed} hint="Business outcome"/><StatCard label="Recent UNVALIDATED" value={unvalidated} hint="Evidence/comparability still blocks certification"/></div>
  <Section title="Recent Runs" subtitle="Select a Run to inspect lifecycle, tests, evidence, health and telemetry.">
   <DataTable rows={items} rowKey={row=>row.run_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(row.run_id))} columns={[
    {key:"display_id",label:"Run",render:row=><><strong>{row.display_id}</strong><div className="muted mono">{row.run_id}</div></>},
    {key:"firmware_version",label:"Firmware"},
    {key:"lifecycle_status",label:"Lifecycle",render:row=><StatusBadge value={row.lifecycle_status}/>},
    {key:"business_outcome",label:"Outcome",render:row=><StatusBadge value={row.business_outcome}/>},
    {key:"environment_class",label:"Environment"},
    {key:"created_at",label:"Created",render:row=>formatDate(row.created_at)}
   ]} emptyTitle="No Runs yet" emptyMessage="Launch a Run from the Runs page to populate the dashboard."/>
  </Section>
 </div>;
}