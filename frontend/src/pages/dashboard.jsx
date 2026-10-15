import React from "react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader} from "../hooks";
import {formatDate,summarizeRunOutcomes} from "../utils";
import {Button,DataTable,ErrorState,InlineNotice,LoadingState,Section,StatCard,StatusBadge} from "../components/ui";

export default function DashboardPage() {
 const runs=useAsyncLoader(()=>api.runs({limit:8}),[],{refreshMs:10000});
 const readiness=useAsyncLoader(()=>api.readiness(),[],{refreshMs:30000});
 if(runs.loading&&!runs.data)return <LoadingState label="Loading Runner dashboard…"/>;
 if(runs.error&&!runs.data)return <ErrorState error={runs.error} onRetry={runs.reload}/>;

 const items=runs.data?.items||[];
 const summary=summarizeRunOutcomes(items);
 const total=runs.data?.total??0;

 return <div className="page-stack">
  <section className="dashboard-hero" aria-labelledby="dashboard-title">
   <div className="dashboard-hero-copy">
    <div className="dashboard-hero-kicker"><span className="hero-tag">RUNNER OVERVIEW</span><span className="hero-refresh"><span className="hero-live-dot" aria-hidden="true"/>Refreshes every 10 seconds</span></div>
    <h2 id="dashboard-title">Validation, with evidence attached.</h2>
    <p>Monitor recent Runs, check Runner readiness, and inspect persisted test evidence. Missing or unvalidated evidence is never counted as a successful outcome.</p>
   </div>
   <div className="dashboard-hero-actions">
    <Button onClick={()=>navigate("/runs")}>Open Run history</Button>
    <Button variant="secondary" onClick={()=>navigate("/artifacts")}>Browse evidence</Button>
   </div>
  </section>

  {readiness.data?<InlineNotice tone={readiness.data.status==="ready"?"success":"warning"}>Runner readiness: <strong>{readiness.data.status}</strong> — {readiness.data.summary}</InlineNotice>:readiness.error?<InlineNotice tone="warning">Readiness could not be checked: {readiness.error.message}</InlineNotice>:null}

  <div className="stat-grid">
   <StatCard label="Total Runs" value={total} hint="All persisted Runs"/>
   <StatCard label="Active · latest 8" value={summary.active} hint="Non-terminal Runs in the visible list"/>
   <StatCard label="Validated outcomes · latest 8" value={summary.validated} hint="VALIDATED and VALIDATED_WITH_WARNINGS"/>
   <StatCard label="Rejected / unvalidated · latest 8" value={summary.needsReview} hint="Outcomes that need review; not counted as success"/>
  </div>

  <Section title="Latest Runs" subtitle={items.length+" shown · "+total+" total persisted"} actions={<Button variant="secondary" onClick={()=>navigate("/runs")}>View all Runs</Button>}>
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
