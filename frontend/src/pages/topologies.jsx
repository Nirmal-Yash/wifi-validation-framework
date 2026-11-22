import React,{useEffect,useRef,useState} from "react";
import {api} from "@/api";
import {useWorkspace} from "@/components/workspace-context";
import {useAsyncLoader,useMutation} from "@/hooks";
import {canPerform} from "@/permissions";
import {copyTopologySelection,createTopologyHistory,moveTopologyNodes,pasteTopologySelection,removeTopologySelection} from "@/topology-editor";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

export const DEFAULT_TOPOLOGY_VIEWPORT=Object.freeze({x:0,y:0,width:1000,height:620});
const VIEWPORT_RATIO=0.62;
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));

export function zoomTopologyViewport(viewport,factor,anchorX=0.5,anchorY=0.5){
 const width=clamp(viewport.width*factor,250,2500);
 const height=width*VIEWPORT_RATIO;
 const worldX=viewport.x+viewport.width*clamp(anchorX,0,1);
 const worldY=viewport.y+viewport.height*clamp(anchorY,0,1);
 return {
  x:clamp(worldX-width*clamp(anchorX,0,1),0,Math.max(0,10000-width)),
  y:clamp(worldY-height*clamp(anchorY,0,1),0,Math.max(0,10000-height)),
  width,height,
 };
}

export function fitTopologyViewport(nodes){
 if(!Array.isArray(nodes)||!nodes.length)return {...DEFAULT_TOPOLOGY_VIEWPORT};
 const xs=nodes.map(node=>Number(node.x)||0);
 const ys=nodes.map(node=>Number(node.y)||0);
 const minX=Math.min(...xs),maxX=Math.max(...xs);
 const minY=Math.min(...ys),maxY=Math.max(...ys);
 const width=clamp(Math.max(420,maxX-minX+260,(maxY-minY+260)/VIEWPORT_RATIO),250,2500);
 const height=width*VIEWPORT_RATIO;
 const centerX=(minX+maxX)/2,centerY=(minY+maxY)/2;
 return {
  x:clamp(centerX-width/2,0,Math.max(0,10000-width)),
  y:clamp(centerY-height/2,0,Math.max(0,10000-height)),
  width,height,
 };
}

const NODE_TYPES=["ROUTER","SWITCH","ACCESS_POINT","CLIENT","MONITOR","CLOUD","OTHER"];
const emptyDefinition=()=>({nodes:[],links:[]});
const localId=prefix=>prefix+"-"+(globalThis.crypto?.randomUUID?globalThis.crypto.randomUUID().slice(0,12):Math.random().toString(36).slice(2,14));

