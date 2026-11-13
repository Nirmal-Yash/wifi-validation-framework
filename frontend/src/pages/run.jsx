import React,{useState} from "react";
import {Activity,CheckCircle2,ClipboardList,FileText,GitCompare,LayoutDashboard,Settings,ShieldCheck,Wifi,XCircle} from "lucide-react";
import {api} from "../api";
import {Tabs,TabsContent,TabsList,TabsTrigger} from "@/components/ui/tabs";
import {navigate} from "../router";
import {useAsyncLoader,useMutation} from "../hooks";
import {formatBytes,formatDate,formatDuration,terminalStatuses} from "../utils";
import {canPerform} from "../permissions";
import {ArtifactLink,Button,ConfirmDialog,DataTable,EmptyState,ErrorState,InlineNotice,JsonPanel,KeyValueGrid,LoadingState,Section,StatCard,StatusBadge} from "../components/ui";
const tabs=[
 {id:"summary",label:"Summary",Icon:LayoutDashboard},
 {id:"tests",label:"Tests",Icon:ClipboardList},
 {id:"health",label:"Health",Icon:ShieldCheck},
 {id:"telemetry",label:"Telemetry",Icon:Wifi},
 {id:"artifacts",label:"Evidence",Icon:FileText},
 {id:"release-gate",label:"Release Gate",Icon:GitCompare},
 {id:"configuration",label:"Configuration",Icon:Settings},
];
export default function RunDetailPage({runId,user}){
 const[tab,setTab]=useState("summary"),[confirm,setConfirm]=useState(null),[baselineRunId,setBaselineRunId]=useState("");
 const runLoader=useAsyncLoader(()=>api.run(runId),[runId],{
  refreshMs:query=>terminalStatuses.has(query.state.data?.lifecycle_status)?false:3000,
  staleTime:1000,
 });
 const testsLoader=useAsyncLoader(()=>api.tests(runId),[runId],{
  refreshMs:()=>runLoader.data&&terminalStatuses.has(runLoader.data.lifecycle_status)?false:5000,
 });
 const healthLoader=useAsyncLoader(()=>api.healthForRun(runId),[runId],{enabled:tab==="health"||tab==="summary"});
 const telemetryLoader=useAsyncLoader(()=>api.telemetry(runId),[runId],{enabled:tab==="telemetry"});
 const artifactsLoader=useAsyncLoader(()=>api.artifacts({run_id:runId,limit:200}),[runId],{enabled:tab==="artifacts"||tab==="summary"});
 const baselineLoader=useAsyncLoader(()=>api.baselines(),[],{enabled:tab==="release-gate"});
 const releaseGateLoader=useAsyncLoader(()=>baselineRunId?api.releaseGate(runId,baselineRunId):Promise.resolve(null),[runId,baselineRunId],{enabled:tab==="release-gate"&&Boolean(baselineRunId)});
 const mutation=useMutation();
 if(runLoader.loading&&!runLoader.data)return<LoadingState label="Loading Run…"/>;
 if(runLoader.error&&!runLoader.data)return<ErrorState error={runLoader.error} onRetry={runLoader.reload}/>;
 const run=runLoader.data,tests=testsLoader.data?.items||[],health=healthLoader.data?.items||run.health||[],telemetry=telemetryLoader.data?.items||[],artifacts=artifactsLoader.data?.items||run.artifacts||[],counts=run.test_counts||{},canOperate=canPerform(user,"runs.execute"),isActive=!terminalStatuses.has(run.lifecycle_status);
 const statusCounts=tests.reduce((acc,test)=>{const status=String(test.status||"UNKNOWN").toUpperCase();acc[status]=(acc[status]||0)+1;return acc;},{});
 const passed=counts.pass??statusCounts.PASS??0,totalTests=counts.total??tests.length,blocked=counts.blocked??statusCounts.BLOCKED??0,unvalidated=counts.unvalidated??statusCounts.UNVALIDATED??0;
 const passPercent=totalTests?Math.min(100,(passed/totalTests)*100):0;
 const summaryItems=[
  {label:"Lifecycle",value:<StatusBadge value={run.lifecycle_status}/>},{label:"Business outcome",value:<StatusBadge value={run.business_outcome}/>},
  {label:"Project",value:run.project_id||"Unscoped legacy Run"},{label:"Firmware",value:run.firmware_version},{label:"Device",value:run.device_id},{label:"Lab",value:run.lab_id},{label:"Profile",value:run.validation_profile},
  {label:"Environment",value:run.environment_class},{label:"Environment health",value:<StatusBadge value={run.environment_health}/>},{label:"Failure class",value:<StatusBadge value={run.failure_class}/>},
  {label:"Created",value:formatDate(run.created_at)},{label:"Started",value:formatDate(run.started_at)},{label:"Completed",value:formatDate(run.completed_at)},
  {label:"Duration",value:formatDuration(run.started_at,run.completed_at)},{label:"Configuration hash",value:run.configuration_hash||"—"}
 ];
 const performAction=async action=>{try{if(action==="cancel")await mutation.run(()=>api.cancel(runId,"Cancelled from NetRegress UI"));if(action==="retry")await mutation.run(()=>api.retry(runId));setConfirm(null);await runLoader.reload();await testsLoader.reload();}catch{setConfirm(null);}};
 return<div className="page-stack">
  <div className="breadcrumb"><a href="/runs" onClick={e=>{e.preventDefault();navigate("/runs");}}>Runs</a><span>/</span><span>{run.display_id}</span></div>
  <div className="page-actions-row"><span className="context-caption mono">{run.run_id}</span><div className="button-row">{canOperate&&isActive?<Button variant="danger" onClick={()=>setConfirm("cancel")}>Cancel Run</Button>:null}{canOperate&&!isActive&&run.lifecycle_status!=="COMPLETED"?<Button onClick={()=>setConfirm("retry")}>Retry Run</Button>:null}</div></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">Operation accepted by the Runner API.</InlineNotice>:null}
  <div className="stat-grid"><StatCard label="Passed tests" value={passed+"/"+totalTests} hint="PASS outcomes / observed TestResults" icon={<CheckCircle2 size={17}/>} tone="success"/><StatCard label="Blocked" value={blocked} hint="Required tests blocked" icon={<XCircle size={17}/>} tone={blocked?"warning":"default"}/><StatCard label="Unvalidated" value={unvalidated} hint="Evidence or comparability incomplete" icon={<ShieldCheck size={17}/>} tone={unvalidated?"warning":"default"}/><StatCard label="Evidence artifacts" value={artifacts.length} hint="Registered records available in this view" icon={<FileText size={17}/>}/></div>
  <div className="run-progress-panel"><div className="row-between"><span>Observed test pass ratio</span><strong>{totalTests?Math.round(passPercent)+"%":"Not available"}</strong></div><div className="progress-track" role="progressbar" aria-label="Observed test pass ratio" aria-valuemin={0} aria-valuemax={100} aria-valuenow={passPercent}><span className={"progress-fill success progress-width-"+Math.round(passPercent)}/></div><p>Test pass ratio is descriptive only; it does not replace the persisted business outcome or release gate.</p></div>
  <Section title="Run context"><KeyValueGrid items={summaryItems}/></Section>
  <Section title="Attempt history" subtitle="All executions remain visible; the latest persisted attempt is authoritative for current results."><DataTable caption="Run attempt history" rows={run.attempts||[]} rowKey={item=>item.attempt_id} columns={[{key:"number",label:"Attempt"},{key:"attempt_id",label:"Attempt ID",render:item=><span className="mono">{item.attempt_id}</span>},{key:"started_at",label:"Started",render:item=>formatDate(item.started_at)},{key:"completed_at",label:"Completed",render:item=>formatDate(item.completed_at)},{key:"latest",label:"Current",render:item=>item.attempt_id===run.latest_attempt_id?<StatusBadge value="LATEST"/>:"—"}]} emptyTitle="No attempts" emptyMessage="No attempt history has been persisted for this Run."/></Section>
  <Tabs value={tab} onValueChange={setTab}><TabsList className="run-tabs" aria-label="Run detail sections">{tabs.map(({id,label,Icon})=><TabsTrigger key={id} value={id}><Icon size={14} aria-hidden="true"/>{label}</TabsTrigger>)}</TabsList>

  <TabsContent value="summary">
<div className="two-column"><Section title="Test summary"><DataTable rows={tests} rowKey={row=>row.test_result_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(runId)+"/tests/"+encodeURIComponent(row.test_result_id))} columns={[
   {key:"test_id",label:"Test",render:row=><><strong>{row.test_id}</strong><div className="muted mono">{row.node_id}</div></>},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},
   {key:"criticality",label:"Criticality"},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"error_reason",label:"Reason",render:row=>row.error_reason||"—"}
  ]} emptyTitle="No test results" emptyMessage="This Run has not persisted TestResults yet."/></Section><Section title="Health">{!health.length?<EmptyState title="No health evidence" message="No Lab Health snapshot is available for this Run."/>:<div className="health-stack">{health.map((item,index)=><div className="health-card" key={index}><div className="row-between"><strong>{item.snapshot?.phase||"Snapshot"}</strong><StatusBadge value={item.snapshot?.overall_status}/></div><span className="muted">{formatDate(item.snapshot?.completed_at)}</span></div>)}</div>}</Section></div>
