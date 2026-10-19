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
import {canExecute} from "../utils";

export default function DashboardPage({user}){
 const runs=useAsyncLoader(()=>api.runs({limit:8}),[],{refreshMs:10000});
 const readiness=useAsyncLoader(()=>api.readiness(),[],{refreshMs:30000});
 if(runs.loading&&!runs.data)return <LoadingState label="Loading Runner overview…"/>;
 if(runs.error&&!runs.data)return <ErrorState error={runs.error} onRetry={runs.reload}/>;

 const items=runs.data?.items||[];
 const summary=summarizeRunOutcomes(items);
 const total=runs.data?.total??0;
 const displayedOutcomes=summary.validated+summary.validatedWithWarnings+summary.rejected+summary.unvalidated;
 const lastRun=items[0];

 return <div className="page-stack dashboard-page">
  <section className="dashboard-hero" aria-labelledby="dashboard-title">
   <div className="dashboard-hero-copy">
    <div className="dashboard-hero-kicker"><span className="hero-tag"><Activity size={13} aria-hidden="true"/>RUNNER OVERVIEW</span><span className="hero-refresh"><span className="hero-live-dot" aria-hidden="true"/>Auto-refresh every 10 seconds</span></div>
    <h2 id="dashboard-title">Validation you can trust.</h2>
    <p>Track execution, inspect evidence, and understand release outcomes from one place. A successful test process alone is not a validated release.</p>
    <div className="hero-metadata"><span><Database size={14} aria-hidden="true"/>{total.toLocaleString()} persisted Runs</span><span><Clock3 size={14} aria-hidden="true"/>Last activity {lastRun?formatDate(lastRun.created_at):"not recorded"}</span></div>
   </div>
   <div className="dashboard-hero-actions">
    {canExecute(user?.role)?<Button onClick={()=>navigate("/runs?launch=1")}><Play size={15} aria-hidden="true"/>Start a Run<ArrowUpRight size={14} aria-hidden="true"/></Button>:null}
    <Button variant="outline" onClick={()=>navigate("/runs")}>Run history<ArrowUpRight size={14} aria-hidden="true"/></Button>
    <Button variant="ghost" onClick={()=>navigate("/artifacts")}><FileText size={15} aria-hidden="true"/>Evidence</Button>
   </div>
  </section>

  <div className="section-intro"><div><h2>At a glance</h2><p>All-time Run volume alongside the latest eight Run outcomes.</p></div><div className="section-intro-meta">Updated {new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}</div></div>
  <div className="stat-grid">
   <StatCard label="Total Runs" value={total.toLocaleString()} hint="All persisted Runs" icon={<Database size={17}/>} />
   <StatCard label="Active Runs" value={summary.active} hint="From latest 8 only" icon={<Activity size={17}/>} tone={summary.active?"info":"default"}/>
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

  <Section title="Latest Runs" subtitle={items.length+" displayed · "+total+" total persisted"} actions={<div className="panel-action-row"><Button variant="ghost" size="sm" onClick={()=>runs.reload().catch(()=>{})}><RefreshCw size={14}/>Refresh</Button><Button variant="outline" size="sm" onClick={()=>navigate("/runs")}>View history<ArrowUpRight size={13}/></Button></div>}>
   <DataTable caption="Eight most recent persisted validation Runs" rows={items} rowKey={row=>row.run_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(row.run_id))} columns={[
    {key:"display_id",label:"Run",render:row=><div className="run-table-identity"><strong>{row.display_id||row.run_id}</strong><span className="muted mono">{row.run_id}</span></div>},
    {key:"firmware_version",label:"Firmware"},
    {key:"lifecycle_status",label:"Lifecycle",render:row=><StatusBadge value={row.lifecycle_status}/>},
    {key:"business_outcome",label:"Outcome",render:row=><StatusBadge value={row.business_outcome}/>},
    {key:"environment_class",label:"Environment",render:row=>row.environment_class||"Not recorded"},
    {key:"created_at",label:"Created",render:row=>formatDate(row.created_at)}
   ]} emptyTitle="No Runs yet" emptyMessage="Launch a Run from Run history to populate the overview."/>
  </Section>
 </div>;
}
