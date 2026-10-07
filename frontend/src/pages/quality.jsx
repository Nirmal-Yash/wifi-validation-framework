import React,{useState} from "react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader} from "../hooks";
import {formatDate,metricMean,validSamples} from "../utils";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LineChart,LoadingState,Section,StatusBadge} from "../components/ui";
const defaultTests=["wifi.latency.threshold","wifi.packet_loss.threshold","wifi.throughput.minimum","wifi.ping.success"];
export function RegressionPage(){
 const[baseline,setBaseline]=useState(""),[current,setCurrent]=useState(""),[search,setSearch]=useState(""),[classification,setClassification]=useState(""),[submitted,setSubmitted]=useState(null);
 const loader=useAsyncLoader(()=>submitted?api.regressions(submitted.baseline,submitted.current):Promise.resolve(null),[submitted?.baseline,submitted?.current],{enabled:Boolean(submitted)});
 const assessments=(loader.data?.assessments||[]).filter(item=>{const term=search.trim().toLowerCase();return(!term||(item.test_id||"").toLowerCase().includes(term)||(item.reason||"").toLowerCase().includes(term))&&(!classification||item.classification===classification);});
 return<div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Analyze</div><h2>Regression intelligence</h2><p className="muted">Explicit Run-to-Run comparison. Comparability and environment class are displayed before interpreting regressions.</p></div></div>
  <Section title="Compare Runs"><div className="filter-grid"><Field label="Baseline Run ID"><input value={baseline} onChange={e=>setBaseline(e.target.value)} placeholder="Baseline Run ID"/></Field><Field label="Current Run ID"><input value={current} onChange={e=>setCurrent(e.target.value)} placeholder="Current Run ID"/></Field><div className="filter-actions"><Button onClick={()=>setSubmitted({baseline:baseline.trim(),current:current.trim()})} disabled={!baseline.trim()||!current.trim()}>Compare</Button></div></div>{loader.error?<InlineNotice tone="danger">{loader.error.message}</InlineNotice>:null}</Section>
  {loader.loading&&!loader.data?<LoadingState label="Comparing Runs…"/>:null}
  {loader.data?<><div className="stat-grid"><Stat label="Comparability" value={<StatusBadge value={loader.data.comparability}/>}/><Stat label="Baseline environment" value={loader.data.environment?.baseline||"—"}/><Stat label="Current environment" value={loader.data.environment?.current||"—"}/><Stat label="Assessments" value={loader.data.assessments?.length||0}/></div><InlineNotice tone={loader.data.comparability==="COMPARABLE"?"success":"warning"}>{loader.data.reason}</InlineNotice>
   <Section title="Filters"><div className="filter-grid"><Field label="Search"><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="test or reason"/></Field><Field label="Classification"><select value={classification} onChange={e=>setClassification(e.target.value)}><option value="">All</option><option>REGRESSION</option><option>SOFT_REGRESSION</option><option>FIXED</option><option>IMPROVED</option><option>NO_BASELINE</option><option>UNVALIDATED</option></select></Field></div></Section>
   <Section title="Assessment results"><DataTable rows={assessments} rowKey={row=>row.test_id} columns={[
    {key:"test_id",label:"Test"},{key:"baseline_status",label:"Baseline",render:row=><StatusBadge value={row.baseline_status}/>},{key:"current_status",label:"Current",render:row=><StatusBadge value={row.current_status}/>},{key:"classification",label:"Classification",render:row=><StatusBadge value={row.classification}/>},{key:"dimensions",label:"Dimensions",render:row=>row.dimensions?.join(", ")||"—"},{key:"reason",label:"Reason"},
    {key:"current_test_result_id",label:"Detail",render:row=>row.current_test_result_id?<a className="text-link" href={"/runs/"+encodeURIComponent(loader.data.current_run_id)+"/tests/"+encodeURIComponent(row.current_test_result_id)} onClick={e=>{e.preventDefault();navigate("/runs/"+encodeURIComponent(loader.data.current_run_id)+"/tests/"+encodeURIComponent(row.current_test_result_id));}}>Open</a>:"—"}
   ]} emptyTitle="No matching assessments" emptyMessage="Adjust the classification or search filters."/></Section>
  </>:null}
 </div>;
}
function Stat({label,value}){return<div className="stat-card"><div className="stat-label">{label}</div><div className="stat-value">{value}</div></div>;}
export function PerformancePage(){
 const[testId,setTestId]=useState(defaultTests[0]),[submitted,setSubmitted]=useState(defaultTests[0]);
 const loader=useAsyncLoader(()=>api.metricsHistory(submitted),[submitted]);
 const rows=loader.data?.items||[],chartPoints=rows.flatMap(row=>{const value=metricMean({samples:row.samples});return value===null?[]:[{label:row.firmware_version+" · "+row.run_id.slice(0,8),value}];});
 if(loader.loading&&!loader.data)return<LoadingState label="Loading performance history…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 return<div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Analyze</div><h2>Performance trends</h2><p className="muted">Raw samples remain authoritative; the chart is a readable aggregate over valid, non-warm-up samples.</p></div></div>
  <Section title="Metric history"><div className="filter-grid"><Field label="Test ID"><input list="test-options" value={testId} onChange={e=>setTestId(e.target.value)}/><datalist id="test-options">{defaultTests.map(item=><option key={item} value={item}/>)}</datalist></Field><div className="filter-actions"><Button onClick={()=>setSubmitted(testId.trim())} disabled={!testId.trim()}>Load</Button></div></div></Section>
  <Section title="Trend" subtitle={[...new Set(rows.map(row=>row.metric_name))].join(", ")||"No metric history"}><LineChart title="Authoritative mean per Run" points={chartPoints} valueLabel={rows[0]?.unit||""}/></Section>
  <Section title="Raw history"><DataTable rows={rows} rowKey={(row,index)=>row.run_id+"-"+row.metric_name+"-"+index} columns={[
   {key:"run_id",label:"Run"},{key:"firmware_version",label:"Firmware"},{key:"metric_name",label:"Metric"},{key:"unit",label:"Unit"},{key:"samples",label:"Valid samples",render:row=>validSamples(row.samples).length},{key:"captured_at",label:"Captured",render:row=>formatDate(row.captured_at)},{key:"values",label:"Values",render:row=>validSamples(row.samples).map(item=>item.value).join(", ")||"—"}
  ]} emptyTitle="No metric history" emptyMessage="The selected Test ID has no persisted metric samples."/></Section>
 </div>;
}
export function TelemetryPage(){
 const[runId,setRunId]=useState(""),[submitted,setSubmitted]=useState("");
 const loader=useAsyncLoader(()=>api.telemetry(submitted),[submitted],{enabled:Boolean(submitted)});
 const items=loader.data?.items||[],chartPoints=items.flatMap(item=>(item.snapshot?.points||[]).filter(point=>Number.isFinite(Number(point.value))).map(point=>({label:point.metric,value:Number(point.value),unit:point.unit})));
 return<div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Analyze</div><h2>WiFi telemetry</h2><p className="muted">Every point retains environment class, source and timestamp. Virtual WiFi telemetry is not RF certification.</p></div></div>
  <Section title="Select Run"><div className="filter-grid"><Field label="Run ID"><input value={runId} onChange={e=>setRunId(e.target.value)}/></Field><div className="filter-actions"><Button onClick={()=>setSubmitted(runId.trim())} disabled={!runId.trim()}>Load</Button></div></div></Section>
  {loader.loading?<LoadingState label="Loading telemetry…"/>:null}{loader.error?<InlineNotice tone="danger">{loader.error.message}</InlineNotice>:null}
  {items.length?<><LineChart title="Numeric telemetry points" points={chartPoints} valueLabel={chartPoints[0]?.unit||""}/>{items.map((item,index)=><Section key={index} title={item.snapshot?.environment_class||"Unknown environment"} subtitle={formatDate(item.snapshot?.captured_at)+" · "+(item.snapshot?.interface||"interface unavailable")}><DataTable rows={item.snapshot?.points||[]} rowKey={(row,i)=>(row.metric||"metric")+"-"+i} columns={[
   {key:"metric",label:"Metric"},{key:"value",label:"Value",render:row=>row.value+" "+(row.unit||"")},{key:"source",label:"Source"},{key:"captured_at",label:"Captured",render:row=>formatDate(row.captured_at)},{key:"environment_class",label:"Environment"}
  ]} emptyTitle="No points" emptyMessage="No telemetry points were captured."/></Section>)}</>:submitted&&!loader.loading?<EmptyState title="No telemetry artifacts" message="No integrity-verified telemetry artifact is available for this Run."/>:null}
 </div>;
}