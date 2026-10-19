import React,{useEffect,useState} from "react";
import {Activity,ArrowUpRight,GitCompare,TrendingDown,TrendingUp,Wifi} from "lucide-react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader} from "../hooks";
import {formatDate,formatNumber,formatShortDate,metricMean,toFiniteNumber,validSamples} from "../utils";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LineChart,LoadingState,Section,StatCard,StatusBadge} from "../components/ui";

const defaultTests=["wifi.latency.threshold","wifi.packet_loss.threshold","wifi.throughput.minimum","wifi.ping.success"];

export function RegressionPage(){
 const[baseline,setBaseline]=useState(""),[current,setCurrent]=useState(""),[search,setSearch]=useState(""),[classification,setClassification]=useState(""),[submitted,setSubmitted]=useState(null);
 const loader=useAsyncLoader(()=>submitted?api.regressions(submitted.baseline,submitted.current):Promise.resolve(null),[submitted?.baseline,submitted?.current],{enabled:Boolean(submitted)});
 const assessments=(loader.data?.assessments||[]).filter(item=>{const term=search.trim().toLowerCase();return(!term||(item.test_id||"").toLowerCase().includes(term)||(item.reason||"").toLowerCase().includes(term))&&(!classification||item.classification===classification);});
 const comparisons=loader.data?.assessments||[];
 const regressionCount=comparisons.filter(item=>["REGRESSION","SOFT_REGRESSION"].includes(item.classification)).length;
 const fixedCount=comparisons.filter(item=>["FIXED","IMPROVED"].includes(item.classification)).length;
 return <div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Analyze / Compare</div><h2>Regression intelligence</h2><p className="muted">Compare two persisted Runs. Confirm comparability and environment class before interpreting performance changes.</p></div><GitCompare className="page-title-icon" size={25} aria-hidden="true"/></div>
  <Section title="Compare Runs" subtitle="Choose an explicit baseline and current Run. No implicit baseline is assumed.">
   <form className="filter-grid" onSubmit={event=>{event.preventDefault();setSubmitted({baseline:baseline.trim(),current:current.trim()});}}>
    <Field label="Baseline Run ID" required><input value={baseline} onChange={e=>setBaseline(e.target.value)} placeholder="Baseline Run ID" required/></Field>
    <Field label="Current Run ID" required><input value={current} onChange={e=>setCurrent(e.target.value)} placeholder="Current Run ID" required/></Field>
    <div className="filter-actions"><Button type="submit" disabled={!baseline.trim()||!current.trim()}><GitCompare size={15}/>Compare Runs</Button></div>
   </form>
   {loader.error?<InlineNotice tone="danger">{loader.error.message}</InlineNotice>:null}
  </Section>
  {loader.loading?<LoadingState label="Comparing persisted Run evidence…"/>:null}
  {loader.data?<><div className="stat-grid">
    <StatCard label="Comparability" value={<StatusBadge value={loader.data.comparability}/>} hint="Required before interpretation" icon={<GitCompare size={17}/>}/>
    <StatCard label="Regressions" value={regressionCount} hint="Hard + soft classifications" icon={<TrendingDown size={17}/>} tone={regressionCount?"warning":"default"}/>
    <StatCard label="Fixed / improved" value={fixedCount} hint="Changes classified by the engine" icon={<TrendingUp size={17}/>} tone="success"/>
    <StatCard label="Assessments" value={comparisons.length} hint="Persisted test comparisons" icon={<Activity size={17}/>}/>
   </div><InlineNotice tone={loader.data.comparability==="COMPARABLE"?"success":"warning"}>{loader.data.reason||"The comparison engine returned no comparability explanation."}</InlineNotice>
   {loader.data.environment?<div className="two-column"><Section title="Baseline environment"><div className="environment-summary"><Wifi size={16}/><span>{loader.data.environment.baseline||"Not recorded"}</span></div></Section><Section title="Current environment"><div className="environment-summary"><Wifi size={16}/><span>{loader.data.environment.current||"Not recorded"}</span></div></Section></div>:null}
   <Section title="Assessment results" subtitle={assessments.length+" of "+comparisons.length+" assessments visible"}>
    <div className="filter-grid compact-filter-grid"><Field label="Search test or reason"><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search assessments…"/></Field><Field label="Classification"><select value={classification} onChange={e=>setClassification(e.target.value)}><option value="">All classifications</option><option>REGRESSION</option><option>SOFT_REGRESSION</option><option>FIXED</option><option>IMPROVED</option><option>NO_BASELINE</option><option>UNVALIDATED</option></select></Field><div className="filter-actions"><Button variant="outline" onClick={()=>{setSearch("");setClassification("");}}>Clear filters</Button></div></div>
    <DataTable caption="Regression assessment results" rows={assessments} rowKey={row=>row.test_id} columns={[
     {key:"test_id",label:"Test"},{key:"baseline_status",label:"Baseline",render:row=><StatusBadge value={row.baseline_status}/>},{key:"current_status",label:"Current",render:row=><StatusBadge value={row.current_status}/>},{key:"classification",label:"Classification",render:row=><StatusBadge value={row.classification}/>},{key:"dimensions",label:"Dimensions",render:row=><div className="pill-list compact-pills">{(row.dimensions||[]).map(item=><span className="pill" key={item}>{item}</span>)}</div>},{key:"reason",label:"Reason"},
     {key:"current_test_result_id",label:"Detail",render:row=>row.current_test_result_id?<a className="text-link inline-action" href={"/runs/"+encodeURIComponent(loader.data.current_run_id)+"/tests/"+encodeURIComponent(row.current_test_result_id)} onClick={e=>{e.preventDefault();navigate("/runs/"+encodeURIComponent(loader.data.current_run_id)+"/tests/"+encodeURIComponent(row.current_test_result_id));}}>Open <ArrowUpRight size={13}/></a>:"—"}
    ]} emptyTitle="No matching assessments" emptyMessage="Adjust the classification or search filters."/>
   </Section>
  </>:submitted&&!loader.loading?<EmptyState title="No comparison data" message="The API returned no assessment result for the selected Run pair."/>:null}
 </div>;
}