</TabsContent>
<TabsContent value="tests">
<Section title="Test results" subtitle="Select a result for its execution contract, samples, evidence and failure semantics."><DataTable rows={tests} rowKey={row=>row.test_result_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(runId)+"/tests/"+encodeURIComponent(row.test_result_id))} columns={[
   {key:"test_id",label:"Test"},{key:"test_version",label:"Version"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"severity",label:"Severity"},{key:"criticality",label:"Criticality"},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"completed_at",label:"Completed",render:row=>formatDate(row.completed_at)}
  ]} emptyTitle="No TestResults" emptyMessage="The selected Run has no persisted test results."/></Section>
</TabsContent>
<TabsContent value="health">
<Section title="Lab Health evidence" subtitle="Read-only evidence. This screen never triggers repair.">{!health.length?<EmptyState title="No health evidence" message="No health snapshots are persisted for this Run."/>:health.map((item,index)=><div className="panel nested" key={index}><div className="row-between"><div><h3>{item.snapshot?.phase||"Snapshot"}</h3><p className="muted">{formatDate(item.snapshot?.completed_at)}</p></div><StatusBadge value={item.snapshot?.overall_status}/></div><DataTable rows={item.snapshot?.observations||[]} rowKey={(row,i)=>row.component+"-"+i} columns={[
   {key:"component",label:"Component"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"required",label:"Required",render:row=>row.required?"Yes":"No"},{key:"summary",label:"Summary"},{key:"observed_at",label:"Observed",render:row=>formatDate(row.observed_at)}
  ]} emptyTitle="No observations" emptyMessage="This snapshot did not persist component observations."/></div>)}</Section>
