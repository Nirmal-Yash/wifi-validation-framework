import React,{useCallback,useEffect,useMemo,useState} from "react";
import {api} from "@/api";
import {useWorkspace} from "@/components/workspace-context";
import {canPerform} from "@/permissions";
import {Button,DataTable,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

const EMPTY_VARIABLES = "{\n  \"region\": \"\"\n}";
const stamp=value=>value?new Date(value).toLocaleString():"—";

export default function InfrastructurePage({user}) {
 const workspaceContext=useWorkspace();
 const projectId=workspaceContext.activeProjectId||"";
 const labId=workspaceContext.activeLabId||"";
 const canRead=canPerform(user,"infrastructure.read");
 const canManage=canPerform(user,"infrastructure.manage");
 const canApprove=canPerform(user,"infrastructure.approve");
 const canExecute=canPerform(user,"infrastructure.execute");
 const canDestroy=canPerform(user,"infrastructure.destroy");
 const [modules,setModules]=useState([]);
 const [workspaces,setWorkspaces]=useState([]);
 const [plans,setPlans]=useState([]);
 const [moduleKey,setModuleKey]=useState("");
 const [name,setName]=useState("Lab infrastructure");
 const [variablesText,setVariablesText]=useState(EMPTY_VARIABLES);
 const [workspaceId,setWorkspaceId]=useState("");
 const [planId,setPlanId]=useState("");
 const [stateResult,setStateResult]=useState(null);
 const [loading,setLoading]=useState(false);
 const [busy,setBusy]=useState("");
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");

 const selectedWorkspace=workspaces.find(item=>item.workspace_id===workspaceId)||null;
 const selectedPlan=plans.find(item=>item.plan_id===planId)||null;
 const planRows=useMemo(()=>plans.map(item=>({...item,created_label:stamp(item.created_at)})),[plans]);

 const refresh=useCallback(async()=>{
  if(!projectId){setModules([]);setWorkspaces([]);setPlans([]);return;}
  setLoading(true);setError("");
  try{
   const [moduleResult,workspaceResult,planResult]=await Promise.all([
    api.infrastructureModules(projectId),
    api.infrastructureWorkspaces(projectId,labId||undefined),
    api.infrastructurePlans(projectId),
   ]);
   setModules(moduleResult.items||[]);
   setWorkspaces(workspaceResult.items||[]);
   setPlans(planResult.items||[]);
   setWorkspaceId(current=>current&&(workspaceResult.items||[]).some(item=>item.workspace_id===current)?current:(workspaceResult.items?.[0]?.workspace_id||""));
   setPlanId(current=>current&&(planResult.items||[]).some(item=>item.plan_id===current)?current:"");
  }catch(exc){setError(exc.message||"Infrastructure data could not be loaded.");}
  finally{setLoading(false);}
 },[projectId,labId]);
 useEffect(()=>{refresh();},[refresh]);

 async function act(key,success,callback) {
  setBusy(key);setNotice("");setError("");
  try{
   const result=await callback();
   setNotice(success);
   await refresh();
   return result;
  }catch(exc){setError(exc.message||"Infrastructure operation failed.");return null;}
  finally{setBusy("");}
 }
 async function createWorkspace(event) {
  event.preventDefault();
  if(!projectId||!labId){setError("Select a Project and Lab in the workspace selector before creating infrastructure.");return;}
  let variables;
  try{variables=JSON.parse(variablesText);}catch(exc){setError("Variables must be valid JSON: "+exc.message);return;}
  const item=await act("workspace-create","Isolated OpenTofu workspace created.",()=>api.createInfrastructureWorkspace({
   project_id:projectId,lab_id:labId,name:name.trim(),module_key:moduleKey,variables,
  }));
  if(item?.workspace_id)setWorkspaceId(item.workspace_id);
 }
 async function createPlan(kind="APPLY") {
  if(!selectedWorkspace)return;
  if(kind==="DESTROY"&&!window.confirm("Create a destroy plan for this Lab infrastructure? Review the exact resource actions before approval."))return;
  const item=await act("plan-create","OpenTofu plan created for review.",()=>api.createInfrastructurePlan(selectedWorkspace.workspace_id,kind));
  if(item?.plan_id)setPlanId(item.plan_id);
 }
 async function approvePlan() {
  if(!selectedPlan||!window.confirm("Approve this exact plan SHA-256 independently? This does not apply infrastructure."))return;
  const item=await act("plan-approve","Plan approval recorded.",()=>api.approveInfrastructurePlan(selectedPlan.plan_id,{
   plan_sha256:selectedPlan.plan_sha256,confirmed:true,
  }));
  if(item?.plan_id)setPlanId(item.plan_id);
 }
 async function applyPlan() {
  if(!selectedPlan)return;
  if(selectedPlan.kind==="DESTROY"&&!canDestroy)return;
  if(!window.confirm("Apply the approved OpenTofu binary plan with SHA-256 "+selectedPlan.plan_sha256+"?"))return;
  const item=await act("plan-apply","OpenTofu apply finished and evidence was persisted.",()=>api.applyInfrastructurePlan(selectedPlan.plan_id,{
   plan_sha256:selectedPlan.plan_sha256,confirmed:true,
  }));
  if(item?.plan_id)setPlanId(item.plan_id);
 }
 async function inspectState() {
  if(!selectedWorkspace)return;
  setBusy("inspect");setError("");
  try{setStateResult(await api.infrastructureState(selectedWorkspace.workspace_id));}
  catch(exc){setError(exc.message||"OpenTofu state inspection failed.");}
  finally{setBusy("");}
 }

 if(!canRead)return <Section title="Infrastructure access restricted" subtitle="Your role does not have infrastructure.read in the selected Project."/>;
 if(!projectId)return <Section title="Infrastructure automation" subtitle="Select a Project and Lab in the workspace selector to begin."/>;
 return <div className="page-stack">
  <div className="module-intro"><div className="module-intro-icon">⌘</div><div><strong>Infrastructure provisioning and state management</strong><p>OpenTofu owns infrastructure resources; Ansible remains the separate device-configuration layer. Workspaces are isolated per Lab, and no plan is applied without independent approval and explicit confirmation.</p></div></div>
  {notice?<InlineNotice tone="success">{notice}</InlineNotice>:null}
  {error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  <Section title="Operator-managed OpenTofu modules" subtitle="The catalogue is read-only. Install and maintain trusted modules under NETREGRESS_OPENTOFU_MODULE_ROOT on the Runner host." actions={<Button size="sm" variant="outline" onClick={refresh} disabled={loading}>Refresh</Button>}>
   {loading&&!modules.length?<LoadingState label="Loading module catalogue…"/>:null}
   <DataTable caption="Approved local modules" rows={modules} rowKey={item=>item.module_key} columns={[
    {key:"module_key",label:"Module",render:item=><strong>{item.module_key}</strong>},
    {key:"file_count",label:"Files"},
    {key:"module_sha256",label:"Source SHA-256",render:item=><code title={item.module_sha256}>{item.module_sha256.slice(0,16)}…</code>},
   ]} emptyTitle="No approved modules" emptyMessage="Configure the operator-managed module root and add a reviewed local OpenTofu module."/>
   {canManage?<form className="form-grid" onSubmit={createWorkspace}>
    <Field label="Workspace name" required><input value={name} onChange={event=>setName(event.target.value)} maxLength={120} required/></Field>
    <Field label="OpenTofu module" required><select value={moduleKey} onChange={event=>setModuleKey(event.target.value)} required><option value="">Choose approved module</option>{modules.map(item=><option key={item.module_key} value={item.module_key}>{item.module_key}</option>)}</select></Field>
    <Field label="Non-secret variables JSON" className="full-width" hint="Secret-like keys are rejected. Keep provider credentials in the operator's approved process identity; never paste secrets here."><textarea rows={6} value={variablesText} onChange={event=>setVariablesText(event.target.value)} spellCheck="false"/></Field>
    <div className="full-width"><Button type="submit" disabled={!labId||!moduleKey||!name.trim()} loading={busy==="workspace-create"}>Create isolated Lab workspace</Button></div>
   </form>:<p className="muted">Workspace creation requires infrastructure.manage.</p>}
   {!labId?<InlineNotice tone="info">Choose a Lab in the global workspace selector to create a new workspace. Existing Project workspaces remain visible.</InlineNotice>:null}
  </Section>
  <Section title="Lab workspaces" subtitle={workspaces.length+" workspace(s) in the selected Project/Lab scope."}>
   {loading&&!workspaces.length?<LoadingState label="Loading infrastructure workspaces…"/>:null}
   <DataTable caption="OpenTofu workspace records" rows={workspaces} rowKey={item=>item.workspace_id} columns={[
    {key:"name",label:"Workspace",render:item=><strong>{item.name}</strong>},
    {key:"lab_id",label:"Lab",render:item=><code>{item.lab_id}</code>},
    {key:"module_key",label:"Module"},
    {key:"module_sha256",label:"Module snapshot",render:item=><code>{item.module_sha256.slice(0,12)}…</code>},
    {key:"status",label:"State",render:item=><StatusBadge value={item.status}/>},
    {key:"created_at",label:"Created",render:item=>stamp(item.created_at)},
    {key:"select",label:"Action",render:item=><Button size="sm" variant="outline" onClick={()=>{setWorkspaceId(item.workspace_id);setStateResult(null);}}>Select</Button>},
   ]} emptyTitle="No Lab workspaces" emptyMessage="Create a workspace from an operator-managed module to begin planning infrastructure."/>
   {selectedWorkspace?<div className="module-intro"><div><strong>{selectedWorkspace.name}</strong><p><code>{selectedWorkspace.workspace_id}</code> · {selectedWorkspace.module_key} · <StatusBadge value={selectedWorkspace.status}/></p></div></div>:null}
   {selectedWorkspace&&canManage?<div className="button-row">
    <Button size="sm" onClick={()=>createPlan("APPLY")} disabled={busy!==""||selectedWorkspace.status!=="ACTIVE"}>Validate and create plan</Button>
    {canDestroy?<Button size="sm" variant="outline" onClick={()=>createPlan("DESTROY")} disabled={busy!==""||selectedWorkspace.status==="DESTROYED"}>Create destroy plan</Button>:null}
    <Button size="sm" variant="outline" onClick={inspectState} disabled={busy!==""||selectedWorkspace.status==="DESTROYED"} loading={busy==="inspect"}>Inspect state</Button>
   </div>:null}
   {selectedWorkspace?.status==="RECOVERY_REQUIRED"?<InlineNotice tone="warning">A previous apply may have partially changed infrastructure. Normal plans are blocked until a separately reviewed P12 reconciliation and recovery path is completed.</InlineNotice>:null}
   {stateResult?<div className="network-intent-validation" aria-live="polite"><strong>State inspection</strong><p>{stateResult.resource_count} resource address(es) · Raw state values exposed: No</p><DataTable caption="Observed resource addresses" rows={(stateResult.resource_addresses||[]).map(address=>({address}))} rowKey={item=>item.address} columns={[{key:"address",label:"Resource address",render:item=><code>{item.address}</code>}]} emptyTitle="No resources in state" emptyMessage="The workspace currently reports no managed resource addresses."/></div>:null}
  </Section>
  <Section title="Plan review and execution" subtitle="Binary plan files remain private and are SHA-256 verified. Review, approval and execution are separate actions.">
   <DataTable caption="Infrastructure plan history" rows={planRows} rowKey={item=>item.plan_id} columns={[
    {key:"kind",label:"Kind",render:item=>item.kind||"APPLY"},
    {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"plan_sha256",label:"Plan SHA-256",render:item=><code title={item.plan_sha256}>{item.plan_sha256.slice(0,16)}…</code>},
    {key:"created_by",label:"Created by"},
    {key:"created_label",label:"Created"},
    {key:"action",label:"Action",render:item=><Button size="sm" variant="outline" onClick={()=>setPlanId(item.plan_id)}>Review</Button>},
   ]} emptyTitle="No plans" emptyMessage="Create a plan for a selected workspace. Plans do not mutate infrastructure."/>
   {selectedPlan?<div className="network-intent-validation" aria-live="polite">
    <div className="network-intent-validation-heading"><strong>Selected plan</strong><StatusBadge value={selectedPlan.status}/></div>
    <p>Plan · <code>{selectedPlan.plan_id}</code> · {selectedPlan.kind}</p>
    <p>SHA-256 · <code>{selectedPlan.plan_sha256}</code></p>
    <p>{selectedPlan.summary?.resource_change_count||0} resource change(s). Review actions below before requesting approval.</p>
    <DataTable caption="Planned resource actions" rows={selectedPlan.summary?.resources||[]} rowKey={item=>item.address} columns={[
     {key:"address",label:"Resource address",render:item=><code>{item.address}</code>},
     {key:"resource_type",label:"Type"},
     {key:"actions",label:"Actions",render:item=>(item.actions||[]).join(" → ")},
    ]} emptyTitle="No resource changes" emptyMessage="This plan contains no resource actions."/>
    <div className="button-row">
     {canApprove&&selectedPlan.status==="PREVIEWED"&&selectedPlan.created_by!==user?.username?<Button size="sm" onClick={approvePlan} disabled={busy!==""} loading={busy==="plan-approve"}>Approve exact plan hash</Button>:null}
     {canExecute&&selectedPlan.status==="APPROVED"&&(selectedPlan.kind!=="DESTROY"||canDestroy)?<Button size="sm" onClick={applyPlan} disabled={busy!==""} loading={busy==="plan-apply"}>Apply approved plan</Button>:null}
    </div>
    {selectedPlan.status==="PREVIEWED"&&selectedPlan.created_by===user?.username?<p className="muted">The plan creator cannot approve their own change. Another authorized reviewer must approve this exact SHA-256.</p>:null}
    {selectedPlan.executions?.map(item=><p key={item.execution_id} className="table-secondary">Execution <code>{item.execution_id}</code> · {item.status} · {item.result?.recovery_required?"Recovery required":item.result?.success?"Applied":"Pending"}</p>)}
   </div>:null}
  </Section>
  <p className="muted">P11 uses an operator-managed local module catalogue and local backend. Remote state, live cloud qualification, automatic rollback and provider-side recovery are not claimed. A failed apply blocks subsequent normal plans until explicit P12 recovery.</p>
 </div>;
}
