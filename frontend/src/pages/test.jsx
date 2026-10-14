import React from "react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader} from "../hooks";
import {formatDate,validSamples} from "../utils";
import {ArtifactLink,DataTable,EmptyState,ErrorState,KeyValueGrid,LoadingState,MetricSampleTable,Section,StatusBadge} from "../components/ui";
export default function TestDetailPage({runId,testResultId}){
 const loader=useAsyncLoader(()=>api.test(runId,testResultId),[runId,testResultId]);
 if(loader.loading&&!loader.data)return<LoadingState label="Loading TestResult…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 const test=loader.data,definition=test.definition||{},metricSamples=(test.metrics||[]).flatMap(metric=>validSamples(metric.samples).map(sample=>Number(sample.value)));
 return<div className="page-stack">
  <div className="breadcrumb"><a href={"/runs/"+encodeURIComponent(runId)} onClick={e=>{e.preventDefault();navigate("/runs/"+encodeURIComponent(runId));}}>Run</a><span>/</span><span>{test.test_id}</span></div>
  <div className="page-title-row"><div><div className="eyebrow">Test detail</div><h2>{test.test_id}</h2><p className="muted mono">{test.test_result_id}</p></div><StatusBadge value={test.status}/></div>
  <div className="stat-grid"><div className="stat-card"><div className="stat-label">Evidence</div><div className="stat-value"><StatusBadge value={test.evidence_state}/></div></div><div className="stat-card"><div className="stat-label">Test version</div><div className="stat-value">{test.test_version}</div></div><div className="stat-card"><div className="stat-label">Criticality</div><div className="stat-value">{test.criticality}</div></div><div className="stat-card"><div className="stat-label">Valid samples</div><div className="stat-value">{metricSamples.length}</div></div></div>
  <Section title="Execution contract" subtitle="The persisted TestRegistry definition is authoritative for what ran."><KeyValueGrid items={[
   {label:"Category",value:definition.category},{label:"Protocol",value:definition.protocol},{label:"Severity",value:definition.severity},{label:"Criticality",value:definition.criticality},{label:"Direction",value:definition.direction},{label:"Destructive",value:definition.destructive?"Yes":"No"},{label:"Estimated duration",value:definition.estimated_duration_sec?definition.estimated_duration_sec+"s":"—"},{label:"Node ID",value:definition.node_id||test.node_id}
  ]}/><div className="pill-list">{(definition.requires||[]).map(item=><span className="pill" key={item}>{item}</span>)}{(definition.capabilities||[]).map(item=><span className="pill" key={item}>{item}</span>)}</div></Section>
  <Section title="Metrics and raw samples">{(test.metrics||[]).length?test.metrics.map(metric=><div className="nested-block" key={metric.name}><div className="row-between"><h3>{metric.name}</h3><span className="muted">{metric.unit} · {metric.authoritative?"authoritative":"context"}</span></div><MetricSampleTable metric={metric}/></div>):<EmptyState title="No metrics" message="This TestResult did not persist metrics."/>}</Section>
  <div className="two-column"><Section title="Failure semantics"><div className="stack"><div><span className="muted">Functional status</span><div><StatusBadge value={test.status}/></div></div><div><span className="muted">Failure reason</span><p>{test.error_reason||"No failure reason recorded."}</p></div><div><span className="muted">Started</span><p>{formatDate(test.started_at)}</p></div><div><span className="muted">Completed</span><p>{formatDate(test.completed_at)}</p></div></div></Section><Section title="Evidence"><DataTable rows={test.artifacts||[]} rowKey={row=>row.artifact_id} columns={[
   {key:"display_name",label:"Artifact"},{key:"artifact_type",label:"Type"},{key:"evidence_state",label:"State",render:row=><StatusBadge value={row.evidence_state}/>},{key:"downloadable",label:"Action",render:row=><ArtifactLink artifact={row}/>}
  ]} emptyTitle="No test-scoped artifacts" emptyMessage="No artifacts are attached directly to this TestResult."/></Section></div>
  <Section title="Definition details"><pre className="json-panel">{JSON.stringify(definition,null,2)}</pre></Section>
 </div>;
}