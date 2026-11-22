import React,{useEffect,useState} from "react";
import {Activity,ArrowUpRight,GitCompare,TrendingDown,TrendingUp,Wifi} from "lucide-react";
import {api} from "../api";
import {useWorkspace} from "@/components/workspace-context";
import {navigate} from "../router";
import {useAsyncLoader,useMutation} from "../hooks";
import {canPerform} from "../permissions";
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
  <div className="page-actions-row"><span className="context-caption">Explicit baseline-to-current comparison · no implicit baseline</span></div>
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

function PerformanceHistoryPage(){
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
  <div className="page-actions-row"><span className="context-caption">Metric history · valid non-warm-up samples only in aggregates</span></div>
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

const DEFAULT_PERFORMANCE_POLICY=JSON.stringify({
 metrics:[{
  name:"latency",unit:"ms",direction:"LOWER_IS_BETTER",
  target:20,warning:40,failure:80,aggregate:"mean",
  minimum_samples:3,allowed_statuses:["VALID"],include_retried:false,required:true
 }]
},null,2);

function PerformancePolicyWorkspace({user}){
 const workspace=useWorkspace();
 const projects=useAsyncLoader(()=>workspace.activeOrganizationId?api.workspaceProjects({organization_id:workspace.activeOrganizationId}):Promise.resolve({items:[]}),[workspace.activeOrganizationId],{enabled:Boolean(workspace.activeOrganizationId),queryKey:"performance-policy-projects"});
 const [projectId,setProjectId]=useState(workspace.activeProjectId||"");
 const [labId,setLabId]=useState(workspace.activeLabId||"");
 const [profileId,setProfileId]=useState("");
 const [revisionId,setRevisionId]=useState("");
 const [definitionText,setDefinitionText]=useState(DEFAULT_PERFORMANCE_POLICY);
 const [profileForm,setProfileForm]=useState({name:"Wireless performance",description:"",scope_type:"LAB",scope_id:""});
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const labs=useAsyncLoader(()=>projectId?api.workspaceLabs(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"performance-policy-labs"});
 const profiles=useAsyncLoader(()=>projectId?api.performancePolicies(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"performance-policy-profiles"});
 const assignments=useAsyncLoader(()=>projectId?api.performanceAssignments(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"performance-policy-assignments"});
 const revisions=useAsyncLoader(()=>profileId?api.performanceRevisions(profileId):Promise.resolve({items:[]}),[profileId],{enabled:Boolean(profileId),queryKey:"performance-policy-revisions"});
 const selectedAssignment=(assignments.data?.items||[]).find(item=>item.lab_id===labId)||null;
 const effectiveRevisions=useAsyncLoader(
  ()=>selectedAssignment?api.performanceRevisions(selectedAssignment.policy_profile_id):Promise.resolve({items:[]}),
  [selectedAssignment?.policy_profile_id],
  {enabled:Boolean(selectedAssignment?.policy_profile_id),queryKey:"performance-effective-policy-revisions"}
 );
 const mutation=useMutation();
 const canRead=canPerform(user,"performance.read");
 const canManage=canPerform(user,"performance.manage");
 const canPublish=canPerform(user,"performance.publish");
 const profileRows=profiles.data?.items||[];
 const revisionRows=revisions.data?.items||[];
 const selectedRevision=revisionRows.find(item=>item.revision_id===revisionId)||null;
 const effectiveRevision=(effectiveRevisions.data?.items||[]).find(item=>item.revision_id===selectedAssignment?.revision_id)||null;
 const labRows=(labs.data?.items||[]).filter(item=>item.status==="ACTIVE");
 const selectedProfile=profileRows.find(item=>item.policy_profile_id===profileId)||null;

 useEffect(()=>{
  const projectRows=projects.data?.items||[];
  if(workspace.activeProjectId&&projectRows.some(item=>item.project_id===workspace.activeProjectId)){
   if(projectId!==workspace.activeProjectId){
    setProjectId(workspace.activeProjectId);setLabId(workspace.activeLabId||"");setProfileId("");setRevisionId("");
   }
  }else if(projectId&&!projectRows.some(item=>item.project_id===projectId)){
   setProjectId("");setLabId("");setProfileId("");setRevisionId("");
  }else if(!projectId&&projectRows.length){
   const first=projectRows[0].project_id;setProjectId(first);workspace.selectProject(first);
  }
 },[projects.data,projectId,workspace.activeProjectId,workspace.activeLabId]);
 useEffect(()=>{
  if(!labs.loading&&labs.data&&labId&&!labRows.some(item=>item.lab_id===labId)){
   setLabId("");workspace.selectLab("");
  }else if(!labs.loading&&labs.data&&!labId&&labRows.length){
   const first=labRows[0].lab_id;setLabId(first);workspace.selectLab(first);
  }
 },[labs.data,labs.loading,labId]);
 useEffect(()=>{
  if(!profileId&&profileRows.length)setProfileId(profileRows[0].policy_profile_id);
 },[profiles.data,profileId]);

 async function perform(action,success,refresh=true){
  setError("");setNotice("");
  try{
   const result=await mutation.run(action);
   setNotice(success);
   if(refresh)await Promise.all([profiles.reload(),assignments.reload(),revisions.reload().catch(()=>null),effectiveRevisions.reload().catch(()=>null)]);
   return result;
  }catch(exc){setError(exc.message||"Performance policy operation failed.");return null;}
 }
 async function createProfile(event){
  event.preventDefault();
  const scopeType=profileForm.scope_type;
  const result=await perform(()=>api.createPerformancePolicy({
   project_id:projectId,name:profileForm.name,description:profileForm.description,
   scope_type:scopeType,scope_id:scopeType==="PROJECT"?projectId:profileForm.scope_id
  }),"Performance policy profile created.");
  if(result?.policy_profile_id)setProfileId(result.policy_profile_id);
 }
 async function createRevision(event){
  event.preventDefault();
  let definition;
  try{definition=JSON.parse(definitionText);}catch{setError("Policy definition must be valid JSON.");return;}
  const result=await perform(()=>api.createPerformanceRevision(profileId,{definition}),"Draft policy revision created.");
  if(result?.revision_id)setRevisionId(result.revision_id);
 }
 async function publishRevision(){
  if(!profileId||!revisionId){setError("Select a draft revision first.");return;}
  const result=await perform(()=>api.publishPerformanceRevision(profileId,{revision_id:revisionId}),"Policy revision published.");
  if(result?.revision_id)setRevisionId(result.revision_id);
 }
 async function assignRevision(){
  if(!profileId||!revisionId||!labId){setError("Select a policy revision and an active Lab.");return;}
  const result=await perform(()=>api.assignPerformanceRevision(profileId,{revision_id:revisionId,lab_id:labId}),"Published revision assigned to the selected Lab.");
  if(result?.revision_id)setRevisionId(result.revision_id);
 }
 if(!canRead)return <InlineNotice tone="warning">Your account does not have permission to read performance policies. Ask an Owner or Admin to review the Project role.</InlineNotice>;
 return <div className="page-stack">
  <div className="module-intro"><div className="module-intro-icon"><Activity size={19}/></div><div><strong>Versioned performance policy</strong><p>Manage immutable threshold revisions per Project or Lab. Publishing freezes the selected revision; assignment controls which published revision is selected for future Runs.</p></div></div>
  <Section title="Project and Lab scope" subtitle="Policy records and Lab assignments are isolated by Project.">
   <div className="form-grid">
    <Field label="Project"><select value={projectId} onChange={event=>{const value=event.target.value;setProjectId(value);workspace.selectProject(value);setProfileId("");setRevisionId("");setLabId("");}} disabled={projects.loading}>
     <option value="">Select Project</option>{(projects.data?.items||[]).map(item=><option key={item.project_id} value={item.project_id}>{item.name} · {item.slug}</option>)}
    </select></Field>
    <Field label="Lab for effective policy"><select value={labId} onChange={event=>{setLabId(event.target.value);workspace.selectLab(event.target.value);}} disabled={!projectId||labs.loading}>
     <option value="">Select active Lab</option>{labRows.map(item=><option key={item.lab_id} value={item.lab_id}>{item.name} · {item.provider_id}</option>)}
    </select></Field>
   </div>
   {projects.error?<InlineNotice tone="danger">Projects could not be loaded: {projects.error.message}</InlineNotice>:null}
   {labs.error?<InlineNotice tone="danger">Labs could not be loaded: {labs.error.message}</InlineNotice>:null}
  </Section>
  {notice?<InlineNotice tone="success">{notice}</InlineNotice>:null}
  {error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  {canManage?<Section title="Create policy profile" subtitle="Choose Project defaults or bind a profile to one Lab. The service verifies Lab ownership.">
   <form className="form-grid" onSubmit={createProfile}>
    <Field label="Profile name" required><input value={profileForm.name} onChange={event=>setProfileForm({...profileForm,name:event.target.value})} maxLength={120} required/></Field>
    <Field label="Scope"><select value={profileForm.scope_type} onChange={event=>setProfileForm({...profileForm,scope_type:event.target.value,scope_id:""})}><option value="PROJECT">Project</option><option value="LAB">Lab</option></select></Field>
    {profileForm.scope_type==="LAB"?<Field label="Lab ID"><select value={profileForm.scope_id} onChange={event=>setProfileForm({...profileForm,scope_id:event.target.value})} required><option value="">Select Lab</option>{labRows.map(item=><option key={item.lab_id} value={item.lab_id}>{item.name}</option>)}</select></Field>:null}
    <Field label="Description"><input value={profileForm.description} onChange={event=>setProfileForm({...profileForm,description:event.target.value})} maxLength={500}/></Field>
    <div className="form-actions"><Button type="submit" disabled={mutation.loading||!projectId||!profileForm.name.trim()||(profileForm.scope_type==="LAB"&&!profileForm.scope_id)}>Create profile</Button></div>
   </form>
  </Section>:null}
  <Section title="Policy revisions" subtitle="Create drafts, inspect immutable revision history, publish and assign a published revision.">
   <div className="form-grid">
    <Field label="Policy profile"><select value={profileId} onChange={event=>{setProfileId(event.target.value);setRevisionId("");}}><option value="">Select policy profile</option>{profileRows.map(item=><option key={item.policy_profile_id} value={item.policy_profile_id}>{item.name} · {item.scope_type}</option>)}</select></Field>
    <Field label="Revision"><select value={revisionId} onChange={event=>{setRevisionId(event.target.value);const found=revisionRows.find(item=>item.revision_id===event.target.value);if(found)setDefinitionText(JSON.stringify(found.definition,null,2));}}><option value="">Select revision</option>{revisionRows.map(item=><option key={item.revision_id} value={item.revision_id}>r{item.revision_number} · {item.status}</option>)}</select></Field>
   </div>
   {selectedProfile?<div className="context-caption">{selectedProfile.description||selectedProfile.name} · {selectedProfile.scope_type}:{selectedProfile.scope_id} · {selectedProfile.status}</div>:null}
   {canManage?<form className="form-grid" onSubmit={createRevision}>
    <Field label="Metric thresholds (JSON)" className="full-width" hint="Metric names and units must exactly match the measurements emitted by the Runner. The initial latency example is illustrative, not an automatic mapping."><textarea rows={11} value={definitionText} onChange={event=>setDefinitionText(event.target.value)} spellCheck="false"/></Field>
    <div className="form-actions"><Button type="submit" disabled={mutation.loading||!profileId}>Create draft revision</Button></div>
   </form>:null}
   {revisions.loading?<LoadingState label="Loading policy revisions…"/>:revisions.error?<ErrorState error={revisions.error} onRetry={revisions.reload}/>:<DataTable caption="Performance policy revision history" rows={revisionRows} rowKey={item=>item.revision_id} columns={[
    {key:"revision_number",label:"Revision"},
    {key:"policy_hash",label:"SHA-256",render:item=><code title={item.policy_hash}>{item.policy_hash.slice(0,12)}…</code>},
    {key:"status",label:"Lifecycle",render:item=><StatusBadge value={item.status}/>},
    {key:"created_at",label:"Created",render:item=>formatDate(item.created_at)},
    {key:"published_at",label:"Published",render:item=>item.published_at?formatDate(item.published_at):"—"},
    {key:"created_by",label:"Author"}
   ]} emptyTitle="No policy revisions" emptyMessage="Create a draft revision for this profile."/>}
   <div className="button-row">
    {canPublish?<Button disabled={!selectedRevision||selectedRevision.status!=="DRAFT"||mutation.loading} onClick={publishRevision}>Publish selected revision</Button>:null}
    {canPublish?<Button variant="outline" disabled={!selectedRevision||selectedRevision.status!=="PUBLISHED"||!labId||mutation.loading} onClick={assignRevision}>Assign published revision to Lab</Button>:null}
   </div>
  </Section>
  <Section title="Effective thresholds" subtitle="The selected Lab's assigned published revision is the threshold set eligible for Run selection.">
   {assignments.loading?<LoadingState label="Loading Lab policy assignments…"/>:assignments.error?<ErrorState error={assignments.error} onRetry={assignments.reload}/>:null}
   {!selectedAssignment?<EmptyState title="No policy assigned to this Lab" message="Publish a revision and assign it to this Lab to make its thresholds available in the Run launch workflow."/>:null}
   {selectedAssignment&&effectiveRevisions.loading?<LoadingState label="Loading assigned policy revision…"/>:null}
   {selectedAssignment&&effectiveRevisions.error?<ErrorState error={effectiveRevisions.error} onRetry={effectiveRevisions.reload}/>:null}
   {effectiveRevision?<>
    <div className="module-intro"><div><strong>{effectiveRevision.status} · revision {effectiveRevision.revision_number}</strong><p>Profile {selectedAssignment.policy_profile_id} · SHA-256 {effectiveRevision.policy_hash}</p></div></div>
    <DataTable caption="Effective performance thresholds" rows={effectiveRevision.definition?.metrics||[]} rowKey={item=>item.name} columns={[
     {key:"name",label:"Metric"},{key:"unit",label:"Unit"},{key:"direction",label:"Direction"},
     {key:"target",label:"Target",align:"right"},{key:"warning",label:"Warning",align:"right"},{key:"failure",label:"Failure",align:"right"},
     {key:"aggregate",label:"Aggregate"},{key:"minimum_samples",label:"Min samples",align:"right"}
    ]} emptyTitle="No metric thresholds" emptyMessage="The assigned revision contains no metric definitions."/>
   </>:null}
   <DataTable caption="Performance policy assignments" rows={assignments.data?.items||[]} rowKey={item=>item.assignment_id} columns={[
    {key:"lab_id",label:"Lab"},{key:"policy_profile_id",label:"Profile"},{key:"revision_id",label:"Published revision"},
    {key:"assigned_at",label:"Assigned",render:item=>formatDate(item.assigned_at)},{key:"assigned_by",label:"By"}
   ]} emptyTitle="No assignments" emptyMessage="No performance policy is assigned in this Project."/>
  </Section>
 </div>;
}

export function PerformancePage({user}){
 const [view,setView]=useState("policies");
 return <div className="page-stack">
  <div className="button-row" role="tablist" aria-label="Performance views">
   <Button variant={view==="policies"?"default":"outline"} onClick={()=>setView("policies")} role="tab" aria-selected={view==="policies"}>Policy management</Button>
   <Button variant={view==="history"?"default":"outline"} onClick={()=>setView("history")} role="tab" aria-selected={view==="history"}>Metric history</Button>
  </div>
  {view==="policies"?<PerformancePolicyWorkspace user={user}/>:<PerformanceHistoryPage/>}
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
  <div className="page-actions-row"><span className="context-caption">Environment-aware data · virtual WiFi is not RF certification</span></div>
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