export function PerformancePage(){
 const[testId,setTestId]=useState(defaultTests[0]),[submitted,setSubmitted]=useState(defaultTests[0]),[metricName,setMetricName]=useState("");
 const loader=useAsyncLoader(()=>api.metricsHistory(submitted),[submitted]);
 const rows=loader.data?.items||[];
 const metricNames=[...new Set(rows.map(row=>row.metric_name).filter(Boolean))];
 useEffect(()=>{if(metricNames.length&&!metricNames.includes(metricName))setMetricName(metricNames[0]);},[metricNames.join("|"),metricName]);
 const selectedRows=rows.filter(row=>row.metric_name===metricName).slice().sort((a,b)=>{
   const left=Date.parse(a.captured_at||""),right=Date.parse(b.captured_at||"");
   return Number.isFinite(left)&&Number.isFinite(right)?left-right:0;
 });
 const chartPoints=selectedRows.flatMap(row=>{
   const value=metricMean(row);
   return value===null?[]:[{label:(row.firmware_version||"Firmware")+" · "+String(row.run_id||"").slice(0,8),value,run_id:row.run_id,captured_at:row.captured_at}];
 });
 const validCount=selectedRows.reduce((sum,row)=>sum+validSamples(row.samples).length,0);
 const unit=selectedRows.find(row=>row.unit)?.unit||"unit not recorded";
 if(loader.loading&&!loader.data)return <LoadingState label="Loading performance history…"/>;
 if(loader.error&&!loader.data)return <ErrorState error={loader.error} onRetry={loader.reload}/>;
 return <div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Analyze / Trends</div><h2>Performance trends</h2><p className="muted">Each chart represents one metric and one unit. Means include only explicitly valid, non-warm-up numeric samples.</p></div><TrendingUp size={25} className="page-title-icon" aria-hidden="true"/></div>
  <Section title="Select metric" subtitle="The test ID loads persisted history; choose one metric before interpreting its trend.">
   <form className="filter-grid" onSubmit={event=>{event.preventDefault();setSubmitted(testId.trim());setMetricName("");}}>
    <Field label="Test ID" required><input list="test-options" value={testId} onChange={e=>setTestId(e.target.value)} required/><datalist id="test-options">{defaultTests.map(item=><option key={item} value={item}/>)}</datalist></Field>
    <div className="filter-actions"><Button type="submit" disabled={!testId.trim()}><Activity size={14}/>Load history</Button></div>
   </form>
  </Section>
  {metricNames.length>1?<Section title="Metric series" subtitle="Separate metrics and units are never mixed in one chart."><div className="filter-grid compact-filter-grid"><Field label="Metric"><select value={metricName} onChange={event=>setMetricName(event.target.value)}>{metricNames.map(name=><option key={name} value={name}>{name}</option>)}</select></Field></div></Section>:null}
  {loader.error?<InlineNotice tone="danger">{loader.error.message}</InlineNotice>:null}
  {loader.data?<><div className="stat-grid">
   <StatCard label="Runs with metric" value={selectedRows.length} hint="Persisted metric history" icon={<DatabaseIcon/>}/>
   <StatCard label="Valid samples" value={validCount} hint="Valid + non-warm-up + numeric" icon={<CheckMetricIcon/>} tone="success"/>
   <StatCard label="Metric" value={metricName||"—"} hint={unit} icon={<TrendingUp size={17}/>}/>
   <StatCard label="Mean observations" value={chartPoints.length} hint="One aggregate per eligible Run" icon={<Activity size={17}/>}/>
  </div>
  <Section title={metricName||"Metric trend"} subtitle={"Valid sample mean per Run · "+unit}>
   {chartPoints.length?<LineChart title="Metric trend" points={chartPoints} valueLabel={unit}/>:<EmptyState title="No valid numeric samples" message="This series has no explicitly valid, non-warm-up numeric samples. Raw samples remain available below."/>}
  </Section>
  <Section title="Raw metric history" subtitle={rows.length+" persisted row(s), including non-valid and warm-up samples"}>
   <DataTable caption="Raw performance metric history" rows={rows} rowKey={(row,index)=>row.run_id+"-"+row.metric_name+"-"+index} columns={[
    {key:"run_id",label:"Run",render:row=><span className="mono">{String(row.run_id||"—").slice(0,12)}</span>},{key:"firmware_version",label:"Firmware"},{key:"metric_name",label:"Metric"},{key:"unit",label:"Unit"},{key:"samples",label:"Valid samples",align:"right",render:row=>validSamples(row.samples).length},{key:"captured_at",label:"Captured",render:row=>formatDate(row.captured_at)},{key:"values",label:"Raw values",render:row=>(row.samples||[]).map(item=>toFiniteNumber(item.value)===null?"—":formatNumber(item.value)).join(", ")||"—"}
   ]} emptyTitle="No metric history" emptyMessage="The selected Test ID has no persisted metric samples."/>
  </Section></>:null}
 </div>;
}
function DatabaseIcon(){return <Activity size={17}/>;}
function CheckMetricIcon(){return <Activity size={17}/>;}