export default function TopologyStudioPage({user}){
 const workspace=useWorkspace();
 const projects=useAsyncLoader(()=>workspace.activeOrganizationId?api.workspaceProjects({organization_id:workspace.activeOrganizationId}):Promise.resolve({items:[]}),[workspace.activeOrganizationId],{enabled:Boolean(workspace.activeOrganizationId),queryKey:"topology-studio-projects"});
 const [projectId,setProjectId]=useState(workspace.activeProjectId||"");
 const [profileId,setProfileId]=useState("");
 const [revisionId,setRevisionId]=useState("");
 const [scope,setScope]=useState({scope_type:"PROJECT",scope_id:""});
 const [profileForm,setProfileForm]=useState({name:"Wireless topology",description:""});
 const [nodeForm,setNodeForm]=useState({node_type:"ROUTER",name:"Router",template_id:"",x:160,y:180});
 const [linkForm,setLinkForm]=useState({source_node_id:"",source_adapter:0,source_port:0,target_node_id:"",target_adapter:0,target_port:0});
 const [definition,setDefinition]=useState(emptyDefinition);
 const [selectedNode,setSelectedNode]=useState("");
 const [selectedNodes,setSelectedNodes]=useState([]);
 const [selectedLink,setSelectedLink]=useState("");
 const [linkEditForm,setLinkEditForm]=useState(null);
 const [validation,setValidation]=useState(null);
 const [validationLoading,setValidationLoading]=useState(false);
 const [historyVersion,setHistoryVersion]=useState(0);
 const historyRef=useRef(null);
 if(!historyRef.current)historyRef.current=createTopologyHistory(definition);
 const definitionRef=useRef(definition),canvasRef=useRef(null),dragSessionRef=useRef(null),clipboardRef=useRef(null);
 const [dragging,setDragging]=useState("");
 const [viewport,setViewport]=useState({...DEFAULT_TOPOLOGY_VIEWPORT});
 const [panning,setPanning]=useState(null);
 const [nodeSearch,setNodeSearch]=useState("");
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
 const selectedLinkRecord=links.find(item=>item.id===selectedLink)||null;
 const canManage=canPerform(user,"topology.manage");
 const canPublish=canPerform(user,"topology.publish");
 const canManageProvider=canPerform(user,"topology.provider.manage");
 const canOperateProvider=canPerform(user,"topology.provider.operate");
 const canApplyTopology=canPerform(user,"topology.apply");
 const binding=providerBinding.data?.binding||null;
 const deviceRows=providerDevices.data?.items||[];
 const credentialRows=(providerCredentials.data?.items||[]).filter(item=>item.credential_type==="API_TOKEN"&&item.status==="ACTIVE");

 useEffect(()=>{
  if(workspace.activeProjectId&&projectRows.some(item=>item.project_id===workspace.activeProjectId)){
   if(projectId!==workspace.activeProjectId){
    setProjectId(workspace.activeProjectId);setProfileId("");setRevisionId("");resetEditorDefinition(emptyDefinition());
   }
  }else if(!projectId&&projectRows.length){
   const first=projectRows[0].project_id;
   setProjectId(first);workspace.selectProject(first);
  }
 },[projects.data,projectId,workspace.activeProjectId]);
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
   resetEditorDefinition(revisionRows[0].definition||emptyDefinition());
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


 function setEditorDefinition(next,{record=true,previous}={}){
  const current=definitionRef.current,candidate=typeof next==="function"?next(current):next,baseline=previous||current;
  if((record&&JSON.stringify(baseline)===JSON.stringify(candidate))||(!record&&JSON.stringify(current)===JSON.stringify(candidate)))return;
  if(record)historyRef.current.commit(candidate,baseline);else historyRef.current.replace(candidate);
  definitionRef.current=candidate;setDefinition(candidate);setValidation(null);
  if(record)setHistoryVersion(value=>value+1);
 }
 function resetEditorDefinition(next){
  const value=next||emptyDefinition();historyRef.current.reset(value);definitionRef.current=value;setDefinition(value);
  setHistoryVersion(value=>value+1);setSelectedNode("");setSelectedNodes([]);setSelectedLink("");setLinkEditForm(null);setValidation(null);
 }
 function undoTopologyEdit(){const value=historyRef.current.undo();if(!value)return;definitionRef.current=value;setDefinition(value);setSelectedNodes(ids=>ids.filter(id=>value.nodes.some(node=>node.id===id)));setSelectedNode(id=>value.nodes.some(node=>node.id===id)?id:"");setSelectedLink(id=>value.links.some(link=>link.id===id)?id:"");setValidation(null);setHistoryVersion(v=>v+1);}
 function redoTopologyEdit(){const value=historyRef.current.redo();if(!value)return;definitionRef.current=value;setDefinition(value);setSelectedNodes(ids=>ids.filter(id=>value.nodes.some(node=>node.id===id)));setSelectedNode(id=>value.nodes.some(node=>node.id===id)?id:"");setSelectedLink(id=>value.links.some(link=>link.id===id)?id:"");setValidation(null);setHistoryVersion(v=>v+1);}
 function copyTopology(){const value=copyTopologySelection(definitionRef.current,selectedNodes,selectedLink);if(!value.nodes.length){clipboardRef.current=null;return;}clipboardRef.current=value;setNotice(value.nodes.length+" node(s) and "+value.links.length+" internal link(s) copied.");}
 function pasteTopology(){if(!canManage||!clipboardRef.current)return;try{const result=pasteTopologySelection(definitionRef.current,clipboardRef.current,{offset:40,idFactory:localId});setEditorDefinition(result.definition);setSelectedNodes(result.nodeIds);setSelectedNode(result.nodeIds[0]||"");setSelectedLink("");setNotice(result.nodeIds.length+" node(s) pasted with new logical IDs.");}catch(exc){setError(exc.message||"Clipboard content could not be pasted.");}}
 function deleteSelectedTopology(){if(!canManage||(!selectedNodes.length&&!selectedLink))return;setEditorDefinition(removeTopologySelection(definitionRef.current,selectedNodes,selectedLink));setSelectedNodes([]);setSelectedNode("");setSelectedLink("");setLinkEditForm(null);}
 function selectCanvasLink(link){setSelectedLink(link.id);setSelectedNodes([]);setSelectedNode("");setLinkEditForm({...link});}
 function saveSelectedLink(event){event.preventDefault();if(!canManage||!selectedLink||!linkEditForm)return;const next={...linkEditForm,source_adapter:Number(linkEditForm.source_adapter),source_port:Number(linkEditForm.source_port),target_adapter:Number(linkEditForm.target_adapter),target_port:Number(linkEditForm.target_port)};setEditorDefinition(value=>({...value,links:value.links.map(item=>item.id===selectedLink?next:item)}));setNotice("Link endpoint references updated. Validate before saving a revision.");}
 function startNodeDrag(event,nodeId){
  event.preventDefault();event.stopPropagation();
  if(!canManage){setSelectedNodes([nodeId]);setSelectedNode(nodeId);setSelectedLink("");return;}
  if(event.ctrlKey||event.metaKey||event.shiftKey){const next=selectedNodes.includes(nodeId)?selectedNodes.filter(id=>id!==nodeId):[...selectedNodes,nodeId];setSelectedNodes(next);setSelectedNode(next[next.length-1]||"");setSelectedLink("");return;}
  const ids=selectedNodes.includes(nodeId)?selectedNodes:[nodeId];setSelectedNodes(ids);setSelectedNode(nodeId);setSelectedLink("");
  dragSessionRef.current={nodeIds:ids.slice(),start:canvasPoint(event),initialDefinition:JSON.parse(JSON.stringify(definitionRef.current))};
  setDragging(nodeId);event.currentTarget.setPointerCapture?.(event.pointerId);
 }
 function finishCanvasInteraction(){const session=dragSessionRef.current;if(session){setEditorDefinition(definitionRef.current,{record:true,previous:session.initialDefinition});dragSessionRef.current=null;}setDragging("");setPanning(null);}
 async function validateDraft(){
  if(!canManage)return null;
  setError("");setNotice("");setValidationLoading(true);
  try{const result=await api.validateTopology({project_id:projectId,profile_id:profileId||undefined,definition:definitionRef.current});setValidation(result);setNotice("Topology definition is valid · SHA-256 "+result.content_sha256);return result;}
  catch(exc){setValidation({valid:false,error:exc.message||"Topology validation failed.",code:exc.code||"INVALID_TOPOLOGY"});setError(exc.message||"Topology validation failed.");return null;}
  finally{setValidationLoading(false);}
 }
 function selectAllNodes(){const ids=nodes.map(node=>node.id);setSelectedNodes(ids);setSelectedNode(ids[0]||"");setSelectedLink("");}
 useEffect(()=>{
  const handler=event=>{
   const target=event.target,tag=String(target?.tagName||"").toLowerCase();
   if(["input","textarea","select","button"].includes(tag)||target?.isContentEditable)return;
   const mod=event.ctrlKey||event.metaKey,key=String(event.key||"").toLowerCase();
   if(mod&&key==="z"){event.preventDefault();event.shiftKey?redoTopologyEdit():undoTopologyEdit();return;}
   if(mod&&key==="y"){event.preventDefault();redoTopologyEdit();return;}
   if(mod&&key==="a"){event.preventDefault();selectAllNodes();return;}
   if(mod&&key==="c"){event.preventDefault();copyTopology();return;}
   if(mod&&key==="v"){event.preventDefault();pasteTopology();return;}
   if(key==="delete"||key==="backspace"){if(canManage&&(selectedNodes.length||selectedLink)){event.preventDefault();deleteSelectedTopology();}return;}
   if(key==="escape"){setSelectedNodes([]);setSelectedNode("");setSelectedLink("");setLinkEditForm(null);}
  };
  window.addEventListener("keydown",handler);return()=>window.removeEventListener("keydown",handler);
 },[selectedNodes,selectedLink,selectedNode,historyVersion]);

 function chooseRevision(id){
  setRevisionId(id);
  const revision=revisionRows.find(item=>item.revision_id===id);
  resetEditorDefinition(revision?.definition||emptyDefinition());
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
   setProfileId(result.profile_id);setRevisionId("");resetEditorDefinition(emptyDefinition());setShowProfileForm(false);
  }
 }
 function addNode(event){
  event.preventDefault();if(!canManage)return;setError("");setNotice("");
  if(!nodeForm.template_id.trim()){
   setError("Enter the provider template reference. Editing never contacts GNS3.");
   return;
  }
  const node={
   id:localId("node"),name:nodeForm.name.trim(),node_type:nodeForm.node_type,
   template_id:nodeForm.template_id.trim(),x:Number(nodeForm.x),y:Number(nodeForm.y),properties:{}
  };
  setEditorDefinition(value=>({...value,nodes:[...value.nodes,node]}));
  setSelectedNode(node.id);setSelectedNodes([node.id]);setSelectedLink("");
  setNodeForm(value=>({...value,
   name:value.node_type[0]+value.node_type.slice(1).toLowerCase()+" "+(nodes.length+2),
   x:Math.min(880,Number(value.x)+80),y:Math.min(520,Number(value.y)+60)
  }));
 }
 function removeNode(id){
  if(!canManage)return;
  const next=removeTopologySelection(definitionRef.current,[id],"");
  setEditorDefinition(next);
  setSelectedNodes(value=>value.filter(item=>item!==id));
  if(selectedNode===id)setSelectedNode("");
  if(selectedLink&&!next.links.some(item=>item.id===selectedLink)){setSelectedLink("");setLinkEditForm(null);}
 }
 function updateNode(id,patch){
  if(!canManage)return;
  setEditorDefinition(value=>({...value,nodes:value.nodes.map(item=>item.id===id?{...item,...patch}:item)}));
 }
 function addLink(event){
  event.preventDefault();if(!canManage)return;setError("");setNotice("");
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
  setEditorDefinition(value=>({...value,links:[...value.links,link]}));setSelectedLink(link.id);setSelectedNodes([]);setSelectedNode("");setLinkEditForm({...link});
 }
 function removeLink(id){
  if(!canManage)return;
  setEditorDefinition(value=>({...value,links:value.links.filter(item=>item.id!==id)}));if(selectedLink===id){setSelectedLink("");setLinkEditForm(null);}
 }
 function canvasPoint(event){
  const rect=(canvasRef.current||event.currentTarget).getBoundingClientRect();
  return {
   x:Math.max(0,Math.min(10000,viewport.x+(event.clientX-rect.left)*viewport.width/rect.width)),
   y:Math.max(0,Math.min(10000,viewport.y+(event.clientY-rect.top)*viewport.height/rect.height))
  };
 }
 function startCanvasPan(event){
  const target=event.target;
  const isBackground=target===event.currentTarget||target?.dataset?.canvasBackground==="true";
  if(!isBackground||event.button!==0)return;
  event.preventDefault();
  setPanning({clientX:event.clientX,clientY:event.clientY,viewport});
  event.currentTarget.setPointerCapture?.(event.pointerId);
 }
 function zoomCanvas(factor,anchorX=0.5,anchorY=0.5){
  setViewport(value=>zoomTopologyViewport(value,factor,anchorX,anchorY));
 }
 function zoomCanvasAtPointer(event){
  event.preventDefault();
  const rect=event.currentTarget.getBoundingClientRect();
  const anchorX=(event.clientX-rect.left)/rect.width;
  const anchorY=(event.clientY-rect.top)/rect.height;
  zoomCanvas(event.deltaY<0?0.9:1.1,anchorX,anchorY);
 }
 function fitCanvas(){setViewport(fitTopologyViewport(nodes));}
 function onCanvasPointerMove(event){
  if(panning){
   const rect=event.currentTarget.getBoundingClientRect();
   const dx=(event.clientX-panning.clientX)*panning.viewport.width/rect.width;
   const dy=(event.clientY-panning.clientY)*panning.viewport.height/rect.height;
   setViewport({
    ...panning.viewport,
    x:Math.max(0,Math.min(10000-panning.viewport.width,panning.viewport.x-dx)),
    y:Math.max(0,Math.min(10000-panning.viewport.height,panning.viewport.y-dy))
   });
   return;
  }
  const session=dragSessionRef.current;if(!session)return;
  const point=canvasPoint(event),dx=Math.round(point.x-session.start.x),dy=Math.round(point.y-session.start.y);
  setEditorDefinition(moveTopologyNodes(session.initialDefinition,session.nodeIds,dx,dy),{record:false});
 }
 async function saveRevision(event){
  event.preventDefault();if(!canManage)return;
  const checked=await validateDraft();if(!checked?.valid)return;
  const result=await runMutation(()=>api.createTopologyRevision(profileId,{definition:definitionRef.current}),"Immutable topology draft revision created.");
  if(result?.revision_id){setRevisionId(result.revision_id);resetEditorDefinition(result.definition||definitionRef.current);}
 }
 async function publishRevision(){
  if(!canPublish)return;
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
     <select value={projectId} onChange={event=>{const value=event.target.value;setProjectId(value);workspace.selectProject(value);setProfileId("");setRevisionId("");resetEditorDefinition(emptyDefinition());}} disabled={projects.loading}>
      <option value="">Select Project</option>
      {projectRows.map(item=><option key={item.project_id} value={item.project_id}>{item.name} · {item.slug}</option>)}
     </select>
    </Field>
    <Field label="Profile">
     <select value={profileId} onChange={event=>{setProfileId(event.target.value);setRevisionId("");resetEditorDefinition(emptyDefinition());}} disabled={!projectId}>
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
   <Section title="Visual canvas" subtitle="Drag nodes to position them. Pan by dragging empty canvas; zoom with the wheel or controls. Canvas editing does not issue provider calls.">
    <div className="topology-canvas-toolbar">
     <label className="topology-node-search"><span>Find node</span><input aria-label="Search topology nodes" value={nodeSearch} onChange={event=>setNodeSearch(event.target.value)} placeholder="Name, ID, type or template"/></label>
     <span className="topology-search-count" role="status">{nodes.filter(node=>!nodeSearch.trim()||[node.name,node.id,node.node_type,node.template_id].some(value=>String(value||"").toLowerCase().includes(nodeSearch.trim().toLowerCase()))).length} / {nodes.length} nodes</span>
     <div className="topology-canvas-actions">
      <Button type="button" variant="outline" size="sm" onClick={()=>zoomCanvas(0.8)} aria-label="Zoom in">Zoom in</Button>
      <Button type="button" variant="outline" size="sm" onClick={()=>zoomCanvas(1.25)} aria-label="Zoom out">Zoom out</Button>
      <Button type="button" variant="ghost" size="sm" onClick={fitCanvas}>Fit to nodes</Button>
     </div>
     <div className="topology-canvas-actions" aria-label="Topology edit history and selection">
      <Button type="button" size="sm" variant="outline" onClick={undoTopologyEdit} disabled={!historyRef.current.canUndo}>Undo</Button>
      <Button type="button" size="sm" variant="outline" onClick={redoTopologyEdit} disabled={!historyRef.current.canRedo}>Redo</Button>
      <Button type="button" size="sm" variant="ghost" onClick={copyTopology} disabled={!selectedNodes.length&&!selectedLink}>Copy</Button>
      <Button type="button" size="sm" variant="ghost" onClick={pasteTopology} disabled={!canManage||!clipboardRef.current}>Paste</Button>
      <Button type="button" size="sm" variant="ghost" onClick={selectAllNodes} disabled={!nodes.length}>Select all</Button>
      <Button type="button" size="sm" variant="destructive" onClick={deleteSelectedTopology} disabled={!canManage||(!selectedNodes.length&&!selectedLink)}>Delete selected</Button>
     </div>
    </div>
    <p className="muted topology-keyboard-help">Shortcuts: Ctrl/Cmd+Z undo · Ctrl/Cmd+Shift+Z redo · Ctrl/Cmd+C/V copy/paste · Ctrl/Cmd+A select all · Delete remove · Shift/Ctrl/Cmd+click add or remove nodes from selection. Shortcuts are disabled while editing form fields.</p>
    <div style={{width:"100%",overflow:"hidden",border:"1px solid var(--border)",borderRadius:12,background:"var(--card)"}}>
     <svg ref={canvasRef} viewBox={viewport.x+" "+viewport.y+" "+viewport.width+" "+viewport.height} role="application" aria-label="Interactive topology canvas. Select nodes and links, drag to move, or drag empty space to pan." style={{display:"block",width:"100%",minWidth:0,height:"auto",aspectRatio:"1000 / 620",touchAction:"none",cursor:panning?"grabbing":"grab"}}
      onPointerDown={startCanvasPan} onPointerMove={onCanvasPointerMove} onPointerUp={finishCanvasInteraction} onPointerCancel={finishCanvasInteraction} onWheel={zoomCanvasAtPointer}>
      <defs><pattern id="topology-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M 25 0 L 0 0 0 25" fill="none" stroke="currentColor" strokeOpacity=".08" strokeWidth="1"/></pattern></defs>
      <rect data-canvas-background="true" x="0" y="0" width="10000" height="10000" fill="url(#topology-grid)"/>
      {links.map(link=>{
       const source=nodeById[link.source_node_id],target=nodeById[link.target_node_id];
       return source&&target?<g key={link.id} role="button" tabIndex="0"
        aria-label={"Select link "+link.id+" from "+source.name+" port "+link.source_adapter+"/"+link.source_port+" to "+target.name+" port "+link.target_adapter+"/"+link.target_port}
        aria-pressed={selectedLink===link.id}
        onPointerDown={event=>event.stopPropagation()}
        onClick={event=>{event.stopPropagation();selectCanvasLink(link);}}
        onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();selectCanvasLink(link);}}}
        style={{cursor:"pointer"}}>
        <line x1={source.x+68} y1={source.y} x2={target.x-68} y2={target.y} stroke={selectedLink===link.id?"var(--warning)":"var(--primary)"} strokeWidth={selectedLink===link.id?8:4}/>
        <circle cx={source.x+68} cy={source.y} r="6" fill={selectedLink===link.id?"var(--warning)":"var(--primary)"}/>
        <circle cx={target.x-68} cy={target.y} r="6" fill={selectedLink===link.id?"var(--warning)":"var(--primary)"}/>
        <text x={(source.x+target.x)/2} y={(source.y+target.y)/2-8} fill="currentColor" fontSize="12">{link.source_adapter}/{link.source_port} ↔ {link.target_adapter}/{link.target_port}</text>
       </g>:null;
      })}
      {nodes.map(node=>{
       const matches=!nodeSearch.trim()||[node.name,node.id,node.node_type,node.template_id].some(value=>String(value||"").toLowerCase().includes(nodeSearch.trim().toLowerCase()));
       return <g key={node.id} transform={"translate("+node.x+" "+node.y+")"}
        role="button" tabIndex="0" aria-label={"Select node "+node.name} aria-pressed={selectedNodes.includes(node.id)}
        onPointerDown={event=>{setPanning(null);startNodeDrag(event,node.id);}}
        onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();setSelectedNodes(current=>current.includes(node.id)?current:[node.id]);setSelectedNode(node.id);setSelectedLink("");}}}
        style={{cursor:"grab",outline:"none"}} opacity={matches?1:0.25}>
        <rect x="-68" y="-34" width="136" height="68" rx="12" fill={selectedNodes.includes(node.id)?"var(--primary)":"var(--muted)"} stroke={nodeSearch.trim()&&matches?"var(--warning)":selectedNodes.includes(node.id)?"var(--primary)":"var(--border)"} strokeWidth={nodeSearch.trim()&&matches?4:selectedNodes.includes(node.id)?4:2}/>
        <text x="0" y="-4" textAnchor="middle" fill={selectedNode===node.id?"white":"currentColor"} fontSize="14" fontWeight="600">{node.name.slice(0,18)}</text>
        <text x="0" y="16" textAnchor="middle" fill={selectedNode===node.id?"white":"currentColor"} fontSize="10">{node.node_type} · {node.id.slice(0,12)}</text>
       </g>;
      })}
     </svg>
    </div>
    {!nodes.length?<EmptyState title="Canvas is empty" message="Add the first node using the palette above. This does not create a provider resource."/>:null}
    {selectedNodes.length>1?<div className="form-grid"><div className="context-caption">{selectedNodes.length} nodes selected · {canManage?"drag any selected node to move the group together.":"view-only selection."}</div>{canManage?<div className="form-actions"><Button type="button" variant="destructive" onClick={deleteSelectedTopology}>Delete selected nodes and attached links</Button></div>:null}</div>:null}
    {selectedNodeRecord?<div className="form-grid">
     <Field label="Selected node"><input value={selectedNodeRecord.name} onChange={event=>updateNode(selectedNode,{name:event.target.value})} disabled={!canManage}/></Field>
     <Field label="Logical node type"><select value={selectedNodeRecord.node_type} onChange={event=>updateNode(selectedNode,{node_type:event.target.value})} disabled={!canManage}>{NODE_TYPES.map(item=><option key={item}>{item}</option>)}</select></Field>
     <Field label="Template reference"><input value={selectedNodeRecord.template_id} onChange={event=>updateNode(selectedNode,{template_id:event.target.value})} disabled={!canManage}/></Field>
     <Field label="X coordinate"><input type="number" min="0" max="10000" value={selectedNodeRecord.x} onChange={event=>updateNode(selectedNode,{x:Number(event.target.value)})} disabled={!canManage}/></Field>
     <Field label="Y coordinate"><input type="number" min="0" max="10000" value={selectedNodeRecord.y} onChange={event=>updateNode(selectedNode,{y:Number(event.target.value)})} disabled={!canManage}/></Field>
     <div className="form-actions"><Button type="button" variant="destructive" onClick={()=>removeNode(selectedNode)} disabled={!canManage}>Remove node and attached links</Button></div>
    </div>:null}
   </Section>
   <Section title="Interface and link editor" subtitle="Select a canvas link to inspect or edit its endpoint adapter/port references. Port occupancy is validated by the canonical backend validator.">
    {selectedLinkRecord&&linkEditForm?<form className="form-grid" onSubmit={saveSelectedLink}>
     <div className="context-caption">Selected link · {selectedLinkRecord.id}</div>
     <Field label="Edit source node"><select value={linkEditForm.source_node_id} onChange={event=>setLinkEditForm({...linkEditForm,source_node_id:event.target.value})}>{nodes.map(item=><option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></Field>
     <Field label="Edit source adapter"><input type="number" min="0" max="255" value={linkEditForm.source_adapter} onChange={event=>setLinkEditForm({...linkEditForm,source_adapter:event.target.value})}/></Field>
     <Field label="Edit source port"><input type="number" min="0" max="255" value={linkEditForm.source_port} onChange={event=>setLinkEditForm({...linkEditForm,source_port:event.target.value})}/></Field>
     <Field label="Edit target node"><select value={linkEditForm.target_node_id} onChange={event=>setLinkEditForm({...linkEditForm,target_node_id:event.target.value})}>{nodes.map(item=><option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></Field>
     <Field label="Edit target adapter"><input type="number" min="0" max="255" value={linkEditForm.target_adapter} onChange={event=>setLinkEditForm({...linkEditForm,target_adapter:event.target.value})}/></Field>
     <Field label="Edit target port"><input type="number" min="0" max="255" value={linkEditForm.target_port} onChange={event=>setLinkEditForm({...linkEditForm,target_port:event.target.value})}/></Field>
     <div className="form-actions"><Button type="submit" disabled={!canManage}>Save link endpoint changes</Button><Button type="button" variant="destructive" onClick={()=>removeLink(selectedLink)} disabled={!canManage}>Remove link</Button></div>
    </form>:<p className="muted">Select a connection on the canvas or from the links table to inspect its endpoints.</p>}
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
     {key:"id",label:"Link ID",render:item=><button type="button" className="table-link-select" aria-pressed={selectedLink===item.id} onClick={()=>selectCanvasLink(item)}>{item.id}</button>},
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
   {canManage?<Section title="Save immutable topology revision" subtitle="Validate the visual draft against the canonical backend rules, then save a new immutable revision with a SHA-256 identity. Existing revisions are never overwritten.">
    {validation?<div className="provider-plan"><p><StatusBadge value={validation.valid?"VALID":"INVALID"}/> {validation.valid?validation.node_count+" nodes · "+validation.link_count+" links · SHA-256 "+validation.content_sha256:validation.error}</p></div>:null}
    <div className="button-row">
     <Button type="button" variant="outline" onClick={validateDraft} loading={validationLoading} disabled={!profileId||!canManage||mutation.loading}>Validate current draft</Button>
     <Button onClick={saveRevision} loading={mutation.loading} disabled={!profileId||!canManage||validationLoading}>Validate and save new draft revision</Button>
     {canPublish?<Button variant="outline" onClick={publishRevision} disabled={!revisionId||selectedRevision?.status!=="DRAFT"||mutation.loading}>Publish selected revision</Button>:null}
    </div>
   </Section>:null}
  </>:<EmptyState title="Select or create a topology profile" message="Choose a Project and a profile to open the local topology canvas."/>}
 </div>;
}
