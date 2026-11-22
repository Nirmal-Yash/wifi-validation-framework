import React from "react";
import {
  Activity,ArrowUpRight,BookOpen,CheckCircle2,Clock3,Database,
  FileText,Play,RefreshCw,ShieldCheck,
} from "lucide-react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader} from "../hooks";
import {formatDate,summarizeRunOutcomes} from "../utils";
import {Button,DataTable,EmptyState,ErrorState,InlineNotice,LoadingState,OutcomeBreakdown,Section,StatCard,StatusBadge} from "../components/ui";
import {canPerform} from "../permissions";
import {useWorkspace} from "../components/workspace-context";

export default function DashboardPage({user}){
 const workspace=useWorkspace();
 const projectId=workspace.activeProjectId;
 const labId=workspace.activeLabId;
 const runs=useAsyncLoader(()=>api.runs({limit:8,project_id:projectId,...(labId?{lab:labId}:{})}),[projectId,labId],{enabled:Boolean(projectId),refreshMs:10000});
 const operations=useAsyncLoader(()=>api.operationsOverview(projectId,labId||undefined),[projectId,labId],{enabled:Boolean(projectId),refreshMs:30000});
 const readiness=useAsyncLoader(()=>api.readiness(),[],{refreshMs:30000});
 const items=runs.data?.items||[];
 const summary=summarizeRunOutcomes(items);
 const total=runs.data?.total??0;
 const hasRunScope=Boolean(projectId&&runs.data);
 const totalLabel=hasRunScope?total.toLocaleString():"—";
 const displayedOutcomes=summary.validated+summary.validatedWithWarnings+summary.rejected+summary.unvalidated;
 const lastRun=items[0];

 return <div className="page-stack dashboard-page">
  <section className="dashboard-hero" aria-labelledby="dashboard-title">
   <div className="dashboard-hero-copy">
    <div className="dashboard-hero-kicker"><span className="hero-tag"><Activity size={13} aria-hidden="true"/>RUNNER OVERVIEW</span><span className="hero-refresh"><span className="hero-live-dot" aria-hidden="true"/>Auto-refresh every 10 seconds</span></div>
    <h2 id="dashboard-title">Validation you can trust.</h2>
    <p>Track execution, inspect evidence, and understand release outcomes from one place. A successful test process alone is not a validated release.</p>
    <div className="hero-metadata"><span><Database size={14} aria-hidden="true"/>{hasRunScope?totalLabel+" persisted Runs":"Select a Project for Run totals"}</span><span><Clock3 size={14} aria-hidden="true"/>Last activity {lastRun?formatDate(lastRun.created_at):"not recorded"}</span></div>
   </div>
   <div className="dashboard-hero-actions">
    {canPerform(user,"runs.execute")?<Button onClick={()=>navigate("/runs?launch=1")}><Play size={15} aria-hidden="true"/>Start a Run<ArrowUpRight size={14} aria-hidden="true"/></Button>:null}
    <Button variant="outline" onClick={()=>navigate("/runs")}>Run history<ArrowUpRight size={14} aria-hidden="true"/></Button>
    <Button variant="ghost" onClick={()=>navigate("/artifacts")}><FileText size={15} aria-hidden="true"/>Evidence</Button>
   </div>
  </section>

  <div className="section-intro"><div><h2>At a glance</h2><p>Persisted Run volume in the selected Project/Lab scope alongside the latest eight Run outcomes.</p></div><div className="section-intro-meta">Updated {new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}</div></div>
  <div className="stat-grid">
   <StatCard label="Total Runs" value={totalLabel} hint="Persisted Runs in selected scope" icon={<Database size={17}/>} />
   <StatCard label="Recent Active Runs" value={hasRunScope?summary.active:"—"} hint="From latest 8 only" icon={<Activity size={17}/>} tone={summary.active?"info":"default"}/>
   <StatCard label="Validated" value={summary.validated} hint="No release-blocking findings" icon={<CheckCircle2 size={17}/>} tone="success" footnote="Latest 8 Runs"/>
   <StatCard label="Needs review" value={summary.needsReview} hint="Rejected or unvalidated outcomes" icon={<ShieldCheck size={17}/>} tone={summary.needsReview?"warning":"default"} footnote="Latest 8 Runs"/>
  </div>

  <div className="dashboard-grid">
   <Section title="Outcome distribution" subtitle={"Business outcomes for "+items.length+" recent Runs. Counts exclude pytest-only PASS labels."} actions={<Button variant="ghost" size="sm" onClick={()=>navigate("/runs")}>Inspect all <ArrowUpRight size={13}/></Button>}>
    {items.length?<OutcomeBreakdown items={items}/>:<EmptyState title="No outcomes yet" message="Run a validation to populate the outcome distribution."/>}
    {items.length&&displayedOutcomes<items.length?<p className="chart-disclaimer">Some recent Runs have no final business outcome yet. They remain visible as a separate category.</p>:null}
   </Section>
   <Section title="Runner readiness" subtitle="Runtime and environment checks, refreshed every 30 seconds" actions={<Button variant="ghost" size="sm" onClick={()=>readiness.reload().catch(()=>{})}><RefreshCw size={14}/>Refresh</Button>}>
    {readiness.loading&&!readiness.data?<div className="readiness-loading"><LoadingState label="Checking API and runtime…"/></div>:null}
    {readiness.error&&!readiness.data?<InlineNotice tone="warning">Readiness could not be checked: {readiness.error.message}</InlineNotice>:null}
    {readiness.data?<><div className="readiness-overview"><div className={"readiness-glyph "+(readiness.data.status==="ready"?"ready":"not-ready")}>{readiness.data.status==="ready"?<CheckCircle2 size={20}/>:<ShieldCheck size={20}/>}</div><div><strong>{readiness.data.status==="ready"?"Ready to run":"Action required"}</strong><p>{readiness.data.summary}</p></div><StatusBadge value={readiness.data.status}/></div>
      <div className="readiness-check-list">{(readiness.data.checks||[]).map(check=><div className="readiness-check" key={check.check_id}><span className="readiness-check-title">{check.check_id.replaceAll("_"," ")}</span><StatusBadge value={check.status}/></div>)}</div>
    </>:null}
    <p className="readiness-footnote"><BookOpen size={13} aria-hidden="true"/> Readiness is not proof of a successful REAL_LAB certification run.</p>
   </Section>
  </div>


  <Section title="Network operations" subtitle={projectId?"Persisted Project/Lab state · source timestamps shown where available":"Select a Project to inspect scoped network operations."} actions={operations.isFetching?<span className="muted">Refreshing…</span>:null}>
   {!projectId?<EmptyState title="No Project selected" message="Choose an Organization and Project in the application header to load operational data."/>:null}
   {operations.loading&&!operations.data?<LoadingState label="Loading network operations…"/>:null}
   {operations.error?<ErrorState error={operations.error} onRetry={operations.reload}/>:null}
   {operations.data?<>
    <div className="operations-summary-grid">
     <StatCard label="Labs in scope" value={operations.data.labs?.in_scope??0} hint={(operations.data.labs?.by_status?.ACTIVE||0)+" active · "+(operations.data.labs?.total??0)+" total in Project"} footnote={"Source updated "+formatDate(operations.data.labs?.source_updated_at)} icon={<Database size={17}/>} />
     <StatCard label="Managed devices" value={operations.data.devices?.access==="RESTRICTED"?"Restricted":(operations.data.devices?.total??0)} hint={operations.data.devices?.access==="RESTRICTED"?"Device inventory permission required":(operations.data.devices?.active||0)+" active · "+(operations.data.devices?.archived||0)+" archived"} footnote={operations.data.devices?.access==="RESTRICTED"?undefined:"Source updated "+formatDate(operations.data.devices?.source_updated_at)} icon={<Activity size={17}/>} />
     <StatCard label="Topology profiles" value={operations.data.topology?.access==="RESTRICTED"?"Restricted":(operations.data.topology?.profiles??0)} hint={operations.data.topology?.access==="RESTRICTED"?"Topology read permission required":(operations.data.topology?.revisions||0)+" revisions"} footnote={operations.data.topology?.access==="RESTRICTED"?undefined:"Source updated "+formatDate(operations.data.topology?.source_updated_at)} icon={<BookOpen size={17}/>} />
     <StatCard label="Pipelines" value={operations.data.pipelines?.access==="RESTRICTED"?"Restricted":(operations.data.pipelines?.total??0)} hint={operations.data.pipelines?.access==="RESTRICTED"?"Pipeline read permission required":(operations.data.pipelines?.queued||0)+" queued · "+(operations.data.pipelines?.running||0)+" running · "+(operations.data.pipelines?.cancelling||0)+" cancelling"} footnote={operations.data.pipelines?.access==="RESTRICTED"?undefined:"Source updated "+formatDate(operations.data.pipelines?.source_updated_at)} icon={<Play size={17}/>} />
    </div>
    <div className="operations-detail-grid">
     <div className="operations-detail-panel">
      <h3>Project and Lab scope</h3>
      <div className="operations-detail-row"><span><strong>{operations.data.scope?.project?.name||"Selected Project"}</strong><small>{operations.data.scope?.project?.project_id||projectId}</small></span><StatusBadge value={operations.data.scope?.project?.status}/></div>
       <div className="operations-detail-row"><span>Organization</span><strong>{workspace.selectedOrganization?.name||operations.data.scope?.project?.organization_id||"Not recorded"}</strong></div>
       <div className="operations-detail-row"><span>Selected Lab</span><strong>{workspace.selectedLab?.name||(labId||"All Labs")}</strong></div>
      <div className="operations-detail-row"><span>Labs in Project</span><strong>{operations.data.labs?.total??0}</strong></div>
      <div className="operations-detail-row"><span>Labs in current scope</span><strong>{operations.data.labs?.in_scope??0}</strong></div>
      {Object.entries(operations.data.labs?.by_status||{}).map(([status,count])=><div className="operations-detail-row" key={status}><span>{status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
      <p className="muted">Project source updated at {formatDate(operations.data.scope?.project?.source_updated_at)} · Lab source updated at {formatDate(operations.data.labs?.source_updated_at)}</p>
     </div>
     <div className="operations-detail-panel">
      <h3>Provider bindings</h3>
      {operations.data.providers?.access==="RESTRICTED"?<p className="muted">Provider binding details require topology read permission.</p>:(operations.data.providers?.items||[]).length?operations.data.providers.items.map(item=><div className="operations-detail-row" key={item.lab_id}><span><strong>{item.provider_id||"Provider not recorded"} · {item.lab_id}</strong><small>Binding: {item.binding_status} · Source updated {formatDate(item.source_updated_at)}</small><small>Source: {(item.source||[]).join(" · ")||"Not recorded"}</small></span><StatusBadge value={item.connection_health}/></div>):<p className="muted">No Lab provider bindings are recorded in this scope.</p>}
      <p className="chart-disclaimer">A saved binding is configuration metadata, not a live health check. Connection health remains unknown until an authenticated provider probe returns real evidence.</p>
     </div>
     <div className="operations-detail-panel">
      <h3>Device inventory</h3>
      {operations.data.devices?.access==="RESTRICTED"?<p className="muted">Device inventory counts are restricted by Project permissions.</p>:Object.entries(operations.data.devices?.by_status||{}).length?Object.entries(operations.data.devices.by_status).map(([status,count])=><div className="operations-detail-row" key={status}><span>{status.replaceAll("_"," ")}</span><strong>{count}</strong></div>):<p className="muted">No persisted devices are recorded in this scope.</p>}
      {operations.data.devices?.access!=="RESTRICTED"?<p className="muted">Source updated at {formatDate(operations.data.devices?.source_updated_at)}</p>:null}
     </div>
     <div className="operations-detail-panel">
      <h3>Topology inventory</h3>
      {operations.data.topology?.access==="RESTRICTED"?<p className="muted">Topology and provider metadata require topology read permission.</p>:<>
       <div className="operations-detail-row"><span>Profiles</span><strong>{operations.data.topology?.profiles??0}</strong></div>
       <div className="operations-detail-row"><span>Revisions</span><strong>{operations.data.topology?.revisions??0}</strong></div>
       <div className="operations-detail-row"><span>Provider apply records</span><strong>{operations.data.topology?.apply_records??0}</strong></div>
        {Object.entries(operations.data.topology?.profiles_by_status||{}).map(([status,count])=><div className="operations-detail-row" key={"profile-"+status}><span>Profiles · {status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
        {Object.entries(operations.data.topology?.revisions_by_status||{}).map(([status,count])=><div className="operations-detail-row" key={"revision-"+status}><span>Revisions · {status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
        {Object.entries(operations.data.topology?.apply_by_status||{}).map(([status,count])=><div className="operations-detail-row" key={"apply-"+status}><span>Apply · {status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
        {(operations.data.topology?.latest_published_revisions||[]).map(item=><div className="operations-detail-row" key={"published-"+item.revision_id}><span>Latest published · {item.profile_name}</span><strong>r{item.revision_number}</strong></div>)}
       <p className="muted">Source updated at {formatDate(operations.data.topology?.source_updated_at)}</p>
      </>}
     </div>
     <div className="operations-detail-panel">
      <h3>Pipeline execution state</h3>
      {operations.data.pipelines?.access==="RESTRICTED"?<p className="muted">Pipeline execution counts are restricted by Project permissions.</p>:<>
        <div className="operations-detail-row"><span>Definitions</span><strong>{operations.data.pipelines?.total??0}</strong></div>
        {Object.entries(operations.data.pipelines?.by_status||{}).map(([status,count])=><div className="operations-detail-row" key={"definition-"+status}><span>Definitions · {status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
        <div className="operations-detail-row"><span>Total executions</span><strong>{operations.data.pipelines?.executions??0}</strong></div>
        {Object.entries(operations.data.pipelines?.executions_by_status||{}).map(([status,count])=><div className="operations-detail-row" key={"execution-"+status}><span>Executions · {status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
        <div className="operations-detail-row"><span>Pipeline steps</span><strong>{operations.data.pipelines?.steps??0}</strong></div>
        {Object.entries(operations.data.pipelines?.steps_by_status||{}).map(([status,count])=><div className="operations-detail-row" key={"step-"+status}><span>Steps · {status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
        <div className="operations-detail-row"><span>Active steps</span><strong>{operations.data.pipelines?.active_steps??0}</strong></div>
        <div className="operations-detail-row"><span>Failed steps</span><strong>{operations.data.pipelines?.failed_steps??0}</strong></div>
        <div className="operations-detail-row"><span>Recovery-required steps</span><strong>{operations.data.pipelines?.recovery_required_steps??0}</strong></div>
        <div className="operations-detail-row"><span>Queued</span><strong>{operations.data.pipelines?.queued??0}</strong></div>
        <div className="operations-detail-row"><span>Running</span><strong>{operations.data.pipelines?.running??0}</strong></div>
        <div className="operations-detail-row"><span>Cancelling</span><strong>{operations.data.pipelines?.cancelling??0}</strong></div>
        <div className="operations-detail-row"><span>Recovery required</span><strong>{operations.data.pipelines?.recovery_required??0}</strong></div>
       <p className="muted">Source updated at {formatDate(operations.data.pipelines?.source_updated_at)}</p>
      </>}
     </div>
     <div className="operations-detail-panel">
      <h3>Validation activity</h3>
       {operations.data.runs?.access==="RESTRICTED"?<p className="muted">Run lifecycle and business-outcome totals require runs.read permission.</p>:<>
       <div className="operations-detail-row"><span>Total persisted Runs</span><strong>{operations.data.runs?.total??0}</strong></div>
       <div className="operations-detail-row"><span>Active Runs</span><strong>{operations.data.runs?.active??0}</strong></div>
      <small className="muted">Run lifecycle</small>
      {Object.entries(operations.data.runs?.by_lifecycle||{}).length?Object.entries(operations.data.runs.by_lifecycle).map(([status,count])=><div className="operations-detail-row" key={status}><span>{status.replaceAll("_"," ")}</span><strong>{count}</strong></div>):<p className="muted">No persisted Runs are recorded for this Project/Lab selection.</p>}
      <small className="muted">Business outcomes</small>
      {Object.entries(operations.data.runs?.by_outcome||{}).map(([outcome,count])=><div className="operations-detail-row" key={outcome}><span>{outcome.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
      <p className="muted">Source updated at {formatDate(operations.data.runs?.source_updated_at)}</p>
       </>}
     </div>
     <div className="operations-detail-panel">
      <h3>Configuration deployments</h3>
      {operations.data.configuration?.access==="RESTRICTED"?<p className="muted">Configuration deployment history requires configurations.read permission.</p>:<>
       <div className="operations-detail-row"><span>Total deployments</span><strong>{operations.data.configuration?.deployments??0}</strong></div>
       {Object.entries(operations.data.configuration?.by_status||{}).map(([status,count])=><div className="operations-detail-row" key={"deployment-"+status}><span>{status.replaceAll("_"," ")}</span><strong>{count}</strong></div>)}
       {operations.data.configuration?.latest?<div className="operations-detail-row"><span><strong>Latest deployment · {operations.data.configuration.latest.device_id}</strong><small>{operations.data.configuration.latest.deployment_id} · {formatDate(operations.data.configuration.latest.created_at)}</small></span><StatusBadge value={operations.data.configuration.latest.status}/></div>:<p className="muted">No device configuration deployments are recorded in this scope.</p>}
       <p className="muted">A deployment result is historical evidence, not a live configuration-drift check.</p>
       <p className="muted">Source updated at {formatDate(operations.data.configuration?.source_updated_at)}</p>
      </>}
     </div>
     <div className="operations-detail-panel">
      <h3>Evidence inventory</h3>
      {operations.data.evidence?.access==="RESTRICTED"?<p className="muted">Evidence inventory requires evidence.read permission.</p>:<>
       <div className="operations-detail-row"><span>Telemetry artifacts</span><strong>{operations.data.evidence?.telemetry_artifacts??0}</strong></div>
       <div className="operations-detail-row"><span>Lab health snapshots</span><strong>{operations.data.evidence?.lab_health_snapshots??0}</strong></div>
        <small className="muted">Verified Wi-Fi telemetry points</small>
        {(operations.data.evidence?.wifi_metrics||[]).length?operations.data.evidence.wifi_metrics.map(metric=><div className="operations-detail-row" key={metric.metric+"-"+metric.interface}><span><strong>{metric.metric.replaceAll("_"," ")}</strong><small>{metric.interface} · {metric.environment_class||"Environment unknown"} · {formatDate(metric.captured_at)}</small><small>Mean {metric.mean_value} {metric.unit} · {metric.sample_count} samples · Run {metric.run_id}</small></span><strong>{metric.latest_value} {metric.unit}</strong></div>):<p className="muted">No integrity-verified numeric Wi-Fi telemetry points are available in this scope.</p>}
       <p className="muted">Only persisted, non-deleted artifact records are counted.</p>
       <p className="muted">Source updated at {formatDate(operations.data.evidence?.source_updated_at)}</p>
      </>}
     </div>
     <div className="operations-detail-panel">
      <h3>Network health</h3>
      <div className="operations-detail-row"><span>Provider health</span><StatusBadge value={operations.data.network_health?.provider_health||"UNKNOWN"}/></div>
      <div className="operations-detail-row"><span>Device reachability</span><StatusBadge value={operations.data.network_health?.device_reachability?.status||"UNAVAILABLE"}/></div>
      <p className="muted">{operations.data.network_health?.device_reachability?.reason}</p>
      <div className="operations-detail-row"><span>Configuration synchronization</span><StatusBadge value={operations.data.network_health?.configuration_sync?.status||"UNAVAILABLE"}/></div>
      <p className="muted">{operations.data.network_health?.configuration_sync?.reason}</p>
      <div className="operations-detail-row"><span>Infrastructure resources</span><StatusBadge value={operations.data.network_health?.infrastructure_resources?.status||"UNAVAILABLE"}/></div>
      <p className="muted">{operations.data.network_health?.infrastructure_resources?.reason}</p>
      <p className="muted">No live reachability, provider health, or infrastructure resource state is inferred from configuration metadata.</p>
     </div>
     <div className="operations-detail-panel">
      <h3>Action items</h3>
      <div className="operations-detail-row"><span>Failed or partial topology applies</span><strong>{operations.data.action_items?.topology_apply_failures??(operations.data.topology?.access==="RESTRICTED"?"Restricted":"0")}</strong></div>
      <div className="operations-detail-row"><span>Failed or partial configuration deployments</span><strong>{operations.data.action_items?.configuration_deployment_failures??(operations.data.configuration?.access==="RESTRICTED"?"Restricted":"0")}</strong></div>
      <div className="operations-detail-row"><span>Pipeline recovery required</span><strong>{operations.data.action_items?.pipeline_recovery_required??(operations.data.pipelines?.access==="RESTRICTED"?"Restricted":"0")}</strong></div>
      <div className="operations-detail-row"><span>Regressions</span><StatusBadge value={operations.data.action_items?.regressions?.status||"UNAVAILABLE"}/></div>
      <p className="muted">{operations.data.action_items?.regressions?.reason}</p>
      <div className="operations-detail-row"><span>Configuration drift</span><StatusBadge value={operations.data.action_items?.configuration_drift?.status||"UNAVAILABLE"}/></div>
      <p className="muted">{operations.data.action_items?.configuration_drift?.reason}</p>
      <div className="operations-detail-row"><span>Provider synchronization errors</span><StatusBadge value={operations.data.action_items?.provider_sync_errors?.status||"UNAVAILABLE"}/></div>
      <p className="muted">{operations.data.action_items?.provider_sync_errors?.reason}</p>
     </div>
      <div className="operations-detail-panel">
      <h3>Network performance</h3>
      <StatusBadge value={operations.data.performance?.access==="RESTRICTED"?"RESTRICTED":(operations.data.performance?.status||"UNAVAILABLE")}/>
      {operations.data.performance?.access==="RESTRICTED"?<p className="muted">Performance observations require performance.read permission.</p>:operations.data.performance?.metrics?.length?<div className="operations-metric-list">{operations.data.performance.metrics.slice(0,10).map(metric=><div className="operations-detail-row" key={metric.name+"-"+metric.unit}><span><strong>{metric.name.replaceAll("_"," ")}</strong><small>{metric.test_id} · {formatDate(metric.captured_at)}</small><small>Run {metric.run_id} · {metric.authoritative?"Authoritative":"Non-authoritative"}</small><small>Mean {metric.mean_value} {metric.unit} · {metric.sample_count} valid samples · range {metric.min_value}–{metric.max_value}</small></span><strong>{metric.value} {metric.unit}</strong></div>)}</div>:<p className="muted">{operations.data.performance?.reason||"No valid, timestamped performance sample is available."}</p>}
      {operations.data.performance?.access!=="RESTRICTED"?<p className="muted">Source updated at {formatDate(operations.data.performance?.source_updated_at)}</p>:null}
     </div>
    </div>
    <p className="readiness-footnote">Overview queried at {formatDate(operations.data.observed_at)}. Counts are persisted records, not a live provider/node health assertion.</p>
   </>:null}
  </Section>

  <Section title="Latest Runs" subtitle={projectId?(runs.loading&&!runs.data?"Loading recent Runs…":runs.error&&!runs.data?"Latest Run list unavailable":items.length+" displayed · "+total+" total persisted"):"Select a Project to inspect scoped Runs"} actions={<div className="panel-action-row"><Button variant="ghost" size="sm" disabled={!projectId} onClick={()=>runs.reload().catch(()=>{})}><RefreshCw size={14}/>Refresh</Button><Button variant="outline" size="sm" onClick={()=>navigate("/runs")}>View history<ArrowUpRight size={13}/></Button></div>}>
   {!projectId?<EmptyState title="No Project selected" message="Select a Project in the application header before viewing its persisted Runs."/>:null}
   {projectId&&runs.loading&&!runs.data?<LoadingState label="Loading Project Runs…"/>:null}
   {projectId&&runs.error?<ErrorState error={runs.error} onRetry={runs.reload}/>:null}
   {projectId&&runs.data?<DataTable caption="Eight most recent persisted validation Runs" rows={items} rowKey={row=>row.run_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(row.run_id))} columns={[
    {key:"display_id",label:"Run",render:row=><div className="run-table-identity"><strong>{row.display_id||row.run_id}</strong><span className="muted mono">{row.run_id}</span></div>},
    {key:"firmware_version",label:"Firmware"},
    {key:"lifecycle_status",label:"Lifecycle",render:row=><StatusBadge value={row.lifecycle_status}/>},
    {key:"business_outcome",label:"Outcome",render:row=><StatusBadge value={row.business_outcome}/>},
    {key:"environment_class",label:"Environment",render:row=>row.environment_class||"Not recorded"},
    {key:"created_at",label:"Created",render:row=>formatDate(row.created_at)}
   ]} emptyTitle="No Runs yet" emptyMessage="No persisted Runs are recorded for the selected Project/Lab scope."/>:null}
  </Section>
 </div>;
}
