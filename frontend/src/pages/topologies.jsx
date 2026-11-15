import React,{useEffect,useState} from "react";
import {api} from "@/api";
import {useAsyncLoader,useMutation} from "@/hooks";
import {canPerform} from "@/permissions";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

const NODE_TYPES=["ROUTER","SWITCH","ACCESS_POINT","CLIENT","MONITOR","CLOUD","OTHER"];
const emptyDefinition=()=>({nodes:[],links:[]});
const localId=prefix=>prefix+"-"+(globalThis.crypto?.randomUUID?globalThis.crypto.randomUUID().slice(0,12):Math.random().toString(36).slice(2,14));

export default function TopologyStudioPage({user}){
 const projects=useAsyncLoader(()=>api.workspaceProjects(),[],{queryKey:"topology-studio-projects"});
 const [projectId,setProjectId]=useState("");
 const [profileId,setProfileId]=useState("");
 const [revisionId,setRevisionId]=useState("");
 const [scope,setScope]=useState({scope_type:"PROJECT",scope_id:""});
 const [profileForm,setProfileForm]=useState({name:"Wireless topology",description:""});
 const [nodeForm,setNodeForm]=useState({node_type:"ROUTER",name:"Router",template_id:"",x:160,y:180});
 const [linkForm,setLinkForm]=useState({source_node_id:"",source_adapter:0,source_port:0,target_node_id:"",target_adapter:0,target_port:0});
 const [definition,setDefinition]=useState(emptyDefinition);
 const [selectedNode,setSelectedNode]=useState("");
 const [dragging,setDragging]=useState("");
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const [showProfileForm,setShowProfileForm]=useState(false);
 const profiles=useAsyncLoader(()=>projectId?api.topologies(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"topology-studio-profiles"});
 const revisions=useAsyncLoader(()=>profileId?api.topologyRevisions(profileId):Promise.resolve({items:[]}),[profileId],{enabled:Boolean(profileId),queryKey:"topology-studio-revisions"});
 const mutation=useMutation();
 const projectRows=projects.data?.items||[];
 const profileRows=profiles.data?.items||[];
 const revisionRows=revisions.data?.items||[];
 const nodes=definition.nodes||[];
 const links=definition.links||[];
 const selectedRevision=revisionRows.find(item=>item.revision_id===revisionId)||null;
 const activeProfile=profileRows.find(item=>item.profile_id===profileId)||null;
 const activeLabId=activeProfile?.scope_type==="LAB"?activeProfile.lab_id:"";
 const [bindingForm,setBindingForm]=useState({endpoint_url:"http://127.0.0.1:3080",gns3_project_id:"",controller_device_id:"",credential_id:""});
 const providerBinding=useAsyncLoader(()=>activeLabId?api.topologyProviderBinding(activeLabId):Promise.resolve({binding:null}),[activeLabId],{enabled:Boolean(activeLabId),queryKey:"topology-provider-binding"});
 const applyHistory=useAsyncLoader(()=>profileId&&activeLabId?api.topologyApplies(profileId):Promise.resolve({items:[]}),[profileId,activeLabId],{enabled:Boolean(profileId&&activeLabId),queryKey:"topology-apply-history"});
 const providerDevices=useAsyncLoader(()=>activeLabId&&projectId?api.devices(projectId,activeLabId,"ACTIVE"):Promise.resolve({items:[]}),[activeLabId,projectId],{enabled:Boolean(activeLabId&&projectId),queryKey:"topology-provider-devices"});
 const providerCredentials=useAsyncLoader(()=>bindingForm.controller_device_id?api.credentials(projectId,bindingForm.controller_device_id):Promise.resolve({items:[]}),[projectId,bindingForm.controller_device_id],{enabled:Boolean(projectId&&bindingForm.controller_device_id),queryKey:"topology-provider-credentials"});
 const [providerCatalog,setProviderCatalog]=useState(null);
 const [providerPlan,setProviderPlan]=useState(null);
 const [reconciliation,setReconciliation]=useState(null);
 const [lastApply,setLastApply]=useState(null);
 const [confirmApply,setConfirmApply]=useState(false);
 const [providerBusy,setProviderBusy]=useState(false);
 const [providerError,setProviderError]=useState("");
 const selectedNodeRecord=nodes.find(item=>item.id===selectedNode)||null;
 const canManage=canPerform(user,"topology.manage");
 const canPublish=canPerform(user,"topology.publish");
 const canManageProvider=canPerform(user,"topology.provider.manage");
 const canOperateProvider=canPerform(user,"topology.provider.operate");
 const canApplyTopology=canPerform(user,"topology.apply");
 const binding=providerBinding.data?.binding||null;
 const deviceRows=providerDevices.data?.items||[];
 const credentialRows=(providerCredentials.data?.items||[]).filter(item=>item.credential_type==="API_TOKEN"&&item.status==="ACTIVE");

 useEffect(()=>{if(!projectId&&projectRows.length)setProjectId(projectRows[0].project_id);},[projects.data,projectId]);
 useEffect(()=>{if(!profileId&&profileRows.length)setProfileId(profileRows[0].profile_id);},[profiles.data,profileId]);
 useEffect(()=>{
  setProviderCatalog(null);setProviderPlan(null);setReconciliation(null);setLastApply(null);
  setConfirmApply(false);setProviderError("");
  setBindingForm({endpoint_url:"http://127.0.0.1:3080",gns3_project_id:"",controller_device_id:"",credential_id:""});
 },[activeLabId]);
 useEffect(()=>{
  const item=providerBinding.data?.binding;
  if(item)setBindingForm({endpoint_url:item.endpoint_url,gns3_project_id:item.gns3_project_id,
   controller_device_id:item.controller_device_id,credential_id:item.credential_id});
 },[providerBinding.data]);
 useEffect(()=>{
  if(!credentialRows.some(item=>item.credential_id===bindingForm.credential_id))
   setBindingForm(value=>({...value,credential_id:credentialRows[0]?.credential_id||""}));
 },[providerCredentials.data]);
 useEffect(()=>{
  if(!revisionId&&revisionRows.length){
   setRevisionId(revisionRows[0].revision_id);
   setDefinition(revisionRows[0].definition||emptyDefinition());
  }
 },[revisions.data,revisionId]);
 useEffect(()=>{
  if(!nodes.some(item=>item.id===linkForm.source_node_id))
   setLinkForm(value=>({...value,source_node_id:nodes[0]?.id||""}));
 },[definition.nodes]);
 useEffect(()=>{
  if(!nodes.some(item=>item.id===linkForm.target_node_id))
   setLinkForm(value=>({...value,target_node_id:nodes[1]?.id||nodes[0]?.id||""}));
 },[definition.nodes]);

 function chooseRevision(id){
  setRevisionId(id);
  const revision=revisionRows.find(item=>item.revision_id===id);
  setDefinition(revision?.definition||emptyDefinition());
  setSelectedNode("");
 }
 async function runMutation(action,success){
  setError("");setNotice("");
  try{
   const result=await mutation.run(action);
   setNotice(success);
   await Promise.all([profiles.reload().catch(()=>null),revisions.reload().catch(()=>null)]);
   return result;
  }catch(exc){
   setError(exc.message||"Topology operation failed.");
   return null;
  }
 }
 async function createProfile(event){
  event.preventDefault();
  const result=await runMutation(()=>api.createTopology({
   project_id:projectId,name:profileForm.name,description:profileForm.description,
   scope_type:scope.scope_type,scope_id:scope.scope_type==="PROJECT"?projectId:scope.scope_id
  }),"Topology profile created.");
  if(result?.profile_id){
   setProfileId(result.profile_id);setRevisionId("");setDefinition(emptyDefinition());setShowProfileForm(false);
  }
 }
 function addNode(event){
  event.preventDefault();setError("");setNotice("");
  if(!nodeForm.template_id.trim()){
   setError("Enter the provider template reference. Editing never contacts GNS3.");
   return;
  }
  const node={
   id:localId("node"),name:nodeForm.name.trim(),node_type:nodeForm.node_type,
   template_id:nodeForm.template_id.trim(),x:Number(nodeForm.x),y:Number(nodeForm.y),properties:{}
  };
  setDefinition(value=>({...value,nodes:[...value.nodes,node]}));
  setSelectedNode(node.id);
  setNodeForm(value=>({...value,
   name:value.node_type[0]+value.node_type.slice(1).toLowerCase()+" "+(nodes.length+2),
   x:Math.min(880,Number(value.x)+80),y:Math.min(520,Number(value.y)+60)
  }));
 }
 function removeNode(id){
  setDefinition(value=>({
   nodes:value.nodes.filter(item=>item.id!==id),
   links:value.links.filter(item=>item.source_node_id!==id&&item.target_node_id!==id)
  }));
  if(selectedNode===id)setSelectedNode("");
 }
 function updateNode(id,patch){
  setDefinition(value=>({...value,nodes:value.nodes.map(item=>item.id===id?{...item,...patch}:item)}));
 }
 function addLink(event){
  event.preventDefault();setError("");setNotice("");
  if(!linkForm.source_node_id||!linkForm.target_node_id){
   setError("Select both logical node endpoints.");return;
  }
  if(linkForm.source_node_id===linkForm.target_node_id){
   setError("A link cannot connect a node to itself.");return;
  }
  const link={
   id:localId("link"),source_node_id:linkForm.source_node_id,
   source_adapter:Number(linkForm.source_adapter),source_port:Number(linkForm.source_port),
   target_node_id:linkForm.target_node_id,target_adapter:Number(linkForm.target_adapter),
   target_port:Number(linkForm.target_port)
  };
  setDefinition(value=>({...value,links:[...value.links,link]}));
 }
 function removeLink(id){
  setDefinition(value=>({...value,links:value.links.filter(item=>item.id!==id)}));
 }
 function canvasPoint(event){
  const rect=event.currentTarget.getBoundingClientRect();
  return {
   x:Math.max(0,Math.min(1000,(event.clientX-rect.left)*1000/rect.width)),
   y:Math.max(0,Math.min(620,(event.clientY-rect.top)*620/rect.height))
  };
 }
 function onCanvasPointerMove(event){
  if(!dragging)return;
  const point=canvasPoint(event);
  updateNode(dragging,{x:Math.round(point.x),y:Math.round(point.y)});
 }
 async function saveRevision(event){
  event.preventDefault();
  const result=await runMutation(
   ()=>api.createTopologyRevision(profileId,{definition}),
   "Immutable topology draft revision created."
  );
  if(result?.revision_id)setRevisionId(result.revision_id);
 }
 async function publishRevision(){
  if(!profileId||!revisionId||selectedRevision?.status!=="DRAFT"){
   setError("Select a draft revision to publish.");return;
  }
  await runMutation(
   ()=>api.publishTopologyRevision(profileId,{revision_id:revisionId}),
   "Topology revision published."
  );
 }
 async function runProvider(action,success){
  setProviderError("");setNotice("");
  setProviderBusy(true);
  try{
   const value=await action();
   if(success)setNotice(success);
   return value;
  }catch(exc){
   setProviderError(exc.message||"Provider operation failed.");
   return null;
  }finally{setProviderBusy(false);}
 }
 async function saveProviderBinding(event){
  event.preventDefault();
  if(!activeLabId)return;
  const result=await runProvider(
   ()=>api.bindTopologyProvider(activeLabId,bindingForm),
   "GNS3 provider binding verified and saved."
  );
  if(result){
   await providerBinding.reload().catch(()=>null);
   setProviderCatalog(null);setProviderPlan(null);setReconciliation(null);
  }
 }
 async function loadProviderCatalog(){
  const result=await runProvider(()=>api.topologyProviderCatalog(activeLabId),"Read-only GNS3 catalogue loaded.");
  if(result)setProviderCatalog(result.catalog);
 }
 async function makeApplyPlan(){
  if(!profileId||selectedRevision?.status!=="PUBLISHED"){
   setProviderError("Select a published revision before planning provider changes.");return;
  }
  const result=await runProvider(
   ()=>api.planTopologyApply(profileId,{revision_id:revisionId}),
   "Dry-run plan refreshed. No GNS3 resources were changed."
  );
  if(result){setProviderPlan(result);setConfirmApply(false);}
 }
 async function applyPublishedTopology(){
  if(!providerPlan?.plan?.can_apply||!confirmApply){
   setProviderError("Review a conflict-free plan and confirm the provider changes.");return;
  }
  const result=await runProvider(()=>api.applyTopology(profileId,{
   revision_id:revisionId,expected_sha256:providerPlan.plan.revision_sha256,confirmed:true
  }),"Topology apply finished. Review the apply record and reconciliation result.");
  if(result){
   setLastApply(result);
   const [planResult,reconcileResult]=await Promise.all([
    api.planTopologyApply(profileId,{revision_id:revisionId}).catch(()=>null),
    api.reconcileTopology(profileId,revisionId).catch(()=>null),
    applyHistory.reload().catch(()=>null)
   ]);
   if(planResult)setProviderPlan(planResult);
   if(reconcileResult)setReconciliation(reconcileResult);
   setConfirmApply(false);
  }else{
   // A controller timeout can still leave a recorded PARTIAL operation.
   await applyHistory.reload().catch(()=>null);
  }
 }
 async function refreshReconciliation(){
  if(!profileId||!revisionId)return;
  const result=await runProvider(
   ()=>api.reconcileTopology(profileId,revisionId),
   "Observed provider state reconciled against the selected immutable revision."
  );
  if(result)setReconciliation(result);
 }
 async function operateNode(logicalNodeId,action){
  const result=await runProvider(
   ()=>api.operateTopologyNode(profileId,logicalNodeId,action),
   "Explicit node "+action.toLowerCase()+" request completed."
  );
  if(result)await refreshReconciliation();
 }

 const nodeById=Object.fromEntries(nodes.map(item=>[item.id,item]));
 if(projects.loading&&!projects.data)return <LoadingState label="Loading topology workspace…"/>;
 if(projects.error&&!projects.data)return <ErrorState error={projects.error} onRetry={projects.reload}/>;
 return <div className="page-stack">
  <div className="module-intro">
   <div className="module-intro-icon">⌘</div>
   <div><strong>Canonical topology studio</strong><p>Build a logical topology using stable node IDs and explicit adapter/port references. Editing and publishing are local data operations; they never provision GNS3 resources.</p></div>
  </div>
  <Section title="Workspace scope" subtitle="Topology profiles are isolated by Project and optionally by Lab.">
   <div className="form-grid">
    <Field label="Project">
     <select value={projectId} onChange={event=>{setProjectId(event.target.value);setProfileId("");setRevisionId("");setDefinition(emptyDefinition());}} disabled={projects.loading}>
      <option value="">Select Project</option>
      {projectRows.map(item=><option key={item.project_id} value={item.project_id}>{item.name} · {item.slug}</option>)}
     </select>
    </Field>
    <Field label="Profile">
     <select value={profileId} onChange={event=>{setProfileId(event.target.value);setRevisionId("");setDefinition(emptyDefinition());}} disabled={!projectId}>
      <option value="">Select topology profile</option>
      {profileRows.map(item=><option key={item.profile_id} value={item.profile_id}>{item.name} · {item.scope_type}</option>)}
     </select>
    </Field>
    {canManage?<div className="form-actions"><Button type="button" variant="outline" onClick={()=>setShowProfileForm(value=>!value)} disabled={!projectId}>{showProfileForm?"Close":"New profile"}</Button></div>:null}
   </div>
   {profiles.error?<InlineNotice tone="danger">{profiles.error.message}</InlineNotice>:null}
   {showProfileForm&&canManage?<form className="form-grid" onSubmit={createProfile}>
    <Field label="Profile name" required><input value={profileForm.name} onChange={event=>setProfileForm({...profileForm,name:event.target.value})} maxLength={120} required/></Field>
    <Field label="Scope">
     <select value={scope.scope_type} onChange={event=>setScope({...scope,scope_type:event.target.value,scope_id:""})}>
      <option value="PROJECT">Project</option><option value="LAB">Lab</option>
     </select>
    </Field>
    {scope.scope_type==="LAB"?<Field label="Lab ID" required><input value={scope.scope_id} onChange={event=>setScope({...scope,scope_id:event.target.value})} required/></Field>:null}
    <Field label="Description"><input value={profileForm.description} onChange={event=>setProfileForm({...profileForm,description:event.target.value})}/></Field>
    <div className="form-actions"><Button type="submit" loading={mutation.loading} disabled={!projectId||!profileForm.name.trim()||(scope.scope_type==="LAB"&&!scope.scope_id.trim())}>Create profile</Button></div>
   </form>:null}
  </Section>
  {notice?<InlineNotice tone="success">{notice}</InlineNotice>:null}
  {error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  {profileId?<>
   <Section title="Revision history" subtitle="Published revisions are immutable. Continue editing by saving a new draft from the local canvas.">
    <div className="form-grid">
     <Field label="Revision">
      <select value={revisionId} onChange={event=>chooseRevision(event.target.value)}>
       <option value="">Unsaved draft</option>
       {revisionRows.map(item=><option key={item.revision_id} value={item.revision_id}>r{item.revision_number} · {item.status} · {item.content_sha256.slice(0,10)}</option>)}
      </select>
     </Field>
     <div className="context-caption">{selectedRevision?"SHA-256 · "+selectedRevision.content_sha256:"Local working draft — not yet persisted"}</div>
    </div>
    {revisions.loading?<LoadingState label="Loading topology revisions…"/>:revisions.error?<ErrorState error={revisions.error} onRetry={revisions.reload}/>:null}
    <DataTable caption="Topology revision history" rows={revisionRows} rowKey={item=>item.revision_id} columns={[
     {key:"revision_number",label:"Revision"},
     {key:"content_sha256",label:"SHA-256",render:item=><code title={item.content_sha256}>{item.content_sha256.slice(0,14)}…</code>},
     {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
     {key:"created_at",label:"Created"},{key:"published_at",label:"Published"}
    ]} emptyTitle="No topology revisions" emptyMessage="Add nodes and links, then save the first immutable draft revision."/>
   </Section>
   <Section title="Node palette" subtitle="Choose a logical type, display name and provider template reference. Template lookup is deferred to the explicit provider workflow.">
    <form className="form-grid" onSubmit={addNode}>
     <Field label="Node type"><select value={nodeForm.node_type} onChange={event=>setNodeForm({...nodeForm,node_type:event.target.value})}>{NODE_TYPES.map(item=><option key={item}>{item}</option>)}</select></Field>
     <Field label="Node name"><input value={nodeForm.name} onChange={event=>setNodeForm({...nodeForm,name:event.target.value})} maxLength={120} required/></Field>
     <Field label="Provider template reference"><input value={nodeForm.template_id} onChange={event=>setNodeForm({...nodeForm,template_id:event.target.value})} maxLength={128} required/></Field>
     <Field label="Initial X"><input type="number" min="0" max="10000" value={nodeForm.x} onChange={event=>setNodeForm({...nodeForm,x:event.target.value})}/></Field>
     <Field label="Initial Y"><input type="number" min="0" max="10000" value={nodeForm.y} onChange={event=>setNodeForm({...nodeForm,y:event.target.value})}/></Field>
     <div className="form-actions"><Button type="submit" disabled={!canManage||mutation.loading}>Add node</Button></div>
    </form>
   </Section>
   <Section title="Visual canvas" subtitle="Drag nodes to position them. The canvas is local-only and does not issue GNS3 calls.">
    <div style={{width:"100%",overflowX:"auto",border:"1px solid var(--border)",borderRadius:12,background:"var(--card)"}}>
     <svg viewBox="0 0 1000 620" role="img" aria-label="Topology canvas. Select and drag nodes to arrange them." style={{display:"block",width:"100%",minWidth:620,touchAction:"none"}}
      onPointerMove={onCanvasPointerMove} onPointerUp={()=>setDragging("")} onPointerLeave={()=>setDragging("")}>
      <defs><pattern id="topology-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M 25 0 L 0 0 0 25" fill="none" stroke="currentColor" strokeOpacity=".08" strokeWidth="1"/></pattern></defs>
      <rect x="0" y="0" width="1000" height="620" fill="url(#topology-grid)"/>
      {links.map(link=>{
       const source=nodeById[link.source_node_id],target=nodeById[link.target_node_id];
       return source&&target?<g key={link.id}>
        <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="var(--primary)" strokeWidth="4"/>
        <text x={(source.x+target.x)/2} y={(source.y+target.y)/2-8} fill="currentColor" fontSize="12">{link.source_adapter}/{link.source_port} ↔ {link.target_adapter}/{link.target_port}</text>
       </g>:null;
      })}
      {nodes.map(node=><g key={node.id} transform={"translate("+node.x+" "+node.y+")"}
       onPointerDown={event=>{event.preventDefault();setSelectedNode(node.id);setDragging(node.id);event.currentTarget.setPointerCapture?.(event.pointerId);}}
       style={{cursor:"grab"}}>
       <rect x="-68" y="-34" width="136" height="68" rx="12" fill={selectedNode===node.id?"var(--primary)":"var(--muted)"} stroke="var(--border)" strokeWidth="2"/>
       <text x="0" y="-4" textAnchor="middle" fill={selectedNode===node.id?"white":"currentColor"} fontSize="14" fontWeight="600">{node.name.slice(0,18)}</text>
       <text x="0" y="16" textAnchor="middle" fill={selectedNode===node.id?"white":"currentColor"} fontSize="10">{node.node_type} · {node.id.slice(0,12)}</text>
      </g>)}
     </svg>
    </div>
    {!nodes.length?<EmptyState title="Canvas is empty" message="Add the first node using the palette above. This does not create a provider resource."/>:null}
    {selectedNodeRecord?<div className="form-grid">
     <Field label="Selected node"><input value={selectedNodeRecord.name} onChange={event=>updateNode(selectedNode,{name:event.target.value})}/></Field>
     <Field label="Template reference"><input value={selectedNodeRecord.template_id} onChange={event=>updateNode(selectedNode,{template_id:event.target.value})}/></Field>
     <Field label="X coordinate"><input type="number" min="0" max="10000" value={selectedNodeRecord.x} onChange={event=>updateNode(selectedNode,{x:Number(event.target.value)})}/></Field>
     <Field label="Y coordinate"><input type="number" min="0" max="10000" value={selectedNodeRecord.y} onChange={event=>updateNode(selectedNode,{y:Number(event.target.value)})}/></Field>
     <div className="form-actions"><Button type="button" variant="destructive" onClick={()=>removeNode(selectedNode)}>Remove node and attached links</Button></div>
    </div>:null}
   </Section>
   <Section title="Interface and link editor" subtitle="Each endpoint is a concrete adapter/port pair. Port occupancy is validated again by the backend.">
    <form className="form-grid" onSubmit={addLink}>
     <Field label="Source node"><select value={linkForm.source_node_id} onChange={event=>setLinkForm({...linkForm,source_node_id:event.target.value})}><option value="">Select node</option>{nodes.map(item=><option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></Field>
     <Field label="Source adapter"><input type="number" min="0" max="255" value={linkForm.source_adapter} onChange={event=>setLinkForm({...linkForm,source_adapter:event.target.value})}/></Field>
     <Field label="Source port"><input type="number" min="0" max="255" value={linkForm.source_port} onChange={event=>setLinkForm({...linkForm,source_port:event.target.value})}/></Field>
     <Field label="Target node"><select value={linkForm.target_node_id} onChange={event=>setLinkForm({...linkForm,target_node_id:event.target.value})}><option value="">Select node</option>{nodes.map(item=><option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></Field>
     <Field label="Target adapter"><input type="number" min="0" max="255" value={linkForm.target_adapter} onChange={event=>setLinkForm({...linkForm,target_adapter:event.target.value})}/></Field>
     <Field label="Target port"><input type="number" min="0" max="255" value={linkForm.target_port} onChange={event=>setLinkForm({...linkForm,target_port:event.target.value})}/></Field>
     <div className="form-actions"><Button type="submit" disabled={nodes.length<2||!canManage}>Add link</Button></div>
    </form>
    <DataTable caption="Logical topology links" rows={links} rowKey={item=>item.id} columns={[
     {key:"id",label:"Link ID"},
     {key:"source_node_id",label:"Source",render:item=>item.source_node_id+" · "+item.source_adapter+"/"+item.source_port},
     {key:"target_node_id",label:"Target",render:item=>item.target_node_id+" · "+item.target_adapter+"/"+item.target_port},
     {key:"actions",label:"Actions",render:item=>canManage?<Button variant="ghost" size="sm" onClick={()=>removeLink(item.id)}>Remove</Button>:"—"}
    ]} emptyTitle="No links" emptyMessage="Connect two nodes using their exact adapter and port numbers."/>
   </Section>
   {activeLabId?<Section title="GNS3 provider and topology apply" subtitle="Bind a private GNS3 controller to this Lab, inspect its catalogue, plan changes and apply only after explicit confirmation.">
    <div className="module-intro">
     <div className="module-intro-icon">⇄</div>
     <div><strong>Explicit provider boundary</strong><p>Editing and publishing remain local-only. The provider is contacted only when you verify a binding, inspect the catalogue, request a dry-run, reconcile, apply, or explicitly start/stop a mapped node. Unmanaged resources are never pruned.</p></div>
    </div>
    {providerBinding.error?<InlineNotice tone="danger">{providerBinding.error.message}</InlineNotice>:null}
    {binding?<div className="context-caption">Active binding · {binding.endpoint_url} · GNS3 project {binding.gns3_project_id} · controller {binding.controller_device_id}</div>:<div className="context-caption">No active GNS3 controller is bound to this Lab.</div>}
    {canManageProvider?<form className="form-grid" onSubmit={saveProviderBinding}>
     <Field label="Private GNS3 Controller URL" required><input value={bindingForm.endpoint_url} onChange={event=>setBindingForm({...bindingForm,endpoint_url:event.target.value})} placeholder="http://127.0.0.1:3080" required/></Field>
     <Field label="GNS3 project ID" required><input value={bindingForm.gns3_project_id} onChange={event=>setBindingForm({...bindingForm,gns3_project_id:event.target.value})} maxLength={128} required/></Field>
     <Field label="Registered controller device" required>
      <select value={bindingForm.controller_device_id} onChange={event=>setBindingForm({...bindingForm,controller_device_id:event.target.value,credential_id:""})} required>
       <option value="">Select device</option>
       {deviceRows.map(item=><option key={item.device_id} value={item.device_id}>{item.name} · {item.host}</option>)}
      </select>
     </Field>
     <Field label="OS-vault API_TOKEN credential" required>
      <select value={bindingForm.credential_id} onChange={event=>setBindingForm({...bindingForm,credential_id:event.target.value})} required>
       <option value="">Select active API credential</option>
       {credentialRows.map(item=><option key={item.credential_id} value={item.credential_id}>{item.label} · {item.credential_id}</option>)}
      </select>
     </Field>
     <div className="form-actions"><Button type="submit" loading={providerBusy} disabled={!activeLabId||!bindingForm.endpoint_url.trim()||!bindingForm.gns3_project_id.trim()||!bindingForm.controller_device_id||!bindingForm.credential_id}>Verify and bind controller</Button></div>
    </form>:null}
    {!deviceRows.length&&activeLabId?<InlineNotice tone="info">Register the GNS3 controller as an active device in this Lab, then attach an API_TOKEN credential through the Credentials workspace.</InlineNotice>:null}
    {providerCredentials.error?<InlineNotice tone="danger">{providerCredentials.error.message}</InlineNotice>:null}
    {providerError?<InlineNotice tone="danger">{providerError}</InlineNotice>:null}
    {binding?<div className="button-row">
     <Button variant="outline" onClick={loadProviderCatalog} loading={providerBusy}>Inspect provider catalogue</Button>
     {canManageProvider?<Button variant="ghost" onClick={()=>runProvider(()=>api.archiveTopologyProvider(activeLabId).then(async result=>{await providerBinding.reload();return result;}),"Provider binding archived. No provider resources were deleted.")} loading={providerBusy}>Archive binding</Button>:null}
    </div>:null}
    {providerCatalog?<div className="form-grid">
     <div className="context-caption">GNS3 version · {providerCatalog.version?.version||"version available"} · projects {providerCatalog.projects?.length||0} · templates {providerCatalog.templates?.length||0}</div>
     <div className="context-caption">Observed nodes {providerCatalog.nodes?.length||0} · links {providerCatalog.links?.length||0}</div>
     <div className="context-caption">Catalogue inspection is read-only; provider nodes and links are not changed.</div>
    </div>:null}
    {binding&&selectedRevision?.status==="PUBLISHED"?<div className="form-grid">
     <div className="form-actions"><Button variant="outline" onClick={makeApplyPlan} loading={providerBusy}>Build dry-run plan</Button>
      <Button variant="outline" onClick={refreshReconciliation} loading={providerBusy}>Reconcile observed state</Button></div>
    </div>:null}
    {providerPlan?.plan?<div className="provider-plan">
     <h4>Dry-run plan · revision {providerPlan.plan.revision_id}</h4>
     <div className="metric-grid">
      <div className="metric-card"><strong>{providerPlan.plan.nodes_to_create.length}</strong><span>Nodes to create</span></div>
      <div className="metric-card"><strong>{providerPlan.plan.links_to_create.length}</strong><span>Links to create</span></div>
      <div className="metric-card"><strong>{providerPlan.plan.links_pending_nodes.length}</strong><span>Links pending node creation</span></div>
      <div className="metric-card"><strong>{providerPlan.plan.conflicts.length}</strong><span>Conflicts</span></div>
     </div>
     <p><StatusBadge value={providerPlan.plan.can_apply?"READY":"BLOCKED"}/> <span className="context-caption">Published revision SHA-256 · {providerPlan.plan.revision_sha256}</span></p>
     {providerPlan.plan.conflicts.length?<ul>{providerPlan.plan.conflicts.map((item,index)=><li key={index}>{item.resource_id||"Provider"}: {item.reason}</li>)}</ul>:<p>No current template or port conflicts were found in the observed provider state.</p>}
     {canApplyTopology&&providerPlan.plan.can_apply?<label className="confirm-operation">
      <input type="checkbox" checked={confirmApply} onChange={event=>setConfirmApply(event.target.checked)}/>
      I reviewed this revision hash and authorize these explicit GNS3 node/link changes for this Lab.
     </label>:null}
     {canApplyTopology?<div className="button-row"><Button onClick={applyPublishedTopology} loading={providerBusy} disabled={!providerPlan.plan.can_apply||!confirmApply}>Confirm and apply topology</Button></div>:null}
    </div>:null}
    {reconciliation?<div className="provider-plan">
     <h4>Observed-versus-desired reconciliation</h4>
     <p><StatusBadge value={reconciliation.status}/> {reconciliation.observed_managed_node_count} of {reconciliation.desired_node_count} managed nodes observed · {reconciliation.missing_nodes.length} missing nodes · {reconciliation.missing_links.length} missing links</p>
     {reconciliation.missing_nodes.length?<p>Missing nodes: {reconciliation.missing_nodes.join(", ")}</p>:null}
     {reconciliation.missing_links.length?<p>Missing links: {reconciliation.missing_links.join(", ")}</p>:null}
     {canOperateProvider&&providerPlan?.plan?.already_present_nodes?.length?<div className="form-actions">
      {providerPlan.plan.already_present_nodes.map(nodeId=><span key={nodeId} className="inline-node-operation"><strong>{nodeId}</strong><Button size="sm" variant="outline" onClick={()=>operateNode(nodeId,"start")} loading={providerBusy}>Start</Button><Button size="sm" variant="ghost" onClick={()=>operateNode(nodeId,"stop")} loading={providerBusy}>Stop</Button></span>)}
     </div>:null}
    </div>:null}
    {lastApply?<div className="provider-plan">
     <h4>Latest apply record · {lastApply.apply_id}</h4>
     <p><StatusBadge value={lastApply.status}/> {lastApply.result?.summary?.created_nodes||0} nodes and {lastApply.result?.summary?.created_links||0} links created</p>
     <pre className="code-block">{JSON.stringify(lastApply.result,null,2)}</pre>
    </div>:null}
    {applyHistory.error?<InlineNotice tone="danger">{applyHistory.error.message}</InlineNotice>:null}
    <DataTable caption="Topology apply and recovery history" rows={applyHistory.data?.items||[]} rowKey={item=>item.apply_id} columns={[
     {key:"apply_id",label:"Apply record",render:item=><code>{item.apply_id}</code>},
     {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
     {key:"revision_id",label:"Revision"},
     {key:"created_at",label:"Started",render:item=>new Date(item.created_at).toLocaleString()},
     {key:"completed_at",label:"Completed",render:item=>item.completed_at?new Date(item.completed_at).toLocaleString():"—"}
    ]} emptyTitle="No topology applies" emptyMessage="Dry-run plans do not create history. Confirmed provider operations are retained here, including partial results."/>
   </Section>:null}
   {canManage?<Section title="Save immutable topology revision" subtitle="Saving creates a new draft with canonical JSON and SHA-256. Existing revisions are never overwritten.">
    <div className="button-row">
     <Button onClick={saveRevision} loading={mutation.loading} disabled={!profileId}>Save new draft revision</Button>
     {canPublish?<Button variant="outline" onClick={publishRevision} disabled={!revisionId||selectedRevision?.status!=="DRAFT"||mutation.loading}>Publish selected revision</Button>:null}
    </div>
   </Section>:null}
  </>:<EmptyState title="Select or create a topology profile" message="Choose a Project and a profile to open the local topology canvas."/>}
 </div>;
}
