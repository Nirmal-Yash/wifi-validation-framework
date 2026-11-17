import React,{useEffect,useState} from "react";
import {api} from "@/api";
import {useAsyncLoader,useMutation} from "@/hooks";
import {canPerform} from "@/permissions";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

const STARTER=JSON.stringify({steps:[{
 key:"provision",type:"WIFI_LAB_PROVISION",name:"Provision the reference Wi-Fi Lab",
 timeout_seconds:600,max_attempts:1,input:{confirmed:true}
}]},null,2);
const GUIDANCE=`Allowed step types:
- WIFI_LAB_PROVISION: input { "confirmed": true }
- TOPOLOGY_APPLY: input { "profile_id": "...", "revision_id": "...", "expected_sha256": "<64 hex>", "confirmed": true }
- PROVIDER_RECONCILE: input { "profile_id": "...", "revision_id": "..." }
- CONFIGURATION_DEPLOY: input { "profile_id": "...", "revision_id": "...", "configuration_hash": "<64 hex>", "device_id": "...", "ssh_credential_id": "...", "wifi_psk_credential_id": "...", "confirmed": true }
- VALIDATION_RUN: input { "tests": ["wifi.latency.threshold"], "firmware_version": "v1.0", "performance_policy_revision_id": "...", "configuration_profile_id": "...", "configuration_revision_id": "...", "topology_profile_id": "...", "topology_revision_id": "...", "device_id": "...", "ssh_credential_id": "..." }

Configuration and topology profile/revision references must be supplied in pairs. A selected configuration revision is resolved through its Project, Lab or Device layer. A selected topology revision must be in sync with the bound GNS3 Lab. Optional Device and SSH references must point to an active Device and its same-device SSH_PASSWORD credential.
Each step accepts key, type, name, timeout_seconds (5–3600), max_attempts (1–5).
Mutating operations and VALIDATION_RUN are single-attempt. VALIDATION_RUN accepts registered semantic test IDs or registered pytest node IDs.
No arbitrary shell/command step is accepted. Never put secret values in the definition.
Opaque Credential Vault IDs only.`;
const stamp=value=>value?new Date(value).toLocaleString():"—";