</TabsContent>
<TabsContent value="telemetry">
<Section title="WiFi telemetry" subtitle="Environment class is preserved at snapshot and point level. Virtual WiFi is not RF certification.">{!telemetry.length?<EmptyState title="No telemetry evidence" message="No telemetry artifacts are persisted for this Run."/>:telemetry.map((item,index)=><div className="panel nested" key={index}><div className="row-between"><div><h3>{item.snapshot?.environment_class||"Unknown environment"}</h3><p className="muted">{formatDate(item.snapshot?.captured_at)} · {item.snapshot?.interface||"interface unavailable"}</p></div><StatusBadge value={item.snapshot?.environment_class}/></div><DataTable rows={item.snapshot?.points||[]} rowKey={(row,i)=>(row.metric||"metric")+"-"+i} columns={[
   {key:"metric",label:"Metric"},{key:"value",label:"Value",render:row=>row.value+" "+(row.unit||"")},{key:"source",label:"Source"},{key:"captured_at",label:"Captured",render:row=>formatDate(row.captured_at)},{key:"environment_class",label:"Environment"}
  ]} emptyTitle="No telemetry points" emptyMessage="This snapshot did not persist telemetry points."/></div>)}</Section>
</TabsContent>
<TabsContent value="artifacts">
<Section title="Evidence artifacts" subtitle="Only registered, integrity-verified artifacts can be interpreted or downloaded."><DataTable rows={artifacts} rowKey={row=>row.artifact_id} columns={[
   {key:"display_name",label:"Artifact",render:row=><><strong>{row.display_name}</strong><div className="muted mono">{row.artifact_id}</div></>},{key:"artifact_type",label:"Type"},{key:"size_bytes",label:"Size",render:row=>formatBytes(row.size_bytes)},{key:"sha256",label:"SHA-256",render:row=><code className="hash">{row.sha256}</code>},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"downloadable",label:"Action",render:row=><ArtifactLink artifact={row}/>}
  ]} emptyTitle="No artifacts" emptyMessage="No evidence artifacts are currently associated with this Run."/></Section>
