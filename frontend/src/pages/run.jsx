import React,{useEffect,useMemo,useState} from "react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader,useMutation} from "../hooks";
import {canExecute,formatDate,formatDuration,terminalStatuses} from "../utils";
import {ArtifactLink,Button,ConfirmDialog,DataTable,EmptyState,ErrorState,InlineNotice,JsonPanel,KeyValueGrid,LoadingState,Section,StatusBadge} from "../components/ui";
const tabs=["summary","tests","health","telemetry","artifacts","configuration"];
export default function RunDetailPage({runId,user}){
 const[tab,setTab]=useState("summary"),[confirm,setConfirm]=useState(null);
 const runLoader=useAsyncLoader(()=>api.run(runId),[runId],{refreshMs:3000});
 const testsLoader=useAsyncLoader(()=>api.tests(runId),[runId],{refreshMs:5000});
 const healthLoader=useAsyncLoader(()=>api.healthForRun(runId),[runId],{enabled:tab==="health"||tab==="summary"});
 const telemetryLoader=useAsyncLoader(()=>api.telemetry(runId),[runId],{enabled:tab==="telemetry"});
 const artifactsLoader=useAsyncLoader(()=>api.artifacts({run_id:runId,limit:200}),[runId],{enabled:tab==="artifacts"||tab==="summary"});
 const mutation=useMutation();
 useEffect(()=>{if(!runLoader.data||terminalStatuses.has(runLoader.data.lifecycle_status))return;const timer=window.setInterval(()=>{runLoader.reload().catch(()=>{});testsLoader.reload().catch(()=>{});},3000);return()=>window.clearInterval(timer);},[runLoader.data?.lifecycle_status,runId]);
 if(runLoader.loading&&!runLoader.data)return<LoadingState label="Loading Run…"/>;
 if(runLoader.error&&!runLoader.data)return<ErrorState error={runLoader.error} onRetry={runLoader.reload}/>;
 const run=runLoader.data,tests=testsLoader.data?.items||[],health=healthLoader.data?.items||run.health||[],telemetry=telemetryLoader.data?.items||[],artifacts=artifactsLoader.data?.items||run.artifacts||[],counts=run.test_counts||{},canOperate=canExecute(user.role),isActive=!terminalStatuses.has(run.lifecycle_status);
 const summaryItems=useMemo(()=>[
  {label:"Lifecycle",value:<StatusBadge value={run.lifecycle_status}/>},{label:"Business outcome",value:<StatusBadge value={run.business_outcome}/>},
  {label:"Firmware",value:run.firmware_version},{label:"Device",value:run.device_id},{label:"Lab",value:run.lab_id},{label:"Profile",value:run.validation_profile},
  {label:"Environment",value:run.environment_class},{label:"Environment health",value:<StatusBadge value={run.environment_health}/>},{label:"Failure class",value:<StatusBadge value={run.failure_class}/>},
  {label:"Created",value:formatDate(run.created_at)},{label:"Started",value:formatDate(run.started_at)},{label:"Completed",value:formatDate(run.completed_at)},
  {label:"Duration",value:formatDuration(run.started_at,run.completed_at)},{label:"Configuration hash",value:run.configuration_hash||"—"}
 ],[run]);
 const performAction=async action=>{try{if(action==="cancel")await mutation.run(()=>api.cancel(runId,"Cancelled from NetRegress UI"));if(action==="retry")await mutation.run(()=>api.retry(runId));setConfirm(null);await runLoader.reload();await testsLoader.reload();}catch{}};
 return<div className="page-stack">
  <div className="breadcrumb"><a href="/runs" onClick={e=>{e.preventDefault();navigate("/runs");}}>Runs</a><span>/</span><span>{run.display_id}</span></div>
  <div className="page-title-row"><div><div className="eyebrow">Run detail</div><h2>{run.display_id}</h2><p className="muted mono">{run.run_id}</p></div><div className="button-row">{canOperate&&isActive?<Button variant="danger" onClick={()=>setConfirm("cancel")}>Cancel Run</Button>:null}{canOperate&&!isActive&&run.lifecycle_status!=="COMPLETED"?<Button onClick={()=>setConfirm("retry")}>Retry Run</Button>:null}</div></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">Operation accepted by the Runner API.</InlineNotice>:null}
  <div className="stat-grid"><div className="stat-card"><div className="stat-label">Tests</div><div className="stat-value">{counts.pass||0}/{counts.total||0}</div><div className="stat-hint">Passed / observed</div></div><div className="stat-card"><div className="stat-label">Blocked</div><div className="stat-value">{counts.blocked||0}</div><div className="stat-hint">Required tests blocked</div></div><div className="stat-card"><div className="stat-label">Unvalidated</div><div className="stat-value">{counts.unvalidated||0}</div><div className="stat-hint">Evidence/comparability incomplete</div></div><div className="stat-card"><div className="stat-label">Artifacts</div><div className="stat-value">{artifacts.length}</div><div className="stat-hint">Persisted evidence records</div></div></div>
  <Section title="Run context"><KeyValueGrid items={summaryItems}/></Section>
  <div className="tab-bar" role="tablist" aria-label="Run detail sections">{tabs.map(value=><button key={value} className={"tab-button "+(tab===value?"active":"")} onClick={()=>setTab(value)} role="tab" aria-selected={tab===value}>{value}</button>)}</div>

  {tab==="summary"?<div className="two-column"><Section title="Test summary"><DataTable rows={tests} rowKey={row=>row.test_result_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(runId)+"/tests/"+encodeURIComponent(row.test_result_id))} columns={[
   {key:"test_id",label:"Test",render:row=><><strong>{row.test_id}</strong><div className="muted mono">{row.node_id}</div></>},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},
   {key:"criticality",label:"Criticality"},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"error_reason",label:"Reason",render:row=>row.error_reason||"—"}
  ]} emptyTitle="No test results" emptyMessage="This Run has not persisted TestResults yet."/></Section><Section title="Health">{!health.length?<EmptyState title="No health evidence" message="No Lab Health snapshot is available for this Run."/>:<div className="health-stack">{health.map((item,index)=><div className="health-card" key={index}><div className="row-between"><strong>{item.snapshot?.phase||"Snapshot"}</strong><StatusBadge value={item.snapshot?.overall_status}/></div><span className="muted">{formatDate(item.snapshot?.completed_at)}</span></div>)}</div>}</Section></div>:null}

  {tab==="tests"?<Section title="Test results" subtitle="Select a result for its execution contract, samples, evidence and failure semantics."><DataTable rows={tests} rowKey={row=>row.test_result_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(runId)+"/tests/"+encodeURIComponent(row.test_result_id))} columns={[
   {key:"test_id",label:"Test"},{key:"test_version",label:"Version"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"severity",label:"Severity"},{key:"criticality",label:"Criticality"},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"completed_at",label:"Completed",render:row=>formatDate(row.completed_at)}
  ]} emptyTitle="No TestResults" emptyMessage="The selected Run has no persisted test results."/></Section>:null}

  {tab==="health"?<Section title="Lab Health evidence" subtitle="Read-only evidence. This screen never triggers repair.">{!health.length?<EmptyState title="No health evidence" message="No health snapshots are persisted for this Run."/>:health.map((item,index)=><div className="panel nested" key={index}><div className="row-between"><div><h3>{item.snapshot?.phase||"Snapshot"}</h3><p className="muted">{formatDate(item.snapshot?.completed_at)}</p></div><StatusBadge value={item.snapshot?.overall_status}/></div><DataTable rows={item.snapshot?.observations||[]} rowKey={(row,i)=>row.component+"-"+i} columns={[
   {key:"component",label:"Component"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"required",label:"Required",render:row=>row.required?"Yes":"No"},{key:"summary",label:"Summary"},{key:"observed_at",label:"Observed",render:row=>formatDate(row.observed_at)}
  ]} emptyTitle="No observations" emptyMessage="This snapshot did not persist component observations."/></div>)}</Section>:null}

  {tab==="telemetry"?<Section title="WiFi telemetry" subtitle="Environment class is preserved at snapshot and point level. Virtual WiFi is not RF certification.">{!telemetry.length?<EmptyState title="No telemetry evidence" message="No telemetry artifacts are persisted for this Run."/>:telemetry.map((item,index)=><div className="panel nested" key={index}><div className="row-between"><div><h3>{item.snapshot?.environment_class||"Unknown environment"}</h3><p className="muted">{formatDate(item.snapshot?.captured_at)} · {item.snapshot?.interface||"interface unavailable"}</p></div><StatusBadge value={item.snapshot?.environment_class}/></div><DataTable rows={item.snapshot?.points||[]} rowKey={(row,i)=>(row.metric||"metric")+"-"+i} columns={[
   {key:"metric",label:"Metric"},{key:"value",label:"Value",render:row=>row.value+" "+(row.unit||"")},{key:"source",label:"Source"},{key:"captured_at",label:"Captured",render:row=>formatDate(row.captured_at)},{key:"environment_class",label:"Environment"}
  ]} emptyTitle="No telemetry points" emptyMessage="This snapshot did not persist telemetry points."/></div>)}</Section>:null}

  {tab==="artifacts"?<Section title="Evidence artifacts" subtitle="Only registered, integrity-verified artifacts can be interpreted or downloaded."><DataTable rows={artifacts} rowKey={row=>row.artifact_id} columns={[
   {key:"display_name",label:"Artifact",render:row=><><strong>{row.display_name}</strong><div className="muted mono">{row.artifact_id}</div></>},{key:"artifact_type",label:"Type"},{key:"size_bytes",label:"Size",render:row=>row.size_bytes+" bytes"},{key:"sha256",label:"SHA-256",render:row=><code className="hash">{row.sha256}</code>},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"downloadable",label:"Action",render:row=><ArtifactLink artifact={row}/>}
  ]} emptyTitle="No artifacts" emptyMessage="No evidence artifacts are currently associated with this Run."/></Section>:null}
  {tab==="configuration"?<div className="two-column"><Section title="Resolved configuration"><JsonPanel value={run.config_snapshot?.resolved_config||{}}/></Section><Section title="Environment snapshot"><JsonPanel value={run.environment||{}}/></Section></div>:null}
  <ConfirmDialog open={Boolean(confirm)} title={confirm==="cancel"?"Cancel this Run?":"Retry this Run?"} message={confirm==="cancel"?"Cancellation is persisted as an operator action and the Runner process is asked to stop. Do not cancel a Run unless you intend to terminate the current execution.":"Retry creates a new Runner process using the source Run selection. Review the new Run after it is accepted."} confirmLabel={confirm==="cancel"?"Cancel Run":"Retry Run"} danger={confirm==="cancel"} loading={mutation.loading} onCancel={()=>setConfirm(null)} onConfirm={()=>performAction(confirm)}/>
 </div>;
}