export default function PipelinesPage({user}){
 const [projectId,setProjectId]=useState("");const [labId,setLabId]=useState("");
 const [pipelineId,setPipelineId]=useState("");const [executionId,setExecutionId]=useState("");
 const [name,setName]=useState("Reference Wi-Fi pipeline");const [description,setDescription]=useState("");
 const [definitionText,setDefinitionText]=useState(STARTER);const [showEditor,setShowEditor]=useState(false);
 const [notice,setNotice]=useState("");const [error,setError]=useState("");
 const canManage=canPerform(user,"pipelines.manage");const canExecute=canPerform(user,"pipelines.execute");
 const projects=useAsyncLoader(()=>api.workspaceProjects(),[],{queryKey:"pipeline-projects"});
 const projectRows=projects.data?.items||[];
 const labs=useAsyncLoader(()=>projectId?api.workspaceLabs(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"pipeline-labs"});
 const labRows=(labs.data?.items||[]).filter(item=>item.status==="ACTIVE");
 const pipelines=useAsyncLoader(()=>projectId?api.pipelines(projectId,labId||undefined):Promise.resolve({items:[]}),[projectId,labId],{enabled:Boolean(projectId),queryKey:"pipeline-list"});
 const pipelineRows=pipelines.data?.items||[];
 const selectedPipeline=pipelineRows.find(item=>item.pipeline_id===pipelineId)||null;
 const detail=useAsyncLoader(()=>pipelineId?api.pipeline(pipelineId):Promise.resolve(null),[pipelineId],{enabled:Boolean(pipelineId),queryKey:"pipeline-detail"});
 const revisions=detail.data?.revisions||[];
 const publishedRevision=revisions.find(item=>item.status==="PUBLISHED")||null;
 const executions=useAsyncLoader(()=>pipelineId?api.pipelineExecutions(pipelineId):Promise.resolve({items:[]}),[pipelineId],{enabled:Boolean(pipelineId),queryKey:"pipeline-executions",refreshMs:5000});
 const executionRows=executions.data?.items||[];
 const selectedExecution=executionRows.find(item=>item.execution_id===executionId)||executionRows[0]||null;
 const executionDetail=useAsyncLoader(()=>selectedExecution?.execution_id?api.pipelineExecution(selectedExecution.execution_id):Promise.resolve(null),[selectedExecution?.execution_id],{enabled:Boolean(selectedExecution?.execution_id),queryKey:"pipeline-execution-detail",refreshMs:5000});
 const mutation=useMutation();
 useEffect(()=>{if(!projectId&&projectRows.length)setProjectId(projectRows[0].project_id);},[projects.data,projectId]);
 useEffect(()=>{if(labId&&!labRows.some(item=>item.lab_id===labId))setLabId("");},[labs.data,labId]);
 useEffect(()=>{if(!pipelineId&&pipelineRows.length)setPipelineId(pipelineRows[0].pipeline_id);},[pipelines.data,pipelineId]);
 useEffect(()=>{if(pipelineId&&!pipelineRows.some(item=>item.pipeline_id===pipelineId))setPipelineId("");},[pipelines.data,pipelineId]);
 useEffect(()=>{if(selectedExecution?.execution_id&&!executionId)setExecutionId(selectedExecution.execution_id);},[executionRows,executionId,selectedExecution?.execution_id]);
 useEffect(()=>{setExecutionId("");},[pipelineId]);
 useEffect(()=>{const current=detail.data?.pipeline;const latest=revisions[0];if(current){setName(current.name);setDescription(current.description||"");if(latest?.definition)setDefinitionText(JSON.stringify(latest.definition,null,2));}},[detail.data]);

 async function act(operation,success){
  setError("");setNotice("");
  try{const result=await mutation.run(operation);setNotice(success);return result;}
  catch(exc){setError(exc.message||"Pipeline operation failed.");return null;}
 }
 async function saveDefinition(event){
  event.preventDefault();let definition;
  try{definition=JSON.parse(definitionText);}catch{setError("Pipeline definition must be valid JSON.");return;}
  if(!projectId||!labId){setError("Select an active Project and Lab before saving.");return;}
  if(!name.trim()){setError("Pipeline name is required.");return;}
  const result=await act(async()=>{
   if(!pipelineId){
    const created=await api.createPipeline({project_id:projectId,lab_id:labId,name:name.trim(),description:description.trim(),definition});
    await api.publishPipelineRevision(created.pipeline.pipeline_id,{revision_id:created.revision.revision_id});
    setPipelineId(created.pipeline.pipeline_id);return created;
   }
   const draft=await api.createPipelineRevision(pipelineId,{definition});
   await api.publishPipelineRevision(pipelineId,{revision_id:draft.revision_id});return draft;
  },pipelineId?"New immutable pipeline revision published.":"Pipeline created and its first revision published.");
  if(result){setShowEditor(false);await Promise.all([pipelines.reload().catch(()=>null),detail.reload().catch(()=>null)]);}
 }
 async function enqueue(){
  if(!publishedRevision){setError("Publish a pipeline revision before execution.");return;}
  if(!window.confirm("Queue this immutable pipeline revision for execution in the selected Lab?"))return;
  const result=await act(()=>api.enqueuePipelineExecution(pipelineId,{revision_id:publishedRevision.revision_id}),"Pipeline execution queued. A local worker must be running to process it.");
  if(result?.execution_id){setExecutionId(result.execution_id);await Promise.all([executions.reload().catch(()=>null),executionDetail.reload().catch(()=>null)]);}
 }
 async function cancel(){
  if(!selectedExecution||!window.confirm("Request cancellation? An in-flight provider operation will not be forcibly interrupted."))return;
  await act(()=>api.cancelPipelineExecution(selectedExecution.execution_id),"Pipeline cancellation requested.");
  await Promise.all([executions.reload().catch(()=>null),executionDetail.reload().catch(()=>null)]);
 }
 async function recover(){
  if(!selectedExecution||!window.confirm("Have you inspected the actual GNS3/device state and confirmed it is safe to resume?"))return;
  await act(()=>api.recoverPipelineExecution(selectedExecution.execution_id),"Recovery approved. The local worker may now resume execution.");
  await Promise.all([executions.reload().catch(()=>null),executionDetail.reload().catch(()=>null)]);
 }
 function editSelected(){
  if(!selectedPipeline)return;
  setName(selectedPipeline.name);setDescription(selectedPipeline.description||"");setShowEditor(true);setError("");setNotice("");
 }
 if(projects.loading&&!projects.data)return <LoadingState label="Loading Project and Lab scopes…"/>;
 if(projects.error&&!projects.data)return <ErrorState error={projects.error} onRetry={projects.reload}/>;
 const execution=executionDetail.data||selectedExecution;
 const stepRows=execution?.steps||[];const attemptRows=execution?.attempts||[];
 const canCancel=canExecute&&execution&&["QUEUED","RUNNING","CANCELLING"].includes(execution.status);
 const canRecover=canManage&&execution?.status==="RECOVERY_REQUIRED";
 return <div className="page-stack">
  <div className="module-intro"><div className="module-intro-icon">⇢</div><div><strong>Durable workflow orchestration</strong><p>Published definitions are immutable. Executions, steps, worker attempts and recovery decisions are persisted within one Project and Lab. Provider operations run in the local worker, not in dashboard requests.</p></div></div>
  {notice?<InlineNotice tone="success">{notice}</InlineNotice>:null}{error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  <Section title="Pipeline scope" subtitle="Select the Project and Lab whose devices, credentials, topology and provider access the workflow may use." actions={<Button size="sm" variant="outline" onClick={()=>{pipelines.reload();executions.reload();executionDetail.reload();}}>Refresh</Button>}>
   <div className="form-grid">
    <Field label="Project"><select value={projectId} onChange={event=>{setProjectId(event.target.value);setLabId("");setPipelineId("");setExecutionId("");}}><option value="">Select Project</option>{projectRows.map(item=><option key={item.project_id} value={item.project_id}>{item.name} · {item.slug}</option>)}</select></Field>
    <Field label="Lab"><select value={labId} onChange={event=>{setLabId(event.target.value);setPipelineId("");setExecutionId("");}} disabled={!projectId||labs.loading}><option value="">All Labs</option>{labRows.map(item=><option key={item.lab_id} value={item.lab_id}>{item.name}</option>)}</select></Field>
    <Field label="Pipeline"><select value={pipelineId} onChange={event=>{setPipelineId(event.target.value);setExecutionId("");}} disabled={!projectId||pipelines.loading}><option value="">Select pipeline</option>{pipelineRows.map(item=><option key={item.pipeline_id} value={item.pipeline_id}>{item.name} · {item.latest_revision?.status||"DRAFT"}</option>)}</select></Field>
   </div>
   {labs.error?<InlineNotice tone="danger">{labs.error.message}</InlineNotice>:null}{pipelines.error?<InlineNotice tone="danger">{pipelines.error.message}</InlineNotice>:null}
  </Section>
  <Section title="Definitions and revisions" subtitle="Create or publish an immutable revision. The backend validates the step allow-list and resource scope." actions={canManage?<Button size="sm" onClick={()=>{if(pipelineId)editSelected();else{setName("Reference Wi-Fi pipeline");setDescription("");setDefinitionText(STARTER);setShowEditor(true);}}}>{pipelineId?"Edit / new revision":"Create pipeline"}</Button>:null}>
   {detail.loading&&!detail.data?<LoadingState label="Loading pipeline revisions…"/>:null}
   {selectedPipeline?<div className="module-intro"><div><strong>{selectedPipeline.name}</strong><p>{selectedPipeline.description||"No description"} · <code>{selectedPipeline.pipeline_id}</code></p></div><div className="content-intro-meta"><StatusBadge value={selectedPipeline.status}/></div></div>:<EmptyState emptyTitle="No pipeline selected" emptyMessage="Create a Project/Lab-scoped pipeline to define an approved sequence of operations."/>}
   {revisions.length?<DataTable caption="Immutable pipeline revisions" rows={revisions} rowKey={item=>item.revision_id} columns={[
    {key:"revision_number",label:"Revision",render:item=>"r"+item.revision_number},
    {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"definition_sha256",label:"Definition SHA-256",render:item=><code>{item.definition_sha256}</code>},
    {key:"created_at",label:"Created",render:item=>stamp(item.created_at)},
    {key:"published_at",label:"Published",render:item=>stamp(item.published_at)}
   ]}/>:null}
   {showEditor&&canManage?<form className="form-grid" onSubmit={saveDefinition}>
    <Field label="Pipeline name" required><input value={name} onChange={event=>setName(event.target.value)} maxLength={120} required/></Field>
    <Field label="Description"><input value={description} onChange={event=>setDescription(event.target.value)} maxLength={500}/></Field>
    <Field label="Pipeline definition JSON" className="full-width" hint="The server validates step type, timeout, retries, confirmation and secret references."><textarea rows={15} value={definitionText} onChange={event=>setDefinitionText(event.target.value)} spellCheck="false" required/></Field>
    <div className="full-width"><pre className="code-block">{GUIDANCE}</pre></div>
    <div className="form-actions"><Button type="submit" loading={mutation.loading} disabled={!projectId||!labId}>Save and publish revision</Button><Button type="button" variant="outline" onClick={()=>setShowEditor(false)}>Close</Button></div>
   </form>:null}
  </Section>
  <Section title="Execution history" subtitle={executionRows.length+" persisted execution(s) for this pipeline."} actions={pipelineId&&canExecute?<Button size="sm" onClick={enqueue} disabled={!publishedRevision||mutation.loading}>Queue published revision</Button>:null}>
   {executions.loading&&!executions.data?<LoadingState label="Loading executions…"/>:executions.error?<ErrorState error={executions.error} onRetry={executions.reload}/>:null}
   <DataTable caption="Pipeline execution history" rows={executionRows} rowKey={item=>item.execution_id} columns={[
    {key:"execution_id",label:"Execution",render:item=><button className="link-button mono" onClick={()=>setExecutionId(item.execution_id)}>{item.execution_id}</button>},
    {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"revision_id",label:"Revision",render:item=><code>{item.revision_id}</code>},
    {key:"attempt_count",label:"Worker steps",render:item=>item.attempt_count},
    {key:"created_at",label:"Queued",render:item=>stamp(item.created_at)},
    {key:"linked_run_id",label:"Run",render:item=>item.linked_run_id?<code>{item.linked_run_id}</code>:"—"}
   ]} emptyTitle="No executions yet" emptyMessage="Publish a revision, then queue it. A local pipeline worker must be running to process steps."/>
  </Section>
  {execution?<Section title="Execution detail" subtitle={execution.execution_id+" · Started "+stamp(execution.started_at)} actions={<div className="button-row">{canCancel?<Button size="sm" variant="outline" disabled={mutation.loading} onClick={cancel}>Request cancel</Button>:null}{canRecover?<Button size="sm" onClick={recover} disabled={mutation.loading}>Approve recovery</Button>:null}<Button size="sm" variant="outline" onClick={()=>{executions.reload();executionDetail.reload();}}>Refresh detail</Button></div>}>
   <div className="form-grid">
    <div><span className="muted">Execution status</span><p><StatusBadge value={execution.status}/></p></div>
    <div><span className="muted">Linked Run</span><p>{execution.linked_run_id?<code>{execution.linked_run_id}</code>:"Not yet linked"}</p></div>
    <div><span className="muted">Revision hash</span><p><code>{execution.definition_sha256}</code></p></div>
    <div><span className="muted">Last error summary</span><p>{execution.last_error||"—"}</p></div>
   </div>
   <DataTable caption="Pipeline steps" rows={stepRows} rowKey={item=>item.step_key} columns={[
    {key:"ordinal",label:"#",render:item=>item.ordinal+1},{key:"step_key",label:"Step"},{key:"step_type",label:"Type"},
    {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"attempt_count",label:"Attempts",render:item=>item.attempt_count+" / "+item.max_attempts},
    {key:"timeout_seconds",label:"Timeout",render:item=>item.timeout_seconds+" s"},
    {key:"result",label:"Run / policy result",render:item=>{
     const result=item.result||{};
     const policy=result.performance_policy_evaluation;
     const summary=[];
     if(result.run_id)summary.push("Run "+result.run_id);
     if(result.run_outcome)summary.push(result.run_outcome);
     if(policy?.overall)summary.push("Policy "+policy.overall);
     if(result.error_code)summary.push(result.error_code);
     return summary.length?<span className="mono">{summary.join(" · ")}</span>:"—";
    }},
    {key:"last_error",label:"Error",render:item=>item.last_error||"—"}
   ]}/>
   <DataTable caption="Worker attempt history" rows={attemptRows} rowKey={item=>item.step_attempt_id} columns={[
    {key:"step_key",label:"Step"},{key:"attempt_number",label:"Attempt"},{key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"worker_id",label:"Worker"},{key:"started_at",label:"Started",render:item=>stamp(item.started_at)},
    {key:"completed_at",label:"Completed",render:item=>stamp(item.completed_at)},{key:"error_summary",label:"Summary",render:item=>item.error_summary||"—"}
   ]}/>
   {execution.status==="QUEUED"?<InlineNotice tone="info">Queued. Start the local worker with <code>python scripts/netregress_pipeline_worker.py --poll-interval 5</code>.</InlineNotice>:null}
   {execution.status==="RECOVERY_REQUIRED"?<InlineNotice tone="warning">Inspect the actual provider/device state before approving recovery. The dashboard does not assume an interrupted operation failed or automatically repeat it.</InlineNotice>:null}
  </Section>:null}
 </div>;
}