</TabsContent>
<TabsContent value="release-gate">
<Section title="Automated release decision" subtitle="Select an explicit promoted baseline. The backend evaluates persisted Run state, evidence and regression policy.">
 <div className="filter-grid"><div className="field"><label className="field-label" htmlFor="release-baseline">Baseline Run</label><select id="release-baseline" value={baselineRunId} onChange={event=>setBaselineRunId(event.target.value)}><option value="">Choose a baseline Run…</option>{(baselineLoader.data?.items||[]).map(item=><option key={item.baseline_id} value={item.baseline_run_id}>{item.name} · {item.baseline_run_id}</option>)}</select></div></div>
 {baselineLoader.loading?<InlineNotice>Loading promoted baselines…</InlineNotice>:null}
 {baselineLoader.error?<InlineNotice tone="danger">{baselineLoader.error.message}</InlineNotice>:null}
 {releaseGateLoader.loading?<InlineNotice>Evaluating release policy…</InlineNotice>:null}
 {releaseGateLoader.error?<InlineNotice tone="danger">{releaseGateLoader.error.message}</InlineNotice>:null}
 {releaseGateLoader.data?<><div className="row-between"><div><strong>Decision</strong><p>{releaseGateLoader.data.summary}</p></div><StatusBadge value={releaseGateLoader.data.status}/></div><InlineNotice tone={releaseGateLoader.data.accepted?"success":"danger"}>{releaseGateLoader.data.comparability_reason||"Comparability was not established."}</InlineNotice><DataTable caption="Release gate issues" rows={releaseGateLoader.data.issues||[]} rowKey={(item,index)=>item.code+"-"+(item.test_id||index)} columns={[{key:"code",label:"Issue"},{key:"test_id",label:"Test"},{key:"message",label:"Explanation"}]} emptyTitle="No release blockers" emptyMessage="The automated policy found no blocking issues for this Run and baseline."/><Section title="Audited waiver exceptions" subtitle="Every waived blocker is tied to its exact waiver and audit reference."><DataTable caption="Applied release waivers" rows={releaseGateLoader.data.waived_issues||[]} rowKey={item=>item.waiver_id+"-"+item.issue.code} columns={[{key:"issue_code",label:"Issue",render:item=>item.issue.code},{key:"test_id",label:"Test",render:item=>item.issue.test_id||"—"},{key:"waiver_id",label:"Waiver ID"},{key:"audit_reference",label:"Audit reference"},{key:"message",label:"Waived explanation",render:item=>item.issue.message}]} emptyTitle="No waiver exceptions applied" emptyMessage="This decision did not rely on an active waiver."/></Section></>:null}
 <InlineNotice tone="warning">An ACCEPT result is an automated policy decision, not human release authorization or protected REAL_LAB / physical-device certification.</InlineNotice>
</Section>
</TabsContent>
<TabsContent value="configuration">
<div className="two-column"><Section title="Resolved configuration"><JsonPanel value={run.config_snapshot?.resolved_config||{}}/></Section><Section title="Environment snapshot"><JsonPanel value={run.environment||{}}/></Section></div>
</TabsContent>
  </Tabs>
  <ConfirmDialog open={Boolean(confirm)} title={confirm==="cancel"?"Cancel this Run?":"Retry this Run?"} message={confirm==="cancel"?"Cancellation is persisted as an operator action and the Runner process is asked to stop. Do not cancel a Run unless you intend to terminate the current execution.":"Retry creates a new Runner process using the source Run selection. Review the new Run after it is accepted."} confirmLabel={confirm==="cancel"?"Cancel Run":"Retry Run"} danger={confirm==="cancel"} loading={mutation.loading} onCancel={()=>setConfirm(null)} onConfirm={()=>performAction(confirm)}/>
 </div>;
}