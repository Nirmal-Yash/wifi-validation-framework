import React from "react";
import {ArrowLeft,Activity,FileText,ShieldCheck,Timer} from "lucide-react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader} from "../hooks";
import {formatDate,validSamples} from "../utils";
import {ArtifactLink,Button,DataTable,EmptyState,ErrorState,JsonPanel,KeyValueGrid,LoadingState,MetricSampleTable,Section,StatCard,StatusBadge} from "../components/ui";

export default function TestDetailPage({runId,testResultId}){
 const loader=useAsyncLoader(()=>api.test(runId,testResultId),[runId,testResultId]);
 if(loader.loading&&!loader.data)return <LoadingState label="Loading TestResult evidence…"/>;
 if(loader.error&&!loader.data)return <ErrorState error={loader.error} onRetry={loader.reload}/>;
 const test=loader.data,definition=test.definition||{},metrics=test.metrics||[];
 const sampleCount=metrics.reduce((sum,metric)=>sum+validSamples(metric.samples).length,0);
 return <div className="page-stack">
  <div className="breadcrumb"><a href={"/runs/"+encodeURIComponent(runId)} onClick={event=>{event.preventDefault();navigate("/runs/"+encodeURIComponent(runId));}}>Run</a><span>/</span><span>{test.test_id}</span></div>
  <div className="page-title-row"><div><div className="eyebrow">Evidence / Test execution</div><h2>{test.test_id}</h2><p className="muted mono">{test.test_result_id}</p></div><div className="button-row"><StatusBadge value={test.status}/><Button variant="outline" size="sm" onClick={()=>navigate("/runs/"+encodeURIComponent(runId))}><ArrowLeft size={14}/>Back to Run</Button></div></div>
  <div className="stat-grid">
   <StatCard label="Functional status" value={<StatusBadge value={test.status}/>} hint="Persisted TestResult status" icon={<Activity size={17}/>}/>
   <StatCard label="Evidence state" value={<StatusBadge value={test.evidence_state}/>} hint="Evidence contract" icon={<ShieldCheck size={17}/>}/>
   <StatCard label="Test version" value={test.test_version||"Not recorded"} hint="Resolved registry definition" icon={<FileText size={17}/>}/>
   <StatCard label="Valid samples" value={sampleCount} hint="Valid, numeric, non-warm-up measurements" icon={<Timer size={17}/>} tone="success"/>
  </div>
  <Section title="Execution contract" subtitle="The persisted TestRegistry definition is authoritative for what ran.">
   <KeyValueGrid items={[
    {label:"Category",value:definition.category},{label:"Protocol",value:definition.protocol},{label:"Severity",value:definition.severity},{label:"Criticality",value:definition.criticality},
    {label:"Direction",value:definition.direction},{label:"Destructive",value:definition.destructive?"Yes":"No"},
    {label:"Estimated duration",value:definition.estimated_duration_sec?definition.estimated_duration_sec+"s":"Not recorded"},
    {label:"Node ID",value:definition.node_id||test.node_id}
   ]}/>
   <div className="pill-list">{(definition.requires||[]).map(item=><span className="pill" key={item}>{item}</span>)}{(definition.capabilities||[]).map(item=><span className="pill" key={item}>{item}</span>)}</div>
  </Section>
  <Section title="Metrics and raw samples" subtitle="All recorded samples remain visible. Only explicitly valid, finite, non-warm-up samples contribute to the mean.">
   {metrics.length?metrics.map(metric=><div className="nested-block" key={metric.name}>
    <div className="row-between"><div><h3>{metric.name}</h3><p className="muted">{metric.unit||"Unit not recorded"} · {metric.authoritative===false?"Context only":"Authoritative metric"}</p></div><StatusBadge value={metric.authoritative===false?"CONTEXT":"AUTHORITATIVE"}/></div>
    <MetricSampleTable metric={metric}/>
   </div>):<EmptyState title="No metrics recorded" message="This TestResult did not persist metric samples."/>}
  </Section>
  <div className="two-column">
   <Section title="Failure semantics" subtitle="Explanation recorded by the Runner">
    <div className="stack">
     <div><span className="muted">Functional status</span><div><StatusBadge value={test.status}/></div></div>
     <div><span className="muted">Failure reason</span><p>{test.error_reason||"No failure reason was recorded."}</p></div>
     <div><span className="muted">Started</span><p>{formatDate(test.started_at)}</p></div>
     <div><span className="muted">Completed</span><p>{formatDate(test.completed_at)}</p></div>
    </div>
   </Section>
   <Section title="Test-scoped evidence" subtitle="Only registered evidence is available for inspection.">
    <DataTable caption="Evidence registered against this TestResult" rows={test.artifacts||[]} rowKey={row=>row.artifact_id} columns={[
     {key:"display_name",label:"Artifact"},{key:"artifact_type",label:"Type"},
     {key:"evidence_state",label:"State",render:row=><StatusBadge value={row.evidence_state}/>},
     {key:"downloadable",label:"Action",render:row=><ArtifactLink artifact={row}/>}
    ]} emptyTitle="No test-scoped artifacts" emptyMessage="No artifacts are attached directly to this TestResult."/>
   </Section>
  </div>
  <Section title="Registry definition details" subtitle="Collapsed by default to keep the execution summary readable."><JsonPanel value={definition}/></Section>
 </div>;
}