export function TelemetryPage(){
 const[runId,setRunId]=useState(""),[submitted,setSubmitted]=useState(""),[metricSelection,setMetricSelection]=useState("");
 const loader=useAsyncLoader(()=>api.telemetry(submitted),[submitted],{enabled:Boolean(submitted)});
 const items=loader.data?.items||[];
 const points=items.flatMap((item,snapshotIndex)=>(item.snapshot?.points||[]).map((point,pointIndex)=>({
   point,snapshot:item.snapshot,snapshotIndex,pointIndex,
   metricKey:String(point.metric||"Unknown metric")+" · "+String(point.unit||"unit not recorded"),
 })));
 const metricOptions=[...new Map(points.filter(item=>toFiniteNumber(item.point.value)!==null).map(item=>[item.metricKey,{value:item.metricKey,label:item.metricKey}])).values()];
 useEffect(()=>{if(metricOptions.length&&!metricOptions.some(item=>item.value===metricSelection))setMetricSelection(metricOptions[0].value);},[metricOptions.map(item=>item.value).join("|"),metricSelection]);
 const chartPoints=points.filter(item=>item.metricKey===metricSelection&&toFiniteNumber(item.point.value)!==null).map(item=>({
   label:formatShortDate(item.point.captured_at||item.snapshot?.captured_at)+" · "+String(item.snapshot?.interface||"WiFi").slice(0,14),
   value:toFiniteNumber(item.point.value),captured_at:item.point.captured_at||item.snapshot?.captured_at,
 }));
 return <div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Analyze / Radio & network</div><h2>WiFi telemetry</h2><p className="muted">Source, timestamp, interface and environment class remain attached to every point. Virtual WiFi data is not RF certification.</p></div><Wifi size={25} className="page-title-icon" aria-hidden="true"/></div>
  <Section title="Select Run" subtitle="Load only integrity-verified telemetry attached to this Run.">
   <form className="filter-grid compact-filter-grid" onSubmit={event=>{event.preventDefault();setSubmitted(runId.trim());setMetricSelection("");}}>
    <Field label="Run ID" required><input value={runId} onChange={e=>setRunId(e.target.value)} required placeholder="Run ID"/></Field>
    <div className="filter-actions"><Button type="submit" disabled={!runId.trim()}><Wifi size={14}/>Load telemetry</Button></div>
   </form>
  </Section>
  {loader.loading?<LoadingState label="Loading integrity-verified telemetry…"/>:null}
  {loader.error?<InlineNotice tone="danger">{loader.error.message}</InlineNotice>:null}
  {items.length?<><div className="stat-grid">
   <StatCard label="Snapshots" value={items.length} hint="Integrity-verified artifacts" icon={<Wifi size={17}/>}/>
   <StatCard label="Numeric points" value={points.filter(item=>toFiniteNumber(item.point.value)!==null).length} hint="All available metrics" icon={<Activity size={17}/>}/>
   <StatCard label="Interfaces" value={[...new Set(items.map(item=>item.snapshot?.interface).filter(Boolean))].length} hint="Recorded interfaces" icon={<DatabaseIcon/>}/>
   <StatCard label="Environment" value={[...new Set(items.map(item=>item.snapshot?.environment_class).filter(Boolean))].join(", ")||"Not recorded"} hint="Preserved from evidence" icon={<Wifi size={17}/>}/>
  </div>
  {metricOptions.length?<Section title="Numeric telemetry trend" subtitle="Choose a single metric and unit; unrelated values are never plotted on one axis.">
   <div className="filter-grid compact-filter-grid"><Field label="Metric series"><select value={metricSelection} onChange={event=>setMetricSelection(event.target.value)}>{metricOptions.map(item=><option value={item.value} key={item.value}>{item.label}</option>)}</select></Field></div>
   <LineChart title={metricSelection} points={chartPoints} valueLabel={metricSelection.split(" · ").at(-1)}/>
  </Section>:<EmptyState title="No numeric telemetry points" message="The snapshots contain no finite numeric values to chart; raw point records remain available below."/>}
  {items.map((item,index)=><Section key={item.artifact_id||index} title={item.snapshot?.environment_class||"Unknown environment"} subtitle={formatDate(item.snapshot?.captured_at)+" · "+(item.snapshot?.interface||"interface unavailable")} actions={<StatusBadge value={item.snapshot?.environment_class}/>}><DataTable rows={item.snapshot?.points||[]} rowKey={(row,i)=>(row.metric||"metric")+"-"+i} columns={[
   {key:"metric",label:"Metric"},{key:"value",label:"Value",align:"right",render:row=>toFiniteNumber(row.value)===null?"—":formatNumber(row.value)+" "+(row.unit||"")},{key:"source",label:"Source"},{key:"captured_at",label:"Captured",render:row=>formatDate(row.captured_at)},{key:"environment_class",label:"Environment"}
  ]} emptyTitle="No points" emptyMessage="No telemetry points were captured."/></Section>)}
  </>:submitted&&!loader.loading?<EmptyState title="No telemetry artifacts" message="No integrity-verified telemetry artifact is available for this Run."/>:null}
 </div>;
}
