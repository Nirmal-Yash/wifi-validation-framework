import React,{useEffect,useMemo,useState} from "react";
import {FileCode2,Network,RefreshCw,ShieldCheck,UploadCloud} from "lucide-react";
import {api} from "@/api";
import {useWorkspace} from "@/components/workspace-context";
import {useAsyncLoader} from "@/hooks";
import {canPerform} from "@/permissions";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

const EMPTY_INTENT = {
 schema_version:"1.0",
 targets:[],
 segments:[],
 interfaces:[],
 static_routes:[],
 ospf:[],
 bgp:[],
 aggregations:[],
 firewall_zones:[],
 firewall_rules:[],
 service_references:[],
 linux_bridges:[],
 linux_vlan_interfaces:[],
};

const formatJson=value=>JSON.stringify(value,null,2);

function JsonEditor({value,onChange,disabled}) {
 return <textarea
  aria-label="Canonical network intent JSON"
  className="network-intent-editor"
  spellCheck="false"
  rows={24}
  value={value}
  onChange={event=>onChange(event.target.value)}
  disabled={disabled}
 />;
}

export default function NetworkIntentPage({user}) {
 const workspace=useWorkspace();
 const projectId=workspace.activeProjectId||"";
 const canManage=canPerform(user,"network_intent.manage");
 const canPublish=canPerform(user,"network_intent.publish");
 const canAutomationRead=canPerform(user,"network_automation.read");
 const canAutomationManage=canPerform(user,"network_automation.manage");
 const canAutomationApprove=canPerform(user,"network_automation.approve");
 const canAutomationExecute=canPerform(user,"network_automation.execute");
 const topologyProfiles=useAsyncLoader(
  ()=>projectId?api.topologies(projectId):Promise.resolve({items:[]}),
  [projectId],
  {enabled:Boolean(projectId),queryKey:"network-intent-topology-profiles"},
 );
 const profiles=useAsyncLoader(
  ()=>projectId?api.networkIntentProfiles(projectId):Promise.resolve({items:[]}),
  [projectId],
  {enabled:Boolean(projectId),queryKey:"network-intent-profiles"},
 );
 const compilerAdapters=useAsyncLoader(
  ()=>projectId?api.networkConfigAdapters(projectId):Promise.resolve({items:[]}),
  [projectId],
  {enabled:Boolean(projectId),queryKey:"network-intent-compiler-adapters"},
 );
 const ansiblePlans=useAsyncLoader(
  ()=>projectId&&canAutomationRead?api.networkAnsiblePlans(projectId):Promise.resolve({items:[]}),
  [projectId,canAutomationRead],
  {enabled:Boolean(projectId&&canAutomationRead),queryKey:"network-intent-ansible-plans"},
 );
 const [createTopologyProfileId,setCreateTopologyProfileId]=useState("");
 const [profileName,setProfileName]=useState("Network intent");
 const [profileDescription,setProfileDescription]=useState("");
 const [profileId,setProfileId]=useState("");
 const [topologyRevisionId,setTopologyRevisionId]=useState("");
 const [revisionId,setRevisionId]=useState("");
 const [definitionText,setDefinitionText]=useState(formatJson(EMPTY_INTENT));
 const [evaluateCapabilities,setEvaluateCapabilities]=useState(true);
 const [validation,setValidation]=useState(null);
 const [compilation,setCompilation]=useState(null);
 const [ansibleCredentialBindingsText,setAnsibleCredentialBindingsText]=useState("{}");
 const [ansiblePlanId,setAnsiblePlanId]=useState("");
 const [ansiblePlanResult,setAnsiblePlanResult]=useState(null);
 const [ansibleExecutionResult,setAnsibleExecutionResult]=useState(null);
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const [logicalNodeId,setLogicalNodeId]=useState("");
 const [targetDeviceId,setTargetDeviceId]=useState("");
 const [busyAction,setBusyAction]=useState("");

 const profileRows=profiles.data?.items||[];
 const topologyRows=topologyProfiles.data?.items||[];
 const selectedProfile=profileRows.find(item=>item.profile_id===profileId)||null;
 const topologyProfileId=selectedProfile?.topology_profile_id||createTopologyProfileId;
 const selectedTopology=topologyRows.find(item=>item.profile_id===topologyProfileId)||null;
 const revisions=useAsyncLoader(
  ()=>profileId?api.networkIntentRevisions(profileId):Promise.resolve({items:[]}),
  [profileId],
  {enabled:Boolean(profileId),queryKey:"network-intent-revisions"},
 );
 const topologyRevisions=useAsyncLoader(
  ()=>topologyProfileId?api.topologyRevisions(topologyProfileId):Promise.resolve({items:[]}),
  [topologyProfileId],
  {enabled:Boolean(topologyProfileId),queryKey:"network-intent-topology-revisions"},
 );
 const deviceRows=useAsyncLoader(
  ()=>projectId?api.devices(projectId,selectedTopology?.scope_type==="LAB"?selectedTopology.lab_id:undefined,"ACTIVE"):Promise.resolve({items:[]}),
  [projectId,selectedTopology?.scope_type,selectedTopology?.lab_id],
  {enabled:Boolean(projectId),queryKey:"network-intent-target-devices"},
 );
 const capabilityReports=useAsyncLoader(
  ()=>targetDeviceId?api.deviceCapabilityReports(targetDeviceId):Promise.resolve({items:[]}),
  [targetDeviceId],
  {enabled:Boolean(targetDeviceId),queryKey:"network-intent-capability-reports"},
 );
 const revisionRows=revisions.data?.items||[];
 const topologyRevisionRows=topologyRevisions.data?.items||[];
 const selectedRevision=revisionRows.find(item=>item.revision_id===revisionId)||null;
 const selectedTopologyRevision=topologyRevisionRows.find(item=>item.revision_id===topologyRevisionId)||null;
 const ansiblePlanRows=ansiblePlans.data?.items||[];
 const selectedAnsiblePlan=ansiblePlanRows.find(item=>item.plan_id===ansiblePlanId)||ansiblePlanResult;
 const logicalNodes=selectedTopologyRevision?.definition?.nodes||[];

 useEffect(()=>{
  setProfileId("");
  setRevisionId("");
  setTopologyRevisionId("");
  setCreateTopologyProfileId("");
  setTargetDeviceId("");
  setLogicalNodeId("");
  setValidation(null);
  setCompilation(null);
  setAnsiblePlanId("");
  setAnsiblePlanResult(null);
  setAnsibleExecutionResult(null);
  setError("");
  setNotice("");
  setDefinitionText(formatJson(EMPTY_INTENT));
 },[projectId]);

 useEffect(()=>{
  if(!selectedProfile)return;
  setCreateTopologyProfileId(selectedProfile.topology_profile_id);
  setTopologyRevisionId(current=>{
   if(current&&topologyRevisionRows.some(item=>item.revision_id===current))return current;
   const published=topologyRevisionRows.find(item=>item.status==="PUBLISHED");
   return published?.revision_id||topologyRevisionRows[0]?.revision_id||"";
  });
 },[selectedProfile?.profile_id,topologyRevisionRows]);

 useEffect(()=>{
  if(!selectedRevision)return;
  setTopologyRevisionId(selectedRevision.topology_revision_id);
  setDefinitionText(formatJson(selectedRevision.definition));
  setValidation(null);
 },[selectedRevision?.revision_id]);

 useEffect(()=>{
  if(!topologyProfileId)return;
  if(selectedProfile&&selectedProfile.topology_profile_id===topologyProfileId){
   const pinned=selectedRevision?.topology_revision_id;
   if(pinned&&topologyRevisionRows.some(item=>item.revision_id===pinned)){
    setTopologyRevisionId(pinned);
    return;
   }
  }
  if(!topologyRevisionId||!topologyRevisionRows.some(item=>item.revision_id===topologyRevisionId)){
   const published=topologyRevisionRows.find(item=>item.status==="PUBLISHED");
   setTopologyRevisionId(published?.revision_id||topologyRevisionRows[0]?.revision_id||"");
  }
 },[topologyProfileId,topologyRevisionRows]);

 useEffect(()=>{
  if(!logicalNodeId&&logicalNodes.length)setLogicalNodeId(logicalNodes[0].id);
  else if(logicalNodeId&&!logicalNodes.some(node=>node.id===logicalNodeId))setLogicalNodeId(logicalNodes[0]?.id||"");
 },[logicalNodes,logicalNodeId]);

 const latestCapabilityReports=useMemo(()=>{
  const rows=capabilityReports.data?.items||[];
  return rows;
 },[capabilityReports.data]);

 function parseDefinition() {
  let parsed;
  try{parsed=JSON.parse(definitionText);}
  catch(exc){throw new Error("Network intent JSON is invalid: "+exc.message);}
  if(!parsed||typeof parsed!=="object"||Array.isArray(parsed))throw new Error("Network intent must be a JSON object.");
  return parsed;
 }

 async function runAction(action,success,after) {
  setBusyAction(action);
  setError("");
  setNotice("");
  try{
   const result=await after();
   setNotice(success);
   setValidation(null);
   await profiles.reload().catch(()=>null);
   await revisions.reload().catch(()=>null);
   return result;
  }catch(exc){
   setError(exc.message||"Network intent operation failed.");
   return null;
  }finally{
   setBusyAction("");
  }
 }

 async function createProfile(event) {
  event.preventDefault();
  if(!projectId||!createTopologyProfileId)return;
  const item=await runAction(
   "create-profile",
   "Network intent profile created and bound to the selected topology profile.",
   ()=>api.createNetworkIntentProfile({
    project_id:projectId,
    topology_profile_id:createTopologyProfileId,
    name:profileName.trim(),
    description:profileDescription.trim(),
   }),
  );
  if(item){setProfileId(item.profile_id);setRevisionId("");setDefinitionText(formatJson(EMPTY_INTENT));}
 }

 async function validateIntent() {
  if(!projectId||!topologyRevisionId){setError("Select a topology revision before validating.");return;}
  setBusyAction("validate");
  setError("");
  setNotice("");
  try{
   const result=await api.validateNetworkIntent({
    project_id:projectId,
    profile_id:profileId||undefined,
    topology_revision_id:topologyRevisionId,
    definition:parseDefinition(),
    evaluate_capabilities:evaluateCapabilities,
   });
   setValidation(result);
   setNotice(result.valid
    ?(result.ready_for_compilation?"Intent is structurally valid and capability-compatible.":"Intent structure is valid; capability evaluation is not yet complete.")
    :"Intent validation returned blocking diagnostics.");
  }catch(exc){setError(exc.message||"Network intent validation failed.");}
  finally{setBusyAction("");}
 }

 async function saveDraft(event) {
  event.preventDefault();
  if(!profileId||!topologyRevisionId){setError("Select a Network Intent profile and a topology revision.");return;}
  const item=await runAction(
   "save-revision",
   "Immutable DRAFT revision saved and pinned to the selected topology revision.",
   ()=>api.createNetworkIntentRevision(profileId,{
    topology_revision_id:topologyRevisionId,
    definition:parseDefinition(),
    provenance:{source:"network-intent-editor",schema_version:"1.0"},
    parent_revision_id:selectedRevision?.revision_id||undefined,
   }),
  );
  if(item){setRevisionId(item.revision_id);setDefinitionText(formatJson(item.definition));}
 }

 async function publishRevision() {
  if(!profileId||!revisionId)return;
  const item=await runAction(
   "publish",
   "Network Intent revision published. Publication required a published topology revision and complete observed capability support.",
   ()=>api.publishNetworkIntentRevision(profileId,{revision_id:revisionId}),
  );
  if(item)setRevisionId(item.revision_id);
 }

 async function rollbackRevision() {
  if(!profileId||!revisionId)return;
  const item=await runAction(
   "rollback",
   "Rollback created a new DRAFT revision from the selected published source.",
   ()=>api.rollbackNetworkIntentRevision(profileId,{source_revision_id:revisionId}),
  );
  if(item){setRevisionId(item.revision_id);setDefinitionText(formatJson(item.definition));}
 }

 async function compileRevision() {
  if(!profileId||!selectedRevision||selectedRevision.status!=="PUBLISHED")return;
  setBusyAction("compile");
  setError("");
  setNotice("");
  try{
   const result=await api.compileNetworkIntentRevision(profileId,revisionId);
   setCompilation(result);
   setNotice(result.status==="COMPILED"
    ?"Vendor configuration preview compiled. No device connection or configuration change was performed."
    :"Compilation is blocked. No partial configuration was returned.");
  }catch(exc){setError(exc.message||"Vendor configuration compilation failed.");}
  finally{setBusyAction("");}
 }

 function parseAnsibleCredentialBindings() {
  let value;
  try{value=JSON.parse(ansibleCredentialBindingsText);}
  catch(exc){throw new Error("Ansible credential binding JSON is invalid: "+exc.message);}
  if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("Credential bindings must be a JSON object keyed by managed Device ID.");
  if(Object.keys(value).length===0||Object.values(value).some(item=>typeof item!=="string"||!item.trim()))throw new Error("Provide one non-empty Credential Vault reference for every target Device.");
  return value;
 }

 async function createAnsiblePlan() {
  if(!profileId||!selectedRevision||selectedRevision.status!=="PUBLISHED")return;
  setBusyAction("ansible-plan");
  setError("");
  setNotice("");
  try{
   const item=await api.createNetworkAnsiblePlan(profileId,revisionId,{
    credential_bindings:parseAnsibleCredentialBindings(),
   });
   setAnsiblePlanResult(item);
   setAnsiblePlanId(item.plan_id||"");
   setAnsibleExecutionResult(null);
   await ansiblePlans.reload().catch(()=>null);
   setNotice(item.status==="BLOCKED"
    ?"Ansible plan is blocked by compilation or environment validation. No Device connection was opened."
    :"Ansible plan preview validated. No Device connection or configuration change was performed.");
  }catch(exc){setError(exc.message||"Ansible plan creation failed.");}
  finally{setBusyAction("");}
 }

 async function approveAnsiblePlan() {
  if(!selectedAnsiblePlan?.plan_id||selectedAnsiblePlan.status!=="PREVIEWED")return;
  setBusyAction("ansible-approve");
  setError("");
  setNotice("");
  try{
   const item=await api.approveNetworkAnsiblePlan(selectedAnsiblePlan.plan_id,{
    plan_sha256:selectedAnsiblePlan.plan_sha256,confirmed:true,
   });
   setAnsiblePlanResult(item);
   await ansiblePlans.reload().catch(()=>null);
   setNotice("Hash-pinned Ansible plan approved. Approval does not execute the plan.");
  }catch(exc){setError(exc.message||"Ansible plan approval failed.");}
  finally{setBusyAction("");}
 }

 async function executeAnsiblePlan() {
  if(!selectedAnsiblePlan?.plan_id||selectedAnsiblePlan.status!=="APPROVED")return;
  setBusyAction("ansible-execute");
  setError("");
  setNotice("");
  try{
   const result=await api.executeNetworkAnsiblePlan(selectedAnsiblePlan.plan_id,{
    plan_sha256:selectedAnsiblePlan.plan_sha256,confirmed:true,
   });
   setAnsibleExecutionResult(result);
   await ansiblePlans.reload().catch(()=>null);
   setNotice(result.status==="SUCCEEDED"
    ?"Ansible execution completed and every target passed the configured read-back check."
    :"Ansible execution failed or had incomplete read-back. Reconciliation is required before retrying.");
  }catch(exc){setError(exc.message||"Ansible execution failed.");await ansiblePlans.reload().catch(()=>null);}
  finally{setBusyAction("");}
 }

 function addTargetBinding() {
  if(!logicalNodeId||!targetDeviceId){setError("Choose a logical node and managed Device before adding a target binding.");return;}
  try{
   const parsed=parseDefinition();
   parsed.targets=Array.isArray(parsed.targets)?parsed.targets:[];
   const duplicate=parsed.targets.find(item=>item.device_id===targetDeviceId&&item.logical_node_id!==logicalNodeId);
   if(duplicate)throw new Error("That Device is already bound to another logical node.");
   parsed.targets=parsed.targets.filter(item=>item.logical_node_id!==logicalNodeId);
   parsed.targets.push({logical_node_id:logicalNodeId,device_id:targetDeviceId});
   parsed.targets.sort((a,b)=>a.logical_node_id.localeCompare(b.logical_node_id));
   setDefinitionText(formatJson(parsed));
   setValidation(null);
   setCompilation(null);
   setError("");
   setNotice("Target binding added to the editable intent document. Save a new DRAFT revision to persist it.");
  }catch(exc){setError(exc.message||"Could not add target binding.");}
 }

 const diagnostics=validation?.diagnostics||[];
 const reportColumns=[
  {key:"observed_at",label:"Observed",render:item=>new Date(item.observed_at).toLocaleString()},
  {key:"provider_id",label:"Provider",render:item=>item.provider_id||"Device discovery"},
  {key:"platform",label:"Platform",render:item=><div><strong>{item.platform}</strong><div className="table-secondary">{item.software_version}</div></div>},
  {key:"adapter",label:"Adapter",render:item=>item.adapter_name+" "+item.adapter_version},
  {key:"features",label:"Capabilities",render:item=>{
   const values=Object.values(item.capabilities||{});
   const supported=values.filter(value=>value.status==="SUPPORTED").length;
   const unsupported=values.filter(value=>value.status==="UNSUPPORTED").length;
   return supported+" supported · "+unsupported+" unsupported · "+(values.length-supported-unsupported)+" unreported";
  }},
  {key:"hash",label:"Report SHA-256",render:item=><code title={item.capability_sha256}>{item.capability_sha256.slice(0,12)}…</code>},
 ];

 return <div className="page-stack network-intent-page">
  <div className="module-intro">
   <div className="module-intro-icon"><Network size={19}/></div>
   <div>
    <strong>Canonical intent is separate from topology and vendor configuration</strong>
    <p>Network Intent v1.0 describes the desired network in vendor-neutral terms. It is pinned to an immutable topology revision. Published intent can be compiled into vendor-specific configuration previews. Compilation never connects to or changes a device.</p>
   </div>
  </div>

  {!projectId?<InlineNotice tone="warning">Select a Project in the workspace header before managing Network Intent.</InlineNotice>:null}
  {notice?<InlineNotice tone="success">{notice}</InlineNotice>:null}
  {error?<InlineNotice tone="danger">{error}</InlineNotice>:null}

  <Section title="Intent profile scope" subtitle="Every Network Intent profile inherits the Project/Lab scope of its selected canonical topology profile.">
   {topologyProfiles.loading&&!topologyProfiles.data?<LoadingState label="Loading canonical topology profiles…"/>:null}
   {topologyProfiles.error?<ErrorState error={topologyProfiles.error} onRetry={topologyProfiles.reload}/>:null}
   {profiles.loading&&!profiles.data?<LoadingState label="Loading Network Intent profiles…"/>:null}
   {profiles.error?<ErrorState error={profiles.error} onRetry={profiles.reload}/>:null}
   <div className="form-grid">
    <Field label="Existing Network Intent profile">
     <select aria-label="Network Intent profile" value={profileId} onChange={event=>{setProfileId(event.target.value);setRevisionId("");setValidation(null);}}>
      <option value="">Select a Network Intent profile</option>
      {profileRows.map(item=><option key={item.profile_id} value={item.profile_id}>{item.name} · {item.scope_type} · {item.status}</option>)}
     </select>
    </Field>
    <Field label="Bound topology profile">
     <select aria-label="Bound topology profile" value={createTopologyProfileId} onChange={event=>setCreateTopologyProfileId(event.target.value)} disabled={Boolean(profileId)}>
      <option value="">Select a topology profile</option>
      {topologyRows.map(item=><option key={item.profile_id} value={item.profile_id}>{item.name} · {item.scope_type} · {item.status}</option>)}
     </select>
    </Field>
   </div>
   {selectedProfile?<div className="table-secondary network-intent-binding">
    <span>Project {selectedProfile.project_id}</span><span>Topology {selectedProfile.topology_profile_id}</span><span>Scope {selectedProfile.scope_type} · {selectedProfile.scope_id}</span>
   </div>:null}
  </Section>

  {!profileId&&canManage?<Section title="Create Network Intent profile" subtitle="Create a new profile bound to an existing active topology profile.">
   <form className="form-grid" onSubmit={createProfile}>
    <Field label="Profile name" required><input aria-label="Network intent profile name" maxLength={120} value={profileName} onChange={event=>setProfileName(event.target.value)} required/></Field>
    <Field label="Description"><input aria-label="Network intent profile description" maxLength={500} value={profileDescription} onChange={event=>setProfileDescription(event.target.value)}/></Field>
    <div className="form-actions"><Button type="submit" loading={busyAction==="create-profile"} disabled={!projectId||!createTopologyProfileId||!profileName.trim()}>Create intent profile</Button></div>
   </form>
   {!topologyRows.length?<EmptyState title="No topology profiles" message="Create a canonical topology profile in Topology Studio before creating Network Intent."/>:null}
  </Section>:null}

  <Section title="Topology revision binding" subtitle="Network Intent revisions reference a specific immutable topology revision, never a provider resource ID.">
   <div className="form-grid">
    <Field label="Topology revision">
     <select aria-label="Network intent topology revision" value={topologyRevisionId} onChange={event=>{setTopologyRevisionId(event.target.value);setValidation(null);}}>
      <option value="">Select topology revision</option>
      {topologyRevisionRows.map(item=><option key={item.revision_id} value={item.revision_id}>#{item.revision_number} · {item.status} · {item.content_sha256?.slice(0,12)}</option>)}
     </select>
    </Field>
    <Field label="Intent revision">
     <select aria-label="Network intent revision" value={revisionId} onChange={event=>{setRevisionId(event.target.value);setValidation(null);}}>
      <option value="">Select or create a revision</option>
      {revisionRows.map(item=><option key={item.revision_id} value={item.revision_id}>#{item.revision_number} · {item.status} · {item.intent_sha256?.slice(0,12)}</option>)}
     </select>
    </Field>
   </div>
   {selectedTopologyRevision?<div className="table-secondary network-intent-binding">
    <span>Topology SHA-256 · {selectedTopologyRevision.content_sha256}</span>
    <span>{selectedTopologyRevision.definition?.nodes?.length||0} logical nodes · {selectedTopologyRevision.definition?.links?.length||0} links</span>
   </div>:null}
  </Section>

  <Section title="Logical-node target binding" subtitle="Target bindings connect logical topology node IDs to managed Device IDs. The logical IDs remain canonical; the Device records supply capability observations.">
   <div className="form-grid">
    <Field label="Logical topology node">
     <select aria-label="Intent logical node" value={logicalNodeId} onChange={event=>setLogicalNodeId(event.target.value)}>
      <option value="">Select logical node</option>
      {logicalNodes.map(item=><option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}
     </select>
    </Field>
    <Field label="Managed Device">
     <select aria-label="Intent target Device" value={targetDeviceId} onChange={event=>setTargetDeviceId(event.target.value)}>
      <option value="">Select managed Device</option>
      {(deviceRows.data?.items||[]).map(item=><option key={item.device_id} value={item.device_id}>{item.name} · {item.device_key} · {item.vendor||"Vendor unknown"}</option>)}
     </select>
    </Field>
    <div className="form-actions"><Button type="button" variant="outline" disabled={!canManage||!topologyRevisionId||!targetDeviceId||!logicalNodeId} onClick={addTargetBinding}>Add target binding to JSON</Button></div>
   </div>
   <p className="muted">A capability report must come from a supported provider/device discovery adapter. The UI cannot manually declare a device feature as supported.</p>
  </Section>

  <Section title="Canonical network intent v1.0" subtitle="Edit the strict JSON contract. Unknown fields, invalid addresses, out-of-range VLANs, dangling references and inline secrets are rejected by the backend.">
   <JsonEditor value={definitionText} onChange={value=>{setDefinitionText(value);setValidation(null);}} disabled={!canManage}/>
   <div className="form-grid network-intent-actions">
    <Field label="Capability-aware validation">
     <label className="network-intent-checkbox"><input type="checkbox" checked={evaluateCapabilities} onChange={event=>setEvaluateCapabilities(event.target.checked)}/> Require observed target capability support</label>
    </Field>
    <div className="form-actions">
     <Button type="button" variant="outline" loading={busyAction==="validate"} disabled={!projectId||!topologyRevisionId} onClick={validateIntent}><ShieldCheck size={14}/>Validate intent</Button>
     {canManage?<Button type="button" loading={busyAction==="save-revision"} disabled={!profileId||!topologyRevisionId} onClick={saveDraft}><UploadCloud size={14}/>Save DRAFT revision</Button>:null}
     {canPublish&&selectedRevision?.status==="DRAFT"?<Button type="button" loading={busyAction==="publish"} onClick={publishRevision}>Publish revision</Button>:null}\n     {canManage&&selectedRevision?.status==="PUBLISHED"?<Button type="button" variant="outline" loading={busyAction==="compile"} onClick={compileRevision}><FileCode2 size={14}/>Compile vendor preview</Button>:null}
     {canManage&&selectedRevision?.status==="PUBLISHED"?<Button type="button" variant="outline" loading={busyAction==="rollback"} onClick={rollbackRevision}>Create rollback draft</Button>:null}
    </div>
   </div>
   {validation?<div className="network-intent-validation" aria-live="polite">
    <div className="network-intent-validation-heading">
     <strong>Validation result</strong>
     <StatusBadge value={validation.capability_status||"UNKNOWN"}/>
    </div>
    <p>{validation.valid?"Structural validation passed.":"Validation contains blocking errors."} {validation.ready_for_compilation?"Observed capabilities are compatible.":"Compilation readiness is not established."}</p>
    {validation.intent_sha256?<p className="table-secondary">Intent SHA-256 · {validation.intent_sha256}</p>:null}
    {validation.required_capabilities?Object.entries(validation.required_capabilities).map(([node,features])=><p className="table-secondary" key={node}>{node} · {features.join(", ")}</p>):null}
    {diagnostics.length?<ul className="network-intent-diagnostics">{diagnostics.map((item,index)=><li key={item.code+"-"+index}><strong>{item.code}</strong> · {item.message}</li>)}</ul>:<p className="table-secondary">No blocking diagnostics.</p>}
   </div>:null}
  </Section>

  <Section title="Revision history" subtitle="Published intent revisions are immutable. Rollback creates a new DRAFT revision rather than rewriting history." actions={<Button size="sm" variant="outline" onClick={()=>revisions.reload()} disabled={!profileId}><RefreshCw size={14}/>Refresh</Button>}>
   {!profileId?<EmptyState title="Select or create a profile" message="Choose a Network Intent profile to inspect its revision history."/>:revisions.loading&&!revisions.data?<LoadingState label="Loading Network Intent revisions…"/>:revisions.error?<ErrorState error={revisions.error} onRetry={revisions.reload}/>:<DataTable caption="Network Intent revision history" rows={revisionRows} rowKey={item=>item.revision_id} columns={[
    {key:"revision_number",label:"Revision",render:item=><strong>#{item.revision_number}</strong>},
    {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"topology_revision_id",label:"Topology revision",render:item=><code>{item.topology_revision_id}</code>},
    {key:"intent_sha256",label:"Intent SHA-256",render:item=><code title={item.intent_sha256}>{item.intent_sha256.slice(0,12)}…</code>},
    {key:"created_at",label:"Created",render:item=>new Date(item.created_at).toLocaleString()},
    {key:"actions",label:"Action",render:item=><Button size="sm" variant="outline" onClick={()=>setRevisionId(item.revision_id)}>Select</Button>},
   ]} emptyTitle="No intent revisions" emptyMessage="Save a DRAFT revision from the editor to begin the version history."/>}
  </Section>

  <Section title="Vendor configuration compilation preview" subtitle="Deterministic, read-only compilation of the selected PUBLISHED revision. Artifacts are previews only; this stage never applies configuration to devices.">
   {!selectedRevision||selectedRevision.status!=="PUBLISHED"?<EmptyState title="Publish a revision to compile" message="Select a published immutable Network Intent revision. Drafts and unsaved editor changes cannot be compiled."/>:null}
   {compilation?<div className="network-intent-validation" aria-live="polite">
    <div className="network-intent-validation-heading">
     <strong>Compilation result</strong>
     <StatusBadge value={compilation.status}/>
    </div>
    <p>{compilation.status==="COMPILED"?"All target devices compiled successfully.":"Compilation was blocked; no partial artifact set was returned."} Device application: not performed.</p>
    {compilation.compilation_id?<p className="table-secondary">Compilation ID · <code>{compilation.compilation_id}</code></p>:null}
    {compilation.adapters?.map(item=><p className="table-secondary" key={item.adapter_id}>{item.name} · {item.version} · {item.output_format}</p>)}
    {compilation.change_summary?<p className="table-secondary">Artifacts · {compilation.change_summary.new} new · {compilation.change_summary.changed} changed · {compilation.change_summary.unchanged} unchanged</p>:null}
    {(compilation.diagnostics||[]).length?<ul className="network-intent-diagnostics">{compilation.diagnostics.map((item,index)=><li key={item.code+"-"+index}><strong>{item.code}</strong> · {item.message}</li>)}</ul>:null}
    {compilation.artifacts?.map(item=><details className="network-intent-artifact" key={item.path}>
     <summary><strong>{item.change_type}</strong> · <code>{item.path}</code> · <span className="table-secondary">SHA-256 {item.sha256.slice(0,12)}…</span></summary>
     <pre>{item.content}</pre>
     {item.diff?<details><summary>Configuration diff</summary><pre>{item.diff}</pre></details>:null}
    </details>)}
    {compilation.orphaned_baseline_files?.length?<p className="table-secondary">Baseline-only files were not deleted: {compilation.orphaned_baseline_files.join(", ")}</p>:null}
   </div>:<p className="muted">No compilation preview has been generated for this selected revision.</p>}
  </Section>

  <Section title="Ansible automation" subtitle="Generate a target-scoped playbook from the published P09 compiler artifacts. Preview and approval are separate; execution may change live configuration and must be explicitly approved.">
   {!canAutomationRead?<InlineNotice tone="warning">Ansible plan history requires network_automation.read permission.</InlineNotice>:null}
   {canAutomationRead?<div className="form-grid">
    <Field label="Credential Vault references by Device ID">
     <textarea
      aria-label="Ansible credential bindings JSON"
      className="network-intent-editor"
      rows={5}
      spellCheck="false"
      value={ansibleCredentialBindingsText}
      onChange={event=>setAnsibleCredentialBindingsText(event.target.value)}
      disabled={!canAutomationManage}
     />
    </Field>
    <p className="muted">Enter a JSON object mapping each target Device ID to its active same-Device SSH_PASSWORD or SSH_PRIVATE_KEY credential ID. Secret values are never accepted here or persisted in the plan.</p>
    <div className="form-actions">
     {canAutomationManage?<Button type="button" loading={busyAction==="ansible-plan"} disabled={!profileId||selectedRevision?.status!=="PUBLISHED"} onClick={createAnsiblePlan}>Create Ansible plan preview</Button>:null}
    </div>
   </div>:null}
   {ansiblePlanResult&&!ansiblePlanResult.plan_id?<div className="network-intent-validation" aria-live="polite">
    <div className="network-intent-validation-heading"><strong>Plan creation result</strong><StatusBadge value={ansiblePlanResult.status||"BLOCKED"}/></div>
    {(ansiblePlanResult.diagnostics||[]).map((item,index)=><p key={item.code+"-"+index}><strong>{item.code}</strong> · {item.message}</p>)}
   </div>:null}
   {canAutomationRead&&ansiblePlans.loading&&!ansiblePlans.data?<LoadingState label="Loading Ansible automation plans…"/>:null}
   {canAutomationRead&&ansiblePlans.error?<ErrorState error={ansiblePlans.error} onRetry={ansiblePlans.reload}/>:null}
   {canAutomationRead?<DataTable caption="Ansible automation plans" rows={ansiblePlanRows} rowKey={item=>item.plan_id} columns={[
    {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"revision_id",label:"Intent revision",render:item=><code>{item.revision_id}</code>},
    {key:"plan_sha256",label:"Plan SHA-256",render:item=><code title={item.plan_sha256}>{item.plan_sha256.slice(0,12)}…</code>},
    {key:"created_at",label:"Created",render:item=>new Date(item.created_at).toLocaleString()},
    {key:"actions",label:"Action",render:item=><Button size="sm" variant="outline" onClick={()=>{setAnsiblePlanId(item.plan_id);setAnsiblePlanResult(null);setAnsibleExecutionResult(null);}}>Select</Button>},
   ]} emptyTitle="No Ansible plans" emptyMessage="Create a plan from a published Network Intent revision and scoped Credential Vault references."/>:null}
   {selectedAnsiblePlan?.plan_id?<div className="network-intent-validation" aria-live="polite">
    <div className="network-intent-validation-heading"><strong>Selected Ansible plan</strong><StatusBadge value={selectedAnsiblePlan.status}/></div>
    <p>Plan ID · <code>{selectedAnsiblePlan.plan_id}</code></p>
    <p>Plan SHA-256 · <code>{selectedAnsiblePlan.plan_sha256}</code></p>
    <p>{selectedAnsiblePlan.validation?.message||"Plan syntax and inventory validation result."} {selectedAnsiblePlan.validation?.ansible_core?("Ansible Core "+selectedAnsiblePlan.validation.ansible_core):""}</p>
    {selectedAnsiblePlan.plan?.playbook_yaml?<details className="network-intent-artifact"><summary>Review generated Ansible playbook</summary><pre>{selectedAnsiblePlan.plan.playbook_yaml}</pre></details>:null}
    {selectedAnsiblePlan.plan?.inventory?<details className="network-intent-artifact"><summary>Review scoped inventory (vault secrets excluded)</summary><pre>{JSON.stringify(selectedAnsiblePlan.plan.inventory,null,2)}</pre></details>:null}
    {selectedAnsiblePlan.plan?.targets?.map(target=><p className="table-secondary" key={target.device_id}>{target.name} · {target.adapter_id} · {target.host}:{target.port} · {target.credential_type} vault reference · Read-back: {target.readback_method}</p>)}
    {(selectedAnsiblePlan.validation?.detail||selectedAnsiblePlan.validation?.message)&&selectedAnsiblePlan.status==="BLOCKED"?<p className="table-secondary">{selectedAnsiblePlan.validation.detail||selectedAnsiblePlan.validation.message}</p>:null}
    <div className="form-actions">
     {canAutomationApprove&&selectedAnsiblePlan.status==="PREVIEWED"&&selectedAnsiblePlan.created_by!==user?.username?<Button type="button" loading={busyAction==="ansible-approve"} onClick={approveAnsiblePlan}>Approve hash-pinned plan</Button>:null}
     {canAutomationExecute&&selectedAnsiblePlan.status==="APPROVED"?<Button type="button" loading={busyAction==="ansible-execute"} onClick={executeAnsiblePlan}>Execute approved plan</Button>:null}
    </div>
    {selectedAnsiblePlan.status==="PREVIEWED"&&selectedAnsiblePlan.created_by===user?.username?<p className="muted">The plan creator cannot approve their own change; a different ADMIN or OWNER must review the exact plan hash.</p>:null}
    {selectedAnsiblePlan.status==="STALE"?<p className="muted">This approved plan is stale because its source capabilities or compiled output changed. Create a fresh plan and obtain a new independent approval.</p>:null}
    {selectedAnsiblePlan.status==="APPROVED"?<p className="muted">Approval is bound to the exact plan SHA-256. Execution revalidates the source revision and current capabilities before opening any Device connection.</p>:null}
    {selectedAnsiblePlan.executions?.map(execution=><div className="table-secondary" key={execution.execution_id}>
     <p>Execution · <code>{execution.execution_id}</code> · <StatusBadge value={execution.status}/></p>
     <p>{execution.result?.verified_device_count||0}/{execution.result?.target_count||0} Devices verified · {execution.result?.readback_status||"NOT_RUN"}</p>
     {execution.result?.reconciliation_required?<p><strong>Reconciliation required.</strong> Partial configuration changes may have occurred; automatic retry is disabled.</p>:null}
     {execution.result?.diagnostic?<p>{execution.result.diagnostic}</p>:null}
    </div>)}
    {ansibleExecutionResult?<p className="table-secondary">Latest execution request · {ansibleExecutionResult.status}</p>:null}
   </div>:null}
   <p className="muted">Initial live execution support: Linux/FRR over SSH, Cisco IOS/IOS-XE and Arista EOS over network_cli. Juniper Junos and Palo Alto PAN-OS remain compile-only until their separate NETCONF/API transports are qualified. Linux execution requires non-interactive sudo privileges. The first run must trust the Device's SSH host key in the operator's known_hosts file.</p>
  </Section>

  <Section title="Registered vendor compilers" subtitle="Compiler availability is advertised independently of topology emulator providers. Software versions are gated by the registered tested range; device changes are not performed here.">
   {compilerAdapters.loading&&!compilerAdapters.data?<LoadingState label="Loading registered compilers…"/>:null}
   {compilerAdapters.error?<ErrorState error={compilerAdapters.error} onRetry={compilerAdapters.reload}/>:null}
   <DataTable caption="Registered network configuration adapters" rows={compilerAdapters.data?.items||[]} rowKey={item=>item.adapter_id} columns={[
    {key:"name",label:"Adapter",render:item=><strong>{item.name}</strong>},
    {key:"platform_family",label:"Observed platform"},
    {key:"supported_versions",label:"Version gate"},
    {key:"output_format",label:"Output format"},
    {key:"version",label:"Adapter version",render:item=><code>{item.version}</code>},
   ]} emptyTitle="No registered compilers" emptyMessage="No vendor configuration adapters are registered."/>
  </Section>

  <Section title="Observed Device capability reports" subtitle="Append-only adapter observations. Missing features remain UNKNOWN; UNSUPPORTED features block capability-aware validation.">
   {targetDeviceId?<div className="table-secondary">Selected Device · {targetDeviceId}</div>:<p className="muted">Select a managed Device in the target-binding section to inspect its observed capability history.</p>}
   {targetDeviceId&&capabilityReports.loading&&!capabilityReports.data?<LoadingState label="Loading capability observations…"/>:null}
   {targetDeviceId&&capabilityReports.error?<ErrorState error={capabilityReports.error} onRetry={capabilityReports.reload}/>:null}
   {targetDeviceId&&!capabilityReports.loading&&!capabilityReports.error?<DataTable caption="Device capability observations" rows={latestCapabilityReports} rowKey={item=>item.report_id} columns={reportColumns} emptyTitle="No observed capability reports" emptyMessage="The selected Device has not yet been inspected by a capability-aware provider or device discovery adapter."/>:null}
  </Section>
 </div>;
}
