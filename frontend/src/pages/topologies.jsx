import React,{useEffect,useRef,useState} from "react";
import {api} from "@/api";
import {useWorkspace} from "@/components/workspace-context";
import {useAsyncLoader,useMutation} from "@/hooks";
import {canPerform} from "@/permissions";
import {autoLayoutTopology,copyTopologySelection,createTopologyHistory,moveTopologyNodes,pasteTopologySelection,removeTopologySelection} from "@/topology-editor";
import {createDefaultPresentation,fitPresentationViewport,movePresentationNodes,presentationLayerLocked,presentationLayerVisible,presentationLinkPath,presentationPortPoint,resolveTopologyPresentation,updatePresentationNodePosition,zoomPresentationViewport} from "@/topology-presentation";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

export const DEFAULT_TOPOLOGY_VIEWPORT=Object.freeze({x:0,y:0,width:1000,height:620});
const VIEWPORT_RATIO=0.62;
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));

export function zoomTopologyViewport(viewport,factor,anchorX=0.5,anchorY=0.5){
 const width=clamp(viewport.width*factor,250,16000);
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
 const width=clamp(Math.max(420,maxX-minX+260,(maxY-minY+260)/VIEWPORT_RATIO),250,16000);
 const height=width*VIEWPORT_RATIO;
 const centerX=(minX+maxX)/2,centerY=(minY+maxY)/2;
 return {
  x:clamp(centerX-width/2,0,Math.max(0,10000-width)),
  y:clamp(centerY-height/2,0,Math.max(0,10000-height)),
  width,height,
 };
}

const NODE_PALETTE=[
 {group:"Routers",label:"Cisco IOS Router",node_type:"ROUTER",vendor:"Cisco",operating_system:"IOS",image:"IOSv"},
 {group:"Routers",label:"Arista Router",node_type:"ROUTER",vendor:"Arista",operating_system:"EOS",image:"vEOS"},
 {group:"Routers",label:"Juniper Router",node_type:"ROUTER",vendor:"Juniper",operating_system:"Junos",image:"vSRX"},
 {group:"Routers",label:"FRR Router",node_type:"ROUTER",vendor:"FRRouting",operating_system:"FRR",image:"FRR"},
 {group:"Routers",label:"VyOS Router",node_type:"ROUTER",vendor:"VyOS",operating_system:"VyOS",image:"VyOS"},
 {group:"Switches",label:"Cisco Switch",node_type:"SWITCH",vendor:"Cisco",operating_system:"IOS",image:"IOSvL2"},
 {group:"Switches",label:"Arista Switch",node_type:"SWITCH",vendor:"Arista",operating_system:"EOS",image:"vEOS"},
 {group:"Switches",label:"Open vSwitch",node_type:"SWITCH",vendor:"Open vSwitch",operating_system:"Linux",image:"Open vSwitch"},
 {group:"Firewalls",label:"Palo Alto Firewall",node_type:"OTHER",vendor:"Palo Alto",operating_system:"PAN-OS",image:"VM-Series"},
 {group:"Firewalls",label:"Linux Firewall",node_type:"OTHER",vendor:"Linux",operating_system:"nftables",image:"Linux"},
 {group:"Wireless",label:"OpenWrt Access Point",node_type:"ACCESS_POINT",vendor:"OpenWrt",operating_system:"OpenWrt",image:"OpenWrt"},
 {group:"Wireless",label:"hostapd Access Point",node_type:"ACCESS_POINT",vendor:"Linux",operating_system:"hostapd",image:"Linux"},
 {group:"Servers",label:"Linux Server",node_type:"OTHER",vendor:"Linux",operating_system:"Ubuntu",image:"Ubuntu Server"},
 {group:"Servers",label:"Docker Host",node_type:"OTHER",vendor:"Docker",operating_system:"Linux",image:"Docker"},
 {group:"Endpoints",label:"Linux Client",node_type:"CLIENT",vendor:"Linux",operating_system:"Ubuntu",image:"Ubuntu Desktop"},
 {group:"Endpoints",label:"Windows Client",node_type:"CLIENT",vendor:"Microsoft",operating_system:"Windows",image:"Windows"},
 {group:"Network utilities",label:"NAT Gateway",node_type:"OTHER",vendor:"NetRegress",operating_system:"NAT",image:"NAT"},
 {group:"Network utilities",label:"Linux Bridge",node_type:"SWITCH",vendor:"Linux",operating_system:"Bridge",image:"Linux bridge"},
 {group:"Network utilities",label:"Cloud Connection",node_type:"CLOUD",vendor:"NetRegress",operating_system:"Cloud",image:"Cloud"},
 {group:"Network utilities",label:"Network Segment",node_type:"OTHER",vendor:"NetRegress",operating_system:"Segment",image:"Network segment"},
];
const PALETTE_GROUPS=[...new Set(NODE_PALETTE.map(item=>item.group))];
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
 const [linkForm,setLinkForm]=useState({source_node_id:"",source_adapter:0,source_port:0,source_interface_name:"",target_node_id:"",target_adapter:0,target_port:0,target_interface_name:"",link_type:"ETHERNET",network_segment_id:"",vlan_id:""});
 const [interfaceForm,setInterfaceForm]=useState({name:"GigabitEthernet0/0",adapter:0,port:0,mode:"ROUTED",ip_address:"",vlan_id:""});
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
 const [presentationDraft,setPresentationDraft]=useState(null);
 const [presentationDirty,setPresentationDirty]=useState(false);
 const [panning,setPanning]=useState(null);
 const [nodeSearch,setNodeSearch]=useState("");
 const [consoleTab,setConsoleTab]=useState("validation");
 const [sessionLogs,setSessionLogs]=useState([]);
 const [paletteDropActive,setPaletteDropActive]=useState(false);
 const [portSelection,setPortSelection]=useState(null);
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const [showProfileForm,setShowProfileForm]=useState(false);
 const [packetTracerFile,setPacketTracerFile]=useState(null);
 const [packetTracerName,setPacketTracerName]=useState("Packet Tracer import");
 const [packetTracerScope,setPacketTracerScope]=useState("PROJECT");
 const [packetTracerLabId,setPacketTracerLabId]=useState("");
 const [packetTracerBusy,setPacketTracerBusy]=useState(false);
 const [packetTracerResult,setPacketTracerResult]=useState(null);
 const [nativeFile,setNativeFile]=useState(null);
 const [nativeName,setNativeName]=useState("Native topology import");
 const [nativeScope,setNativeScope]=useState("PROJECT");
 const [nativeLabId,setNativeLabId]=useState("");
 const [nativeBusy,setNativeBusy]=useState(false);
 const [nativeImportResult,setNativeImportResult]=useState(null);
 const profiles=useAsyncLoader(()=>projectId?api.topologies(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"topology-studio-profiles"});
 const revisions=useAsyncLoader(()=>profileId?api.topologyRevisions(profileId):Promise.resolve({items:[]}),[profileId],{enabled:Boolean(profileId),queryKey:"topology-studio-revisions"});
 const presentationRevisions=useAsyncLoader(()=>profileId&&revisionId?api.topologyPresentationRevisions(profileId,revisionId):Promise.resolve({items:[]}),[profileId,revisionId],{enabled:Boolean(profileId&&revisionId),queryKey:"topology-presentation-revisions"});
 const nativeSources=useAsyncLoader(()=>profileId?api.topologyNativeSources(profileId):Promise.resolve({items:[]}),[profileId],{enabled:Boolean(profileId),queryKey:"topology-native-sources"});
 const nativeArtifacts=useAsyncLoader(()=>profileId?api.topologyNativeArtifacts(profileId):Promise.resolve({items:[]}),[profileId],{enabled:Boolean(profileId),queryKey:"topology-native-artifacts"});
 const mutation=useMutation();
 const projectRows=projects.data?.items||[];
 const profileRows=profiles.data?.items||[];
 const revisionRows=revisions.data?.items||[];
 const presentationRevisionRows=presentationRevisions.data?.items||[];
 const nativeArtifactRows=(nativeArtifacts.data?.items||[]).filter(item=>["GNS3_PROJECT","CML_LAB","EVE_NG_UNL","CISCO_PACKET_TRACER_PKT"].includes(item.format_id));
 const nodes=definition.nodes||[];
 const links=definition.links||[];
 const selectedRevision=revisionRows.find(item=>item.revision_id===revisionId)||null;
 const activePresentationRevision=presentationRevisionRows.filter(item=>item.topology_revision_id===revisionId&&item.presentation).sort((a,b)=>(b.revision_number||0)-(a.revision_number||0))[0]||null;
 const activePresentation=presentationDraft||activePresentationRevision?.presentation||createDefaultPresentation(definition);
 const presentationModel=resolveTopologyPresentation(definition,activePresentation);
 const isNativePresentation=presentationModel.layoutOrigin==="NATIVE";
 const renderNodes=presentationModel.nodes;
 const renderNodeById=presentationModel.nodeById;
 const activeProfile=profileRows.find(item=>item.profile_id===profileId)||null;
 const activeLabId=activeProfile?.scope_type==="LAB"?activeProfile.lab_id:"";
 const [bindingForm,setBindingForm]=useState({provider_id:"gns3",endpoint_url:"http://127.0.0.1:3080",provider_workspace_id:"",gns3_project_id:"",controller_device_id:"",credential_id:""});
 const providerBinding=useAsyncLoader(()=>activeLabId?api.topologyProviderBinding(activeLabId):Promise.resolve({binding:null}),[activeLabId],{enabled:Boolean(activeLabId),queryKey:"topology-provider-binding"});
 const applyHistory=useAsyncLoader(()=>profileId&&activeLabId?api.topologyApplies(profileId):Promise.resolve({items:[]}),[profileId,activeLabId],{enabled:Boolean(profileId&&activeLabId),queryKey:"topology-apply-history"});
 const providerDevices=useAsyncLoader(()=>activeLabId&&projectId?api.devices(projectId,activeLabId,"ACTIVE"):Promise.resolve({items:[]}),[activeLabId,projectId],{enabled:Boolean(activeLabId&&projectId),queryKey:"topology-provider-devices"});
 const providerCredentials=useAsyncLoader(()=>bindingForm.controller_device_id?api.credentials(projectId,bindingForm.controller_device_id):Promise.resolve({items:[]}),[projectId,bindingForm.controller_device_id],{enabled:Boolean(projectId&&bindingForm.controller_device_id),queryKey:"topology-provider-credentials"});
 const nodeCredentials=useAsyncLoader(()=>projectId?api.credentials(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId&&canPerform(user,"credentials.read")),queryKey:"topology-node-credential-references"});
 const configurationProfiles=useAsyncLoader(()=>projectId?api.configurationProfiles(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId&&canPerform(user,"configurations.read")),queryKey:"topology-node-configuration-profiles"});
 const [providerCatalog,setProviderCatalog]=useState(null);
 const [providerPlan,setProviderPlan]=useState(null);
 const [providerInterfaces,setProviderInterfaces]=useState(null);
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
 useEffect(()=>{setProviderInterfaces(null);},[selectedNode,activeLabId]);
 useEffect(()=>{
  setProviderCatalog(null);setProviderPlan(null);setProviderInterfaces(null);setReconciliation(null);setLastApply(null);
  setConfirmApply(false);setProviderError("");
  setBindingForm({provider_id:"gns3",endpoint_url:"http://127.0.0.1:3080",provider_workspace_id:"",gns3_project_id:"",controller_device_id:"",credential_id:""});
 },[activeLabId]);
 useEffect(()=>{
  const item=providerBinding.data?.binding;
  if(item)setBindingForm({provider_id:item.provider_id||"gns3",endpoint_url:item.endpoint_url,
   provider_workspace_id:item.provider_workspace_id||item.gns3_project_id||"",gns3_project_id:item.gns3_project_id||item.provider_workspace_id||"",
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
  if(!revisionId)return;
  const matching=(presentationRevisions.data?.items||[]).filter(item=>item.topology_revision_id===revisionId&&item.presentation).sort((a,b)=>(b.revision_number||0)-(a.revision_number||0));
  const selected=matching[0]?.presentation||createDefaultPresentation(revisionRows.find(item=>item.revision_id===revisionId)?.definition||definitionRef.current);
  setPresentationDraft(selected);setPresentationDirty(false);
  if(selected.viewport?.width&&selected.viewport?.height)setViewport({x:selected.viewport.x,y:selected.viewport.y,width:selected.viewport.width,height:selected.viewport.height});
  else setViewport(fitPresentationViewport(resolveTopologyPresentation(revisionRows.find(item=>item.revision_id===revisionId)?.definition||definitionRef.current,selected).nodes));
 },[revisionId,presentationRevisions.data,revisions.data]);
 useEffect(()=>{
  if(!nodes.some(item=>item.id===linkForm.source_node_id))
   setLinkForm(value=>({...value,source_node_id:nodes[0]?.id||""}));
 },[definition.nodes]);
 useEffect(()=>{
  if(!nodes.some(item=>item.id===linkForm.target_node_id))
   setLinkForm(value=>({...value,target_node_id:nodes[1]?.id||nodes[0]?.id||""}));
 },[definition.nodes]);



 async function importPacketTracer(event){
  event.preventDefault();
  if(!canManage||!projectId||!packetTracerFile||!packetTracerName.trim())return;
  if(packetTracerScope==="LAB"&&!packetTracerLabId.trim()){
   setError("Enter the Lab ID for a Lab-scoped Packet Tracer import.");return;
  }
  setPacketTracerBusy(true);setError("");setNotice("");setPacketTracerResult(null);
  try{
   const payload=new FormData();
   payload.set("project_id",projectId);
   payload.set("name",packetTracerName.trim());
   payload.set("scope_type",packetTracerScope);
   if(packetTracerScope==="LAB")payload.set("scope_id",packetTracerLabId.trim());
   payload.set("file",packetTracerFile);
   const result=await api.importPacketTracerTopology(payload);
   setPacketTracerResult(result);
   setProfileId(result.profile.profile_id);
   setRevisionId(result.revision.revision_id);
   resetEditorDefinition(result.revision.definition||emptyDefinition());
   setNotice("Packet Tracer project imported as a new immutable native source and a DRAFT topology revision. Provider templates remain unmapped until explicitly selected.");
   setPacketTracerFile(null);
   await profiles.reload().catch(()=>null);
  }catch(exc){
   setError(exc.message||"Packet Tracer import failed.");
  }finally{
   setPacketTracerBusy(false);
  }
 }
 async function exportPacketTracer(sourceId){
  if(!canManage||!profileId||!revisionId)return;
  setPacketTracerBusy(true);setError("");setNotice("");
  try{
   const result=await api.exportPacketTracerRevision(profileId,sourceId,revisionId);
   const url=window.URL.createObjectURL(result.blob);
   const anchor=document.createElement("a");
   anchor.href=url;anchor.download=result.filename||"packet-tracer-export.pkt";
   document.body.appendChild(anchor);anchor.click();anchor.remove();
   window.URL.revokeObjectURL(url);
   setNotice("Packet Tracer .pkt export generated and codec-read-back verified. Reopening in the Packet Tracer desktop application has not been verified by this environment.");
  }catch(exc){
   setError(exc.message||"Packet Tracer export failed.");
  }finally{
   setPacketTracerBusy(false);
  }
 }

 async function importNativeProject(event){
  event.preventDefault();
  if(!canManage||!projectId||!nativeFile||!nativeName.trim())return;
  if(nativeScope==="LAB"&&!nativeLabId.trim()){
   setError("Enter the Lab ID for a Lab-scoped native topology import.");return;
  }
  setNativeBusy(true);setError("");setNotice("");setNativeImportResult(null);
  try{
   const payload=new FormData();
   payload.set("project_id",projectId);
   payload.set("name",nativeName.trim());
   payload.set("scope_type",nativeScope);
   if(nativeScope==="LAB")payload.set("scope_id",nativeLabId.trim());
   payload.set("file",nativeFile);
   const result=await api.importNativeTopology(payload);
   setNativeImportResult(result);
   setProfileId(result.profile.profile_id);
   setRevisionId(result.revision.revision_id);
   resetEditorDefinition(result.revision.definition||emptyDefinition());
   setNativeFile(null);
   setNotice(result.report?.format_id+" project imported into a new DRAFT topology profile. Publish the canonical and presentation revisions before export.");
   await profiles.reload().catch(()=>null);
  }catch(exc){
   setError(exc.message||"Native topology import failed.");
  }finally{
   setNativeBusy(false);
  }
 }
 async function exportNativeProject(sourceId){
  if(!canManage||!profileId||!selectedRevision)return;
  const presentation=presentationRevisionRows.find(item=>item.status==="PUBLISHED"&&item.source_artifact_id===sourceId&&item.topology_revision_id===revisionId);
  if(selectedRevision.status!=="PUBLISHED"||!presentation){
   setError("Publish the selected topology revision and its matching native presentation snapshot before exporting.");return;
  }
  setNativeBusy(true);setError("");setNotice("");
  try{
   const result=await api.exportNativeTopologyArtifact(profileId,sourceId,revisionId,presentation.presentation_id);
   const url=window.URL.createObjectURL(result.blob);
   const anchor=document.createElement("a");
   anchor.href=url;anchor.download=result.filename||"native-topology-export";
   document.body.appendChild(anchor);anchor.click();anchor.remove();
   window.URL.revokeObjectURL(url);
   setNotice("Native project serialized and source-integrity checked. The originating GNS3, CML or EVE-NG application reopen is still an external acceptance test.");
  }catch(exc){
   setError(exc.message||"Native topology export failed.");
  }finally{
   setNativeBusy(false);
  }
 }

 function appendSessionLog(level,message){
  const entry={id:localId("log"),at:new Date().toISOString(),level,message:String(message||"")};
  setSessionLogs(items=>[entry,...items].slice(0,100));
 }
 function updateNodeField(nodeId,field,value){
  if(!canManage)return;
  setEditorDefinition(current=>({
   ...current,
   nodes:current.nodes.map(node=>{
    if(node.id!==nodeId)return node;
    const next={...node};
    if(value===undefined||value===null||value==="")delete next[field];
    else next[field]=value;
    return next;
   }),
  }));
 }
 function addNodeFromPalette(item,point){
  if(!canManage)return null;
  if(nodes.length>=128){setError("The canonical topology limit is 128 nodes.");return null;}
  const ordinal=nodes.length+1;
  const node={
   id:localId("node"),name:item.label+" "+ordinal,node_type:item.node_type,template_id:"",
   x:Math.round(point?.x??(160+(ordinal%5)*150)),
   y:Math.round(point?.y??(180+Math.floor((ordinal-1)/5)*120)),
   properties:{},vendor:item.vendor,operating_system:item.operating_system,image:item.image,interfaces:[],
  };
  setEditorDefinition(value=>({...value,nodes:[...value.nodes,node]}));
  setSelectedNode(node.id);setSelectedNodes([node.id]);setSelectedLink("");setLinkEditForm(null);
  setNotice("Logical node added. Choose a provider template only when a provider mapping is available.");
  appendSessionLog("INFO","Added logical node "+node.name+" ("+node.node_type+")");
  return node;
 }
 function startPaletteDrag(event,item){
  if(!canManage){event.preventDefault();return;}
  const index=NODE_PALETTE.indexOf(item);
  event.dataTransfer?.setData("application/x-netregress-topology-node",String(index));
  event.dataTransfer?.setData("text/plain","netregress-topology-node:"+index);
  if(event.dataTransfer)event.dataTransfer.effectAllowed="copy";
 }
 function allowPaletteDrop(event){
  if(!canManage)return;
  event.preventDefault();
  if(event.dataTransfer)event.dataTransfer.dropEffect="copy";
  setPaletteDropActive(true);
 }
 function dropPaletteNode(event){
  event.preventDefault();setPaletteDropActive(false);
  if(!canManage)return;
  const raw=event.dataTransfer?.getData("application/x-netregress-topology-node")
   ||event.dataTransfer?.getData("text/plain")?.replace("netregress-topology-node:","");
  if(typeof raw!=="string"||!raw.trim())return;
  const index=Number(raw);
  if(!Number.isInteger(index)||index<0||index>=NODE_PALETTE.length)return;
  addNodeFromPalette(NODE_PALETTE[index],canvasPoint(event));
 }
 function autoLayoutDraft(){
  if(!canManage||!nodes.length)return;
  const arranged=autoLayoutTopology(definitionRef.current);
  setEditorDefinition(arranged);
  setViewport(fitTopologyViewport(arranged.nodes));
  setNotice("Automatic layered layout applied to the local draft.");
  appendSessionLog("INFO","Applied automatic topology layout to "+nodes.length+" nodes");
 }
 function addNodeInterface(nodeId){
  if(!canManage)return;
  const name=String(interfaceForm.name||"").trim();
  const adapter=Number(interfaceForm.adapter),port=Number(interfaceForm.port);
  if(!name||!Number.isInteger(adapter)||!Number.isInteger(port)||adapter<0||adapter>255||port<0||port>255){
   setError("Enter an interface name and valid adapter/port numbers from 0 to 255.");return;
  }
  const existing=nodes.find(node=>node.id===nodeId)?.interfaces||[];
  if(existing.length>=64){setError("A logical node can declare at most 64 interfaces.");return;}
  if(existing.some(item=>item.name===name||(item.adapter===adapter&&item.port===port))){
   setError("Interface names and adapter/port assignments must be unique on a node.");return;
  }
  const item={name,adapter,port,mode:interfaceForm.mode};
  if(interfaceForm.ip_address.trim())item.ip_address=interfaceForm.ip_address.trim();
  if(String(interfaceForm.vlan_id).trim())item.vlan_id=Number(interfaceForm.vlan_id);
  updateNode(nodeId,{interfaces:[...existing,item].sort((a,b)=>a.adapter-b.adapter||a.port-b.port)});
  setInterfaceForm(value=>({...value,name:"Ethernet"+(existing.length+1),port:Number(value.port)+1,ip_address:"",vlan_id:""}));
  setError("");
  appendSessionLog("INFO","Added planned interface "+name+" to "+nodeId);
 }
 function removeNodeInterface(nodeId,interfaceName){
  if(!canManage)return;
  const referenced=links.some(link=>
   (link.source_node_id===nodeId&&link.source_interface_name===interfaceName)
   ||(link.target_node_id===nodeId&&link.target_interface_name===interfaceName)
  );
  if(referenced){setError("This interface is referenced by a link. Remove or reassign that link first.");return;}
  const node=nodes.find(item=>item.id===nodeId);
  updateNode(nodeId,{interfaces:(node?.interfaces||[]).filter(item=>item.name!==interfaceName)});
 }
 function updateNodeInterface(nodeId,interfaceName,patch){
  if(!canManage)return;
  const node=nodes.find(item=>item.id===nodeId);
  updateNode(nodeId,{interfaces:(node?.interfaces||[]).map(item=>item.name===interfaceName?{...item,...patch}:item)});
 }
 function chooseTopologyPort(node,interfaceItem){
  if(!canManage)return;
  const selected={node_id:node.id,interface_name:interfaceItem.name,adapter:interfaceItem.adapter,port:interfaceItem.port};
  if(!portSelection){
   setPortSelection(selected);
   setNotice("Source port "+node.name+" · "+interfaceItem.name+" selected. Choose a destination port.");
   return;
  }
  if(portSelection.node_id===selected.node_id){
   setError("A topology link must connect two different logical nodes.");
   setPortSelection(selected);return;
  }
  if(links.length>=512){setError("The canonical topology limit is 512 links.");setPortSelection(null);return;}
  const link={
   id:localId("link"),
   source_node_id:portSelection.node_id,source_adapter:portSelection.adapter,source_port:portSelection.port,
   source_interface_name:portSelection.interface_name,
   target_node_id:selected.node_id,target_adapter:selected.adapter,target_port:selected.port,
   target_interface_name:selected.interface_name,link_type:"ETHERNET",
  };
  setEditorDefinition(value=>({...value,links:[...value.links,link]}));
  setSelectedLink(link.id);setSelectedNodes([]);setSelectedNode("");setLinkEditForm({...link});
  setPortSelection(null);
  setNotice("Logical link created from the selected ports. Validate before saving.");
  appendSessionLog("INFO","Connected "+portSelection.node_id+"/"+portSelection.interface_name+" to "+selected.node_id+"/"+selected.interface_name);
 }
 function setEditorDefinition(next,{record=true,previous}={}){
  const current=definitionRef.current,candidate=typeof next==="function"?next(current):next,baseline=previous||current;
  if((record&&JSON.stringify(baseline)===JSON.stringify(candidate))||(!record&&JSON.stringify(current)===JSON.stringify(candidate)))return;
  if(record)historyRef.current.commit(candidate,baseline);else historyRef.current.replace(candidate);
  definitionRef.current=candidate;setDefinition(candidate);setValidation(null);
  if(record)setHistoryVersion(value=>value+1);
 }
 function resetEditorDefinition(next){
  const value=next||emptyDefinition();historyRef.current.reset(value);definitionRef.current=value;setDefinition(value);
  setHistoryVersion(value=>value+1);setSelectedNode("");setSelectedNodes([]);setSelectedLink("");setLinkEditForm(null);setPortSelection(null);setValidation(null);
 }
 function undoTopologyEdit(){const value=historyRef.current.undo();if(!value)return;definitionRef.current=value;setDefinition(value);setSelectedNodes(ids=>ids.filter(id=>value.nodes.some(node=>node.id===id)));setSelectedNode(id=>value.nodes.some(node=>node.id===id)?id:"");setSelectedLink(id=>value.links.some(link=>link.id===id)?id:"");setValidation(null);setHistoryVersion(v=>v+1);}
 function redoTopologyEdit(){const value=historyRef.current.redo();if(!value)return;definitionRef.current=value;setDefinition(value);setSelectedNodes(ids=>ids.filter(id=>value.nodes.some(node=>node.id===id)));setSelectedNode(id=>value.nodes.some(node=>node.id===id)?id:"");setSelectedLink(id=>value.links.some(link=>link.id===id)?id:"");setValidation(null);setHistoryVersion(v=>v+1);}
 function copyTopology(){const value=copyTopologySelection(definitionRef.current,selectedNodes,selectedLink);if(!value.nodes.length){clipboardRef.current=null;return;}clipboardRef.current=value;setNotice(value.nodes.length+" node(s) and "+value.links.length+" internal link(s) copied.");}
 function pasteTopology(){if(!canManage||!clipboardRef.current)return;try{const result=pasteTopologySelection(definitionRef.current,clipboardRef.current,{offset:40,idFactory:localId});setEditorDefinition(result.definition);setSelectedNodes(result.nodeIds);setSelectedNode(result.nodeIds[0]||"");setSelectedLink("");setNotice(result.nodeIds.length+" node(s) pasted with new logical IDs.");}catch(exc){setError(exc.message||"Clipboard content could not be pasted.");}}
 function deleteSelectedTopology(){if(!canManage||(!selectedNodes.length&&!selectedLink))return;setEditorDefinition(removeTopologySelection(definitionRef.current,selectedNodes,selectedLink));setSelectedNodes([]);setSelectedNode("");setSelectedLink("");setLinkEditForm(null);}
 function selectCanvasLink(link){setSelectedLink(link.id);setSelectedNodes([]);setSelectedNode("");setLinkEditForm({...link,link_type:link.link_type||"ETHERNET"});}
 function saveSelectedLink(event){event?.preventDefault?.();if(!canManage||!selectedLink||!linkEditForm)return;const next={...linkEditForm,source_adapter:Number(linkEditForm.source_adapter),source_port:Number(linkEditForm.source_port),target_adapter:Number(linkEditForm.target_adapter),target_port:Number(linkEditForm.target_port)};setEditorDefinition(value=>({...value,links:value.links.map(item=>item.id===selectedLink?next:item)}));setNotice("Link endpoint references updated. Validate before saving a revision.");appendSessionLog("INFO","Updated link "+selectedLink+" interface and network intent");}
 function startNodeDrag(event,nodeId){
  event.preventDefault();event.stopPropagation();
  if(!canManage){setSelectedNodes([nodeId]);setSelectedNode(nodeId);setSelectedLink("");return;}
  if(event.ctrlKey||event.metaKey||event.shiftKey){const next=selectedNodes.includes(nodeId)?selectedNodes.filter(id=>id!==nodeId):[...selectedNodes,nodeId];setSelectedNodes(next);setSelectedNode(next[next.length-1]||"");setSelectedLink("");return;}
  if(presentationLayerLocked(renderNodeById[nodeId]?.layout,presentationModel.layers)){setNotice("This native presentation layer is locked; its node placement is read-only.");return;}
  const ids=selectedNodes.includes(nodeId)?selectedNodes:[nodeId];setSelectedNodes(ids);setSelectedNode(nodeId);setSelectedLink("");
  if(isNativePresentation){
   const initial=presentationDraft||activePresentation;
   dragSessionRef.current={mode:"presentation",nodeIds:ids.slice(),start:canvasPoint(event),initialPresentation:JSON.parse(JSON.stringify(initial))};
  }else{
   dragSessionRef.current={mode:"topology",nodeIds:ids.slice(),start:canvasPoint(event),initialDefinition:JSON.parse(JSON.stringify(definitionRef.current))};
  }
  setDragging(nodeId);event.currentTarget.setPointerCapture?.(event.pointerId);
 }
 function finishCanvasInteraction(){
  const session=dragSessionRef.current;
  if(session?.mode==="topology")setEditorDefinition(definitionRef.current,{record:true,previous:session.initialDefinition});
  dragSessionRef.current=null;setDragging("");setPanning(null);
 }
 async function validateDraft(){
  if(!canManage)return null;
  setError("");setNotice("");setValidationLoading(true);
  try{const result=await api.validateTopology({project_id:projectId,profile_id:profileId||undefined,definition:definitionRef.current});setValidation(result);setNotice("Topology definition is valid · SHA-256 "+result.content_sha256);appendSessionLog("INFO","Validated draft: "+result.node_count+" nodes and "+result.link_count+" links");return result;}
  catch(exc){setValidation({valid:false,error:exc.message||"Topology validation failed.",code:exc.code||"INVALID_TOPOLOGY"});setError(exc.message||"Topology validation failed.");appendSessionLog("ERROR","Draft validation failed: "+(exc.message||"Unknown error"));return null;}
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
 },[nodes,selectedNodes,selectedLink,selectedNode,historyVersion]);

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
   appendSessionLog("INFO",success);
   await Promise.all([profiles.reload().catch(()=>null),revisions.reload().catch(()=>null)]);
   return result;
  }catch(exc){
   setError(exc.message||"Topology operation failed.");
   appendSessionLog("ERROR",exc.message||"Topology operation failed.");
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
  const x=viewport.x+(event.clientX-rect.left)*viewport.width/rect.width;
  const y=viewport.y+(event.clientY-rect.top)*viewport.height/rect.height;
  return isNativePresentation?{x,y}:{x:Math.max(0,Math.min(10000,x)),y:Math.max(0,Math.min(10000,y))};
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
  setViewport(value=>isNativePresentation?zoomPresentationViewport(value,factor,anchorX,anchorY):zoomTopologyViewport(value,factor,anchorX,anchorY));
 }
 function zoomCanvasAtPointer(event){
  event.preventDefault();
  const rect=event.currentTarget.getBoundingClientRect();
  const anchorX=(event.clientX-rect.left)/rect.width;
  const anchorY=(event.clientY-rect.top)/rect.height;
  zoomCanvas(event.deltaY<0?0.9:1.1,anchorX,anchorY);
 }
 function fitCanvas(){setViewport(isNativePresentation?fitPresentationViewport(renderNodes):fitTopologyViewport(nodes));}
 function onCanvasPointerMove(event){
  if(panning){
   const rect=event.currentTarget.getBoundingClientRect();
   const dx=(event.clientX-panning.clientX)*panning.viewport.width/rect.width;
   const dy=(event.clientY-panning.clientY)*panning.viewport.height/rect.height;
   setViewport({
    ...panning.viewport,
    x:isNativePresentation?panning.viewport.x-dx:Math.max(0,Math.min(10000-panning.viewport.width,panning.viewport.x-dx)),
    y:isNativePresentation?panning.viewport.y-dy:Math.max(0,Math.min(10000-panning.viewport.height,panning.viewport.y-dy))
   });
   return;
  }
  const session=dragSessionRef.current;if(!session)return;
  const point=canvasPoint(event),dx=Math.round(point.x-session.start.x),dy=Math.round(point.y-session.start.y);
  if(session.mode==="presentation"){
   setPresentationDraft(movePresentationNodes(session.initialPresentation,session.nodeIds,dx,dy));
   setPresentationDirty(true);
  }else{
   setEditorDefinition(moveTopologyNodes(session.initialDefinition,session.nodeIds,dx,dy),{record:false});
  }
 }
 async function saveRevision(event){
  event.preventDefault();if(!canManage)return;
  const checked=await validateDraft();if(!checked?.valid)return;
  const result=await runMutation(()=>api.createTopologyRevision(profileId,{definition:definitionRef.current}),"Immutable topology draft revision created.");
  if(result?.revision_id){setRevisionId(result.revision_id);resetEditorDefinition(result.definition||definitionRef.current);}
 }
 function payloadZoom(value){return Number((1000/value.width).toFixed(4));}
 async function savePresentationSnapshot(){
  if(!canManage||!profileId||!selectedRevision)return;
  if(JSON.stringify(definitionRef.current)!==JSON.stringify(selectedRevision.definition)){
   setError("Save logical topology edits as a new canonical revision before saving its presentation.");return;
  }
  const canonical=selectedRevision.definition||emptyDefinition();
  const existing=presentationDraft||activePresentation;
  const native=existing.layout_origin==="NATIVE"&&Boolean(existing.source_artifact_id);
  const nodeMap=new Map((existing.nodes||[]).map(item=>[item.node_id,item]));
  const linkMap=new Map((existing.links||[]).map(item=>[item.link_id,item]));
  const payload={
   ...existing,schema_version:"1.0",layout_origin:native?"NATIVE":"NETREGRESS",
   coordinate_space:existing.coordinate_space||{unit:"px",origin:"top_left",x_axis:"right",y_axis:"down",scale:1,offset_x:0,offset_y:0},
   canvas:existing.canvas||{width:1000,height:620},
   viewport:{x:viewport.x,y:viewport.y,width:viewport.width,height:viewport.height,zoom:payloadZoom(viewport)},
   grid:existing.grid||{enabled:true,snap:false,size:25},
   layers:existing.layers||[],
   nodes:(canonical.nodes||[]).map(node=>nodeMap.get(node.id)||{node_id:node.id,x:node.x,y:node.y,width:136,height:68,label:node.name||node.id,z_index:0}),
   links:(canonical.links||[]).map(link=>linkMap.get(link.id)||{link_id:link.id,route_style:"direct",z_index:0}),
   drawings:existing.drawings||[],
  };
  const result=await runMutation(
   ()=>api.createTopologyPresentationRevision(profileId,selectedRevision.revision_id,{presentation:payload}),
   "Immutable presentation revision saved; native layout and source provenance retained."
  );
  if(result?.presentation_id){setPresentationDirty(false);await presentationRevisions.reload().catch(()=>null);}
 }
 async function publishPresentationSnapshot(presentationId){
  if(!canPublish||!profileId||!presentationId)return;
  const result=await runMutation(
   ()=>api.publishTopologyPresentationRevision(profileId,presentationId),
   "Canvas presentation snapshot published."
  );
  if(result?.presentation_id)await presentationRevisions.reload().catch(()=>null);
 }
 function restorePresentationViewport(item){
  const saved=item?.presentation?.viewport;
  if(!saved)return;
  setViewport({x:saved.x,y:saved.y,width:saved.width,height:saved.height});
  setNotice("Restored the saved viewport from presentation revision "+item.revision_number+".");
  setError("");
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
   appendSessionLog("INFO",success||"Provider operation completed.");
   return value;
  }catch(exc){
   setProviderError(exc.message||"Provider operation failed.");
   appendSessionLog("ERROR",exc.message||"Provider operation failed.");
   return null;
  }finally{setProviderBusy(false);}
 }
 async function saveProviderBinding(event){
  event.preventDefault();
  if(!activeLabId)return;
  const result=await runProvider(
   ()=>api.bindTopologyProvider(activeLabId,bindingForm),
   "Provider binding verified and saved."
  );
  if(result){
   await providerBinding.reload().catch(()=>null);
   setProviderCatalog(null);setProviderPlan(null);setProviderInterfaces(null);setReconciliation(null);
  }
 }
 async function loadProviderCatalog(){
  const result=await runProvider(()=>api.topologyProviderCatalog(activeLabId),"Read-only provider catalogue loaded.");
  if(result)setProviderCatalog(result.catalog);
 }
 async function makeApplyPlan(){
  if(!profileId||selectedRevision?.status!=="PUBLISHED"){
   setProviderError("Select a published revision before planning provider changes.");return;
  }
  const result=await runProvider(
   ()=>api.planTopologyApply(profileId,{revision_id:revisionId}),
   "Dry-run plan refreshed. No provider resources were changed."
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
 async function inspectSelectedProviderInterfaces(){
  const providerNodeId=reconciliation?.logical_to_provider?.[selectedNode];
  if(!activeLabId||!providerNodeId){
   setProviderError("Refresh reconciliation and select an observed, mapped node before inspecting provider interfaces.");return;
  }
  const result=await runProvider(
   ()=>api.topologyProviderInterfaces(activeLabId,providerNodeId),
   "Provider-observed interfaces refreshed."
  );
  if(result)setProviderInterfaces(result);
 }
 async function refreshReconciliation(){
  if(!profileId||!revisionId)return;
  setProviderInterfaces(null);
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
 const selectedNodeMappingStatus=reconciliation?.logical_to_provider?.[selectedNode]
  ?"MAPPED":reconciliation?.missing_nodes?.includes(selectedNode)?"MISSING":"UNKNOWN";
 const selectedProviderNodeId=reconciliation?.logical_to_provider?.[selectedNode]||"";
 const selectedNodeProviderState=providerCatalog?.nodes?.find(item=>item.node_id===selectedProviderNodeId)?.status||"UNKNOWN";
 const selectedLinkMappingStatus=reconciliation?.logical_to_provider_links?.[selectedLink]
  ?"MAPPED":reconciliation?.mismatched_links?.includes(selectedLink)?"MISMATCHED"
  :reconciliation?.missing_links?.includes(selectedLink)?"MISSING":"UNKNOWN";
 const selectedLinkProviderId=reconciliation?.logical_to_provider_links?.[selectedLink]||"Not mapped";
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
  <Section title="Unified native project import" subtitle="Import supported GNS3, CML, EVE-NG and Cisco Packet Tracer files through the shared codec, canonical topology and immutable provenance workflow.">
   {canManage?<form className="form-grid" onSubmit={importNativeProject}>
    <Field label="New topology profile name" required><input aria-label="Native topology profile name" value={nativeName} onChange={event=>setNativeName(event.target.value)} maxLength={120} required/></Field>
    <Field label="Import scope"><select aria-label="Native topology import scope" value={nativeScope} onChange={event=>setNativeScope(event.target.value)}><option value="PROJECT">Project</option><option value="LAB">Lab</option></select></Field>
    {nativeScope==="LAB"?<Field label="Lab ID" required><input aria-label="Native topology Lab ID" value={nativeLabId} onChange={event=>setNativeLabId(event.target.value)} maxLength={128} required/></Field>:null}
    <Field label="Native project file" required><input aria-label="GNS3 CML EVE-NG or Packet Tracer project file" type="file" accept=".gns3,.yaml,.yml,.virl,.unl,.pkt,application/json,application/yaml,application/xml,text/xml,application/octet-stream" onChange={event=>setNativeFile(event.target.files?.[0]||null)} required/></Field>
    <div className="form-actions"><Button type="submit" loading={nativeBusy} disabled={!projectId||!nativeFile||!nativeName.trim()||(nativeScope==="LAB"&&!nativeLabId.trim())}>Import native project</Button></div>
    <p className="muted">Automatic format detection · maximum 50 MiB · original bytes and SHA-256 retained. Import never connects to a controller, provisions a lab or executes node configurations.</p>
   </form>:<p className="muted">Native project import requires topology.manage permission in the selected Project.</p>}
   {nativeImportResult?.report?<div className="topology-observed-panel">
    <strong>Native import compatibility report</strong>
    <p>{nativeImportResult.report.format_id} · {nativeImportResult.report.format_version} · {nativeImportResult.report.counts?.nodes||0} nodes · {nativeImportResult.report.counts?.links||0} links · {nativeImportResult.report.counts?.drawings||0} drawings</p>
    <p className="muted">Source SHA-256 · {nativeImportResult.source?.sha256}</p>
    {(nativeImportResult.report.warnings||[]).map((item,index)=><p className="muted" key={"native-warning-"+index}>{item}</p>)}
   </div>:null}
  </Section>
  <Section title="Packet Tracer native import" subtitle="Import a .pkt project into the existing canonical topology and retain the original native bytes, hash and conversion report.">
   {canManage?<form className="form-grid" onSubmit={importPacketTracer}>
    <Field label="New topology profile name" required><input aria-label="Packet Tracer profile name" value={packetTracerName} onChange={event=>setPacketTracerName(event.target.value)} maxLength={120} required/></Field>
    <Field label="Import scope">
     <select aria-label="Packet Tracer import scope" value={packetTracerScope} onChange={event=>setPacketTracerScope(event.target.value)}>
      <option value="PROJECT">Project</option><option value="LAB">Lab</option>
     </select>
    </Field>
    {packetTracerScope==="LAB"?<Field label="Lab ID" required><input aria-label="Packet Tracer Lab ID" value={packetTracerLabId} onChange={event=>setPacketTracerLabId(event.target.value)} maxLength={128} required/></Field>:null}
    <Field label="Native .pkt file" required><input aria-label="Packet Tracer .pkt file" type="file" accept=".pkt,application/octet-stream" onChange={event=>setPacketTracerFile(event.target.files?.[0]||null)} required/></Field>
    <div className="form-actions"><Button type="submit" loading={packetTracerBusy} disabled={!projectId||!packetTracerFile||!packetTracerName.trim()||(packetTracerScope==="LAB"&&!packetTracerLabId.trim())}>Import Packet Tracer project</Button></div>
    <p className="muted">Original source bytes are immutable and hash-checked. Import does not create emulator resources or assign provider templates. Files are limited to 3.5 MB.</p>
   </form>:<p className="muted">Packet Tracer import requires topology.manage permission in the selected Project.</p>}
   {packetTracerResult?.report?<div className="topology-observed-panel">
    <strong>Import compatibility report</strong>
    <p>{packetTracerResult.report.counts?.nodes||0} nodes · {packetTracerResult.report.counts?.links||0} links · {packetTracerResult.report.warnings?.length||0} warnings · {packetTracerResult.report.unsupported_objects?.length||0} unsupported object groups</p>
    <p className="muted">Source SHA-256 · {packetTracerResult.source?.sha256}</p>
    {(packetTracerResult.report.warnings||[]).map((item,index)=><p className="muted" key={"pkt-warning-"+index}>{item}</p>)}
   </div>:null}
  </Section>
  {notice?<InlineNotice tone="success">{notice}</InlineNotice>:null}
  {error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  {profileId?<>
   <Section title="Native Packet Tracer sources" subtitle="Source provenance is immutable. Export checks the selected revision against the supported native-edit subset and reports any unsupported changes.">
    {nativeSources.loading&&!nativeSources.data?<LoadingState label="Loading native source records…"/>:null}
    {nativeSources.error?<ErrorState error={nativeSources.error} onRetry={nativeSources.reload}/>:null}
    <DataTable caption="Imported Packet Tracer native sources" rows={nativeSources.data?.items||[]} rowKey={item=>item.source_id} columns={[
     {key:"filename",label:"Source file",render:item=><strong>{item.filename}</strong>},
     {key:"format_version",label:"Native version"},
     {key:"sha256",label:"Source SHA-256",render:item=><code title={item.sha256}>{item.sha256.slice(0,12)}…</code>},
     {key:"size_bytes",label:"Bytes",render:item=>Number(item.size_bytes).toLocaleString()},
     {key:"imported_at",label:"Imported"},
     {key:"compatibility",label:"Warnings",render:item=>(item.compatibility_report?.warnings||[]).length},
     {key:"actions",label:"Action",render:item=><Button type="button" size="sm" variant="outline" onClick={()=>exportPacketTracer(item.source_id)} loading={packetTracerBusy} disabled={!canManage||!selectedRevision}>Export selected revision</Button>},
    ]} emptyTitle="No native Packet Tracer sources" emptyMessage="Import a .pkt file above to retain its source bytes and provenance beside the canonical topology revision."/>
    <p className="muted">The first serializer subset supports device-name and canvas-coordinate edits. Node/device changes, link rewiring and interface/configuration changes are rejected until explicit native mappings exist. Codec round-trip is not the same as reopening in Packet Tracer.</p>
   </Section>
    <Section title="Unified native source artifacts" subtitle="GNS3, CML, EVE-NG and Packet Tracer source files are immutable and hash-verified. Export requires published topology and matching presentation revisions.">
     {nativeArtifacts.loading&&!nativeArtifacts.data?<LoadingState label="Loading native project source records…"/>:null}
     {nativeArtifacts.error?<ErrorState error={nativeArtifacts.error} onRetry={nativeArtifacts.reload}/>:null}
     <DataTable caption="Unified native topology source artifacts" rows={nativeArtifactRows} rowKey={item=>item.source_id} columns={[
      {key:"filename",label:"Source file",render:item=><strong>{item.filename}</strong>},
      {key:"format_id",label:"Format"},
      {key:"format_version",label:"Native version"},
      {key:"sha256",label:"Source SHA-256",render:item=><code title={item.sha256}>{item.sha256.slice(0,12)}…</code>},
      {key:"size_bytes",label:"Bytes",render:item=>Number(item.size_bytes).toLocaleString()},
      {key:"imported_at",label:"Imported"},
      {key:"actions",label:"Action",render:item=><Button type="button" size="sm" variant="outline" onClick={()=>exportNativeProject(item.source_id)} loading={nativeBusy} disabled={!canManage||selectedRevision?.revision_id!==item.topology_revision_id||selectedRevision?.status!=="PUBLISHED"||!presentationRevisionRows.some(view=>view.source_artifact_id===item.source_id&&view.status==="PUBLISHED")}>Export selected revision</Button>},
     ]} emptyTitle="No unified native source artifacts" emptyMessage="Import a supported native project to retain its original file and format/version provenance."/>
     <p className="muted">GNS3, CML and EVE-NG serializers support their documented placement/label subsets. Packet Tracer additionally supports only device-name and X/Y edits. Device/link/configuration changes outside each codec's capability report are rejected rather than discarded. Export read-back does not replace testing the generated file in the originating vendor application.</p>
    </Section>
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
   <Section title="Versioned canvas presentation" subtitle="Store the current canvas viewport, canonical node placement and basic link presentation in an immutable snapshot pinned to this topology hash. The versioned backend schema also accepts native port anchors, route points, drawings, layers and vendor extensions for codec integrations; these advanced fields are not yet editable in this canvas UI.">
    {presentationRevisions.loading&&!presentationRevisions.data?<LoadingState label="Loading presentation revisions…"/>:null}
    {presentationRevisions.error?<ErrorState error={presentationRevisions.error} onRetry={presentationRevisions.reload}/>:null}
    <div className="form-actions">
     <Button type="button" variant="outline" onClick={savePresentationSnapshot} loading={mutation.loading} disabled={!canManage||!selectedRevision||JSON.stringify(definitionRef.current)!==JSON.stringify(selectedRevision.definition)||!presentationDirty}>Save presentation revision</Button>
     {presentationRevisionRows[0]?.presentation?.viewport?<Button type="button" variant="ghost" onClick={()=>restorePresentationViewport(presentationRevisionRows[0])}>Restore latest saved viewport</Button>:null}
    </div>
    <p className="muted">Presentation edits are saved independently from canonical network intent. Native node placement, dimensions, rotations, port anchors, link routes, drawings, layers and grid are read from the immutable presentation revision; moving native nodes does not change device/link semantics. Unavailable external device-image binaries remain source asset references and are identified rather than fabricated.</p>
    <DataTable caption="Topology presentation revision history" rows={presentationRevisionRows} rowKey={item=>item.presentation_id} columns={[
     {key:"revision_number",label:"Presentation revision"},
     {key:"presentation",label:"Layout",render:item=>item.presentation?.layout_origin||"Not recorded"},
     {key:"presentation_sha256",label:"SHA-256",render:item=><code title={item.presentation_sha256}>{item.presentation_sha256.slice(0,14)}…</code>},
     {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
     {key:"created_at",label:"Created"},
     {key:"actions",label:"Action",render:item=>item.status==="DRAFT"&&selectedRevision?.status==="PUBLISHED"&&canPublish?<Button type="button" size="sm" variant="outline" onClick={()=>publishPresentationSnapshot(item.presentation_id)} loading={mutation.loading}>Publish</Button>:item.presentation?.viewport?<Button type="button" size="sm" variant="ghost" onClick={()=>restorePresentationViewport(item)}>Restore view</Button>:null}
    ]} emptyTitle="No presentation snapshots" emptyMessage="Capture a snapshot to persist canvas placement and viewport separately from the canonical network topology."/>
   </Section>
   <Section title="Node palette" subtitle="Drag or select a logical device type. Provider templates and images are mapped separately after selecting a provider.">
    <div className="topology-palette-groups">
     {PALETTE_GROUPS.map(group=><div className="topology-palette-group" key={group}>
      <h3>{group}</h3><div className="topology-palette-items">
       {NODE_PALETTE.filter(item=>item.group===group).map(item=><button key={item.label} type="button" className="topology-palette-item" draggable={canManage} disabled={!canManage} onDragStart={event=>startPaletteDrag(event,item)} onClick={()=>addNodeFromPalette(item)}>
        <span className="topology-palette-glyph">{item.node_type==="ROUTER"?"R":item.node_type==="SWITCH"?"S":item.node_type==="ACCESS_POINT"?"W":item.node_type==="CLIENT"?"C":item.node_type==="CLOUD"?"☁":"N"}</span>
        <span><strong>{item.label}</strong><small>{item.vendor} · {item.operating_system}</small></span>
       </button>)}
      </div>
     </div>)}
    </div>
    <p className="muted">Palette entries define logical intent only. Provider template IDs remain blank until a compatible template is selected.</p>
   </Section>
   <div className="topology-workbench-layout">
   <Section title="Visual canvas" subtitle={isNativePresentation?"Native vendor layout · placement edits are presentation-only · no provider calls":"Drag nodes to position them. Pan by dragging empty canvas; zoom with the wheel or controls. Canvas editing does not issue provider calls."}>
    <div className="topology-canvas-toolbar">
     <label className="topology-node-search"><span>Find node</span><input aria-label="Search topology nodes" value={nodeSearch} onChange={event=>setNodeSearch(event.target.value)} placeholder="Name, ID, type or template"/></label>
     <span className="topology-search-count" role="status">{nodes.filter(node=>!nodeSearch.trim()||[node.name,node.id,node.node_type,node.template_id].some(value=>String(value||"").toLowerCase().includes(nodeSearch.trim().toLowerCase()))).length} / {nodes.length} nodes</span>
     <div className="topology-canvas-actions">
      <Button type="button" variant="outline" size="sm" onClick={()=>zoomCanvas(0.8)} aria-label="Zoom in">Zoom in</Button>
      <Button type="button" variant="outline" size="sm" onClick={()=>zoomCanvas(1.25)} aria-label="Zoom out">Zoom out</Button>
      <Button type="button" variant="ghost" size="sm" onClick={fitCanvas}>Fit to nodes</Button>
      <Button type="button" variant="outline" size="sm" onClick={autoLayoutDraft} disabled={!canManage||!nodes.length}>Auto layout</Button>
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
    <div className={"topology-canvas-dropzone"+(paletteDropActive?" is-drop-active":"")} onDragOver={allowPaletteDrop}
     onDragLeave={event=>{if(event.currentTarget===event.target)setPaletteDropActive(false);}} onDrop={dropPaletteNode}>
     <div className="topology-canvas-drop-hint" aria-live="polite">{paletteDropActive?"Release to add a logical node":"Drop a palette node here · drag empty canvas to pan"}</div>
     <svg ref={canvasRef} viewBox={viewport.x+" "+viewport.y+" "+viewport.width+" "+viewport.height} role="application" aria-label="Vendor-aware native topology canvas; placement edits are stored separately from canonical network intent." style={{display:"block",width:"100%",minWidth:0,height:"auto",aspectRatio:"1000 / 620",touchAction:"none",cursor:panning?"grabbing":"grab"}}
      onPointerDown={startCanvasPan} onPointerMove={onCanvasPointerMove} onPointerUp={finishCanvasInteraction} onPointerCancel={finishCanvasInteraction} onWheel={zoomCanvasAtPointer}>
      <defs><pattern id="topology-grid" width={presentationModel.grid.size||25} height={presentationModel.grid.size||25} patternUnits="userSpaceOnUse"><path d={"M "+(presentationModel.grid.size||25)+" 0 L 0 0 0 "+(presentationModel.grid.size||25)} fill="none" stroke="currentColor" strokeOpacity=".08" strokeWidth="1"/></pattern></defs>
      <rect data-canvas-background="true" x={viewport.x} y={viewport.y} width={viewport.width} height={viewport.height} fill={presentationModel.canvas.background||"var(--background)"}/>
      {presentationModel.grid.enabled?<rect x={viewport.x} y={viewport.y} width={viewport.width} height={viewport.height} fill="url(#topology-grid)" pointerEvents="none"/>:null}
      {[...presentationModel.drawings].sort((a,b)=>(a.z_index||0)-(b.z_index||0)).filter(item=>presentationLayerVisible(item,presentationModel.layers)).map(item=>{
       const style=item.style||{},stroke=style.stroke||"var(--primary)",fill=style.fill||"none",strokeWidth=style.stroke_width||2,opacity=style.opacity??1;
       if(item.kind==="RECTANGLE")return <rect key={item.id} x={item.canvasX} y={item.canvasY} width={item.width||0} height={item.height||0} rx="2" stroke={stroke} fill={fill} strokeWidth={strokeWidth} opacity={opacity} pointerEvents="none"/>;
       if(item.kind==="ELLIPSE")return <ellipse key={item.id} cx={item.canvasX+(item.width||0)/2} cy={item.canvasY+(item.height||0)/2} rx={(item.width||0)/2} ry={(item.height||0)/2} stroke={stroke} fill={fill} strokeWidth={strokeWidth} opacity={opacity} pointerEvents="none"/>;
       if(item.kind==="LINE"||item.kind==="FREEHAND")return <polyline key={item.id} points={(item.canvasPoints||[]).map(point=>point.x+","+point.y).join(" ")} stroke={stroke} fill="none" strokeWidth={strokeWidth} opacity={opacity} strokeDasharray={style.dash||undefined} pointerEvents="none"/>;
       if(item.kind==="TEXT")return <text key={item.id} x={item.canvasX} y={item.canvasY} fill={stroke} fontSize={style.font_size||14} textAnchor={style.text_align==="center"?"middle":style.text_align==="end"?"end":"start"} opacity={opacity} pointerEvents="none">{item.text||""}</text>;
       return <g key={item.id} pointerEvents="none"><rect x={item.canvasX} y={item.canvasY} width={item.width||120} height={item.height||64} stroke={stroke} fill={fill} strokeDasharray="5 3"/><text x={item.canvasX+6} y={item.canvasY+18} fill="currentColor" fontSize="10">Asset reference · {item.asset_path||"image"}</text></g>;
      })}
      {presentationModel.links.filter(link=>presentationLayerVisible(link.layout,presentationModel.layers)).map(link=>{
       const source=renderNodeById[link.source_node_id],target=renderNodeById[link.target_node_id];
       if(!source||!target)return null;
       const layout=link.layout||{};
       return <g key={link.id} role="button" tabIndex="0" aria-label={"Select link "+link.id+" from "+source.name+" to "+target.name}
        aria-pressed={selectedLink===link.id} onPointerDown={event=>event.stopPropagation()}
        onClick={event=>{event.stopPropagation();selectCanvasLink(link);}}
        onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();selectCanvasLink(link);}}} style={{cursor:"pointer"}}>
        <path d={presentationLinkPath(source,target,link,presentationModel.coordinateSpace,presentationModel.canvas)} fill="none" stroke={selectedLink===link.id?"var(--warning)":"var(--primary)"} strokeWidth={selectedLink===link.id?5:3} strokeDasharray={layout.style?.dash||undefined}/>
        {layout.label?<text x={(source.canvasX+target.canvasX)/2} y={(source.canvasY+target.canvasY)/2-8} fill="currentColor" fontSize="12">{layout.label}</text>:null}
        <title>{link.source_interface_name||link.source_adapter+"/"+link.source_port} ↔ {link.target_interface_name||link.target_adapter+"/"+link.target_port}</title>
       </g>;
      })}
      {[...renderNodes].sort((a,b)=>(a.layout.z_index||0)-(b.layout.z_index||0)).filter(node=>presentationLayerVisible(node.layout,presentationModel.layers)).map(node=>{
       const matches=!nodeSearch.trim()||[node.name,node.id,node.node_type,node.template_id,node.displayLabel].some(value=>String(value||"").toLowerCase().includes(nodeSearch.trim().toLowerCase()));
       const locked=presentationLayerLocked(node.layout,presentationModel.layers);
       return <g key={node.id} transform={"translate("+node.canvasX+" "+node.canvasY+") rotate("+node.rotation+")"} role="button" tabIndex="0"
        aria-label={"Select node "+node.displayLabel} aria-pressed={selectedNodes.includes(node.id)}
        onPointerDown={event=>{setPanning(null);startNodeDrag(event,node.id);}}
        onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();setSelectedNodes(current=>current.includes(node.id)?current:[node.id]);setSelectedNode(node.id);setSelectedLink("");}}}
        style={{cursor:locked?"not-allowed":"grab",outline:"none"}} opacity={matches?1:0.22}>
        <rect x={-node.width/2} y={-node.height/2} width={node.width} height={node.height} rx="9" fill={selectedNodes.includes(node.id)?"var(--primary)":"var(--muted)"} stroke={nodeSearch.trim()&&matches?"var(--warning)":selectedNodes.includes(node.id)?"var(--primary)":"var(--border)"} strokeWidth={selectedNodes.includes(node.id)||nodeSearch.trim()&&matches?3:1.5}/>
        <text x="0" y="-5" textAnchor="middle" fill={selectedNode===node.id?"white":"currentColor"} fontSize="13" fontWeight="650">{String(node.displayLabel).slice(0,24)}</text>
        <text x="0" y="14" textAnchor="middle" fill={selectedNode===node.id?"white":"currentColor"} fontSize="9">{node.node_type} · {node.id.slice(0,12)}</text>
        {(node.interfaces||[]).map(interfaceItem=>{
         const attached=presentationModel.links.find(link=>(link.source_node_id===node.id&&link.source_interface_name===interfaceItem.name)||(link.target_node_id===node.id&&link.target_interface_name===interfaceItem.name));
         const other=attached?(attached.source_node_id===node.id?renderNodeById[attached.target_node_id]:renderNodeById[attached.source_node_id]):null;
         const point=presentationPortPoint(node,interfaceItem,other);
         return <g key={interfaceItem.name} role="button" tabIndex="0" aria-label={"Connect port "+node.name+" "+interfaceItem.name}
          onPointerDown={event=>event.stopPropagation()} onClick={event=>{event.stopPropagation();chooseTopologyPort(node,interfaceItem);}}
          onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();chooseTopologyPort(node,interfaceItem);}}} style={{cursor:canManage?"crosshair":"pointer"}}>
          <circle cx={point.x-node.canvasX} cy={point.y-node.canvasY} r="4.5" fill={portSelection?.node_id===node.id&&portSelection?.interface_name===interfaceItem.name?"var(--warning)":"var(--primary)"} stroke="var(--background)" strokeWidth="1.5"/>
          <title>{interfaceItem.name} · {interfaceItem.adapter}/{interfaceItem.port}</title>
         </g>;
        })}
        {node.layout.icon_ref||node.layout.icon_asset_path?<title>{node.layout.icon_ref||node.layout.icon_asset_path}</title>:null}
       </g>;
      })}
     </svg>
    </div>
    {!nodes.length?<EmptyState title="Canvas is empty" message="Drag a palette item here or select one above. This adds logical intent only."/>:null}
    {selectedNodes.length>1?<div className="form-grid"><div className="context-caption">{selectedNodes.length} nodes selected · {canManage?"drag any selected node to move the group together.":"view-only selection."}</div>{canManage?<div className="form-actions"><Button type="button" variant="destructive" onClick={deleteSelectedTopology}>Delete selected nodes and attached links</Button></div>:null}</div>:null}
   </Section>
   <Section title="Property inspector" subtitle="Edit logical network intent, interfaces and links. Provider IDs and operational state are actual read-only observations.">
    <div className="topology-inspector-layout">
     <div className="topology-inspector-pane">
      {selectedNodeRecord?<div className="topology-inspector-content">
       <div className="topology-inspector-heading"><strong>Node properties</strong><StatusBadge value={selectedNodeRecord.node_type}/></div>
       <div className="topology-inspector-grid">
        <Field label="Name"><input value={selectedNodeRecord.name} onChange={event=>updateNodeField(selectedNode,"name",event.target.value)} disabled={!canManage}/></Field>
        <Field label="Logical ID"><input value={selectedNodeRecord.id} readOnly/></Field>
        <Field label="Node type"><select value={selectedNodeRecord.node_type} onChange={event=>updateNodeField(selectedNode,"node_type",event.target.value)} disabled={!canManage}>{NODE_TYPES.map(type=><option key={type}>{type}</option>)}</select></Field>
        <Field label={isNativePresentation?"Presentation X":"Canvas X"}><input type="number" min={isNativePresentation?-100000:0} max="100000" value={isNativePresentation?(renderNodeById[selectedNode]?.canvasX??selectedNodeRecord.x):selectedNodeRecord.x} onChange={event=>{if(isNativePresentation){setPresentationDraft(current=>updatePresentationNodePosition(current||activePresentation,selectedNode,"x",Number(event.target.value)));setPresentationDirty(true);}else updateNodeField(selectedNode,"x",Number(event.target.value));}} disabled={!canManage}/></Field>
        <Field label={isNativePresentation?"Presentation Y":"Canvas Y"}><input type="number" min={isNativePresentation?-100000:0} max="100000" value={isNativePresentation?(renderNodeById[selectedNode]?.canvasY??selectedNodeRecord.y):selectedNodeRecord.y} onChange={event=>{if(isNativePresentation){setPresentationDraft(current=>updatePresentationNodePosition(current||activePresentation,selectedNode,"y",Number(event.target.value)));setPresentationDirty(true);}else updateNodeField(selectedNode,"y",Number(event.target.value));}} disabled={!canManage}/></Field>
        <Field label="Vendor"><input value={selectedNodeRecord.vendor||""} onChange={event=>updateNodeField(selectedNode,"vendor",event.target.value)} disabled={!canManage}/></Field>
        <Field label="Operating system"><input value={selectedNodeRecord.operating_system||""} onChange={event=>updateNodeField(selectedNode,"operating_system",event.target.value)} disabled={!canManage}/></Field>
        <Field label="Image / OS image"><input value={selectedNodeRecord.image||""} onChange={event=>updateNodeField(selectedNode,"image",event.target.value)} disabled={!canManage}/></Field>
        <Field label="Provider template ID">
         {providerCatalog?.templates?.length?<select value={selectedNodeRecord.template_id||""} onChange={event=>updateNodeField(selectedNode,"template_id",event.target.value)} disabled={!canManage}>
          <option value="">Unmapped logical node</option>{providerCatalog.templates.map(item=><option key={item.template_id} value={item.template_id}>{item.name||item.template_id} · {item.template_id}</option>)}
          {selectedNodeRecord.template_id&&!providerCatalog.templates.some(item=>item.template_id===selectedNodeRecord.template_id)?<option value={selectedNodeRecord.template_id}>{selectedNodeRecord.template_id} · not present in current catalogue</option>:null}
         </select>:<input value={selectedNodeRecord.template_id||""} onChange={event=>updateNodeField(selectedNode,"template_id",event.target.value)} disabled={!canManage} placeholder="Unmapped logical node"/>}
        </Field>
        <Field label="CPU cores"><input type="number" min="1" max="128" value={selectedNodeRecord.cpu_cores??""} onChange={event=>updateNodeField(selectedNode,"cpu_cores",event.target.value===""?undefined:Number(event.target.value))} disabled={!canManage}/></Field>
        <Field label="Memory (MB)"><input type="number" min="128" max="1048576" value={selectedNodeRecord.memory_mb??""} onChange={event=>updateNodeField(selectedNode,"memory_mb",event.target.value===""?undefined:Number(event.target.value))} disabled={!canManage}/></Field>
        <Field label="Management IP / prefix"><input value={selectedNodeRecord.management_address||""} onChange={event=>updateNodeField(selectedNode,"management_address",event.target.value)} disabled={!canManage} placeholder="192.0.2.10/24"/></Field>
        <Field label="Default gateway"><input value={selectedNodeRecord.default_gateway||""} onChange={event=>updateNodeField(selectedNode,"default_gateway",event.target.value)} disabled={!canManage} placeholder="192.0.2.1"/></Field>
        <Field label="VLAN ID"><input type="number" min="1" max="4094" value={selectedNodeRecord.vlan_id??""} onChange={event=>updateNodeField(selectedNode,"vlan_id",event.target.value===""?undefined:Number(event.target.value))} disabled={!canManage}/></Field>
        <Field label="Configuration profile"><select value={selectedNodeRecord.configuration_profile_id||""} onChange={event=>updateNodeField(selectedNode,"configuration_profile_id",event.target.value)} disabled={!canManage||!canPerform(user,"configurations.read")}>
         <option value="">No profile bound</option>{configurationProfiles.data?.items?.map(item=><option key={item.profile_id} value={item.profile_id}>{item.name} · {item.status}</option>)}
         {selectedNodeRecord.configuration_profile_id&&!configurationProfiles.data?.items?.some(item=>item.profile_id===selectedNodeRecord.configuration_profile_id)?<option value={selectedNodeRecord.configuration_profile_id}>{selectedNodeRecord.configuration_profile_id} · outside available list</option>:null}
        </select></Field>
        <Field label="Credential Vault reference"><select value={selectedNodeRecord.credential_ref_id||""} onChange={event=>updateNodeField(selectedNode,"credential_ref_id",event.target.value)} disabled={!canManage||!canPerform(user,"credentials.read")}>
         <option value="">No credential reference</option>{nodeCredentials.data?.items?.map(item=><option key={item.credential_id} value={item.credential_id}>{item.label} · {item.credential_id}</option>)}
         {selectedNodeRecord.credential_ref_id&&!nodeCredentials.data?.items?.some(item=>item.credential_id===selectedNodeRecord.credential_ref_id)?<option value={selectedNodeRecord.credential_ref_id}>{selectedNodeRecord.credential_ref_id} · outside available list</option>:null}
        </select></Field>
       </div>
       <div className="topology-observed-panel">
        <div className="topology-inspector-heading"><strong>Provider mapping and observed state</strong><StatusBadge value={selectedNodeMappingStatus}/></div>
        <div className="operations-detail-row"><span>Provider resource ID</span><code>{reconciliation?.logical_to_provider?.[selectedNode]||"Not mapped"}</code></div>
        <div className="operations-detail-row"><span>Provider node state</span><StatusBadge value={selectedNodeProviderState}/></div>
        <p className="muted">Observed state comes only from a provider catalogue or reconciliation response. Editing these fields never contacts the provider.</p>
       </div>
       <div className="topology-interface-editor">
        <div className="topology-inspector-heading"><strong>Network interfaces and ports</strong><span className="muted">{(selectedNodeRecord.interfaces||[]).length} planned</span></div>
        {(selectedNodeRecord.interfaces||[]).map(item=><div className="topology-interface-row" key={item.name}>
         <div className="topology-interface-heading"><strong>{item.name}</strong><small>Planned interface · {item.adapter}/{item.port}</small></div>
         {canManage?<div className="topology-interface-edit-grid">
          <Field label="Mode"><select aria-label={"Mode "+item.name} value={item.mode||"OTHER"} onChange={event=>updateNodeInterface(selectedNode,item.name,{mode:event.target.value})}><option>ACCESS</option><option>TRUNK</option><option>ROUTED</option><option>WIRELESS</option><option>OTHER</option></select></Field>
          <Field label="Adapter"><input aria-label={"Adapter "+item.name} type="number" min="0" max="255" value={item.adapter} onChange={event=>updateNodeInterface(selectedNode,item.name,{adapter:Number(event.target.value)})}/></Field>
          <Field label="Port"><input aria-label={"Port "+item.name} type="number" min="0" max="255" value={item.port} onChange={event=>updateNodeInterface(selectedNode,item.name,{port:Number(event.target.value)})}/></Field>
          <Field label="IP address"><input aria-label={"IP address "+item.name} value={item.ip_address||""} onChange={event=>updateNodeInterface(selectedNode,item.name,{ip_address:event.target.value})}/></Field>
          <Field label="VLAN"><input aria-label={"VLAN "+item.name} type="number" min="1" max="4094" value={item.vlan_id??""} onChange={event=>updateNodeInterface(selectedNode,item.name,{vlan_id:event.target.value===""?undefined:Number(event.target.value)})}/></Field>
         </div>:<small>{item.mode||"Mode unspecified"} · {item.ip_address||"No IP"}{item.vlan_id?" · VLAN "+item.vlan_id:""}</small>}
         <div className="topology-interface-actions"><Button type="button" size="sm" variant="outline" onClick={()=>chooseTopologyPort(selectedNodeRecord,item)} disabled={!canManage}>Connect port</Button><Button type="button" size="sm" variant="ghost" onClick={()=>removeNodeInterface(selectedNode,item.name)} disabled={!canManage}>Remove</Button></div>
        </div>)}
        {canManage?<form className="form-grid topology-interface-form" onSubmit={event=>{event.preventDefault();addNodeInterface(selectedNode);}}>
         <Field label="Interface name"><input value={interfaceForm.name} onChange={event=>setInterfaceForm({...interfaceForm,name:event.target.value})} required/></Field>
         <Field label="Adapter"><input type="number" min="0" max="255" value={interfaceForm.adapter} onChange={event=>setInterfaceForm({...interfaceForm,adapter:event.target.value})}/></Field>
         <Field label="Port"><input type="number" min="0" max="255" value={interfaceForm.port} onChange={event=>setInterfaceForm({...interfaceForm,port:event.target.value})}/></Field>
         <Field label="Mode"><select value={interfaceForm.mode} onChange={event=>setInterfaceForm({...interfaceForm,mode:event.target.value})}><option>ACCESS</option><option>TRUNK</option><option>ROUTED</option><option>WIRELESS</option><option>OTHER</option></select></Field>
         <Field label="IP address / prefix"><input value={interfaceForm.ip_address} onChange={event=>setInterfaceForm({...interfaceForm,ip_address:event.target.value})}/></Field>
         <Field label="VLAN"><input type="number" min="1" max="4094" value={interfaceForm.vlan_id} onChange={event=>setInterfaceForm({...interfaceForm,vlan_id:event.target.value})}/></Field>
         <div className="form-actions"><Button type="submit">Add interface</Button></div>
        </form>:null}
       </div>
       <div className="topology-inspector-footer"><Button type="button" variant="destructive" disabled={!canManage} onClick={()=>removeNode(selectedNode)}>Remove node and attached links</Button></div>
      </div>:selectedLinkRecord&&linkEditForm?<div className="topology-inspector-content">
       <div className="topology-inspector-heading"><strong>Link properties</strong><StatusBadge value={selectedLinkMappingStatus}/></div>
       <div className="context-caption">Selected link · {selectedLinkRecord.id}</div>
       <div className="topology-inspector-grid">
        <Field label="Source node"><select value={linkEditForm.source_node_id} onChange={event=>setLinkEditForm({...linkEditForm,source_node_id:event.target.value})} disabled={!canManage}>{nodes.map(node=><option key={node.id} value={node.id}>{node.name}</option>)}</select></Field>
        <Field label="Source interface"><select value={linkEditForm.source_interface_name||""} onChange={event=>{const node=nodes.find(item=>item.id===linkEditForm.source_node_id);const item=(node?.interfaces||[]).find(value=>value.name===event.target.value);setLinkEditForm({...linkEditForm,source_interface_name:event.target.value,source_adapter:item?.adapter??linkEditForm.source_adapter,source_port:item?.port??linkEditForm.source_port});}} disabled={!canManage}><option value="">Select interface</option>{(nodes.find(node=>node.id===linkEditForm.source_node_id)?.interfaces||[]).map(item=><option key={item.name}>{item.name}</option>)}</select></Field>
        <Field label="Destination node"><select value={linkEditForm.target_node_id} onChange={event=>setLinkEditForm({...linkEditForm,target_node_id:event.target.value})} disabled={!canManage}>{nodes.map(node=><option key={node.id} value={node.id}>{node.name}</option>)}</select></Field>
        <Field label="Destination interface"><select value={linkEditForm.target_interface_name||""} onChange={event=>{const node=nodes.find(item=>item.id===linkEditForm.target_node_id);const item=(node?.interfaces||[]).find(value=>value.name===event.target.value);setLinkEditForm({...linkEditForm,target_interface_name:event.target.value,target_adapter:item?.adapter??linkEditForm.target_adapter,target_port:item?.port??linkEditForm.target_port});}} disabled={!canManage}><option value="">Select interface</option>{(nodes.find(node=>node.id===linkEditForm.target_node_id)?.interfaces||[]).map(item=><option key={item.name}>{item.name}</option>)}</select></Field>
        <Field label="Edit source adapter"><input type="number" min="0" max="255" value={linkEditForm.source_adapter} onChange={event=>setLinkEditForm({...linkEditForm,source_adapter:event.target.value})} disabled={!canManage}/></Field>
        <Field label="Edit source port"><input type="number" min="0" max="255" value={linkEditForm.source_port} onChange={event=>setLinkEditForm({...linkEditForm,source_port:event.target.value})} disabled={!canManage}/></Field>
        <Field label="Edit target adapter"><input type="number" min="0" max="255" value={linkEditForm.target_adapter} onChange={event=>setLinkEditForm({...linkEditForm,target_adapter:event.target.value})} disabled={!canManage}/></Field>
        <Field label="Edit target port"><input type="number" min="0" max="255" value={linkEditForm.target_port} onChange={event=>setLinkEditForm({...linkEditForm,target_port:event.target.value})} disabled={!canManage}/></Field>
        <Field label="Link type"><select value={linkEditForm.link_type||"ETHERNET"} onChange={event=>setLinkEditForm({...linkEditForm,link_type:event.target.value})} disabled={!canManage}><option>ETHERNET</option><option>WIRELESS</option><option>SERIAL</option><option>TUNNEL</option><option>OTHER</option></select></Field>
        <Field label="Network segment"><input value={linkEditForm.network_segment_id||""} onChange={event=>setLinkEditForm({...linkEditForm,network_segment_id:event.target.value})} disabled={!canManage}/></Field>
        <Field label="VLAN association"><input type="number" min="1" max="4094" value={linkEditForm.vlan_id??""} onChange={event=>setLinkEditForm({...linkEditForm,vlan_id:event.target.value===""?"":Number(event.target.value)})} disabled={!canManage}/></Field>
       </div>
       <div className="topology-observed-panel"><div className="operations-detail-row"><span>Provider link ID</span><code>{selectedLinkProviderId}</code></div><div className="operations-detail-row"><span>Operational status</span><StatusBadge value={selectedLinkMappingStatus}/></div></div>
       <div className="form-actions"><Button type="button" onClick={saveSelectedLink} disabled={!canManage}>Save link endpoint changes</Button><Button type="button" variant="destructive" onClick={()=>removeLink(selectedLink)} disabled={!canManage}>Remove link</Button></div>
      </div>:<EmptyState title="Select a node or link" message="Choose an object on the canvas to inspect properties, interfaces, provider mapping and observed status."/>}
     </div>
     <aside className="topology-inspector-summary">
      <div className="operations-detail-row"><span>Logical nodes</span><strong>{nodes.length}</strong></div>
      <div className="operations-detail-row"><span>Logical links</span><strong>{links.length}</strong></div>
      <div className="operations-detail-row"><span>Unmapped templates</span><strong>{nodes.filter(node=>!node.template_id).length}</strong></div>
      <div className="operations-detail-row"><span>Unmapped provider nodes</span><strong>{nodes.filter(node=>!reconciliation?.logical_to_provider?.[node.id]).length}</strong></div>
      <div className="operations-detail-row"><span>Revision</span><strong>{selectedRevision?"r"+selectedRevision.revision_number:"Local draft"}</strong></div>
      <p className="muted">Logical intent is authoritative. Provider IDs and runtime status are observed, not editable desired-state fields.</p>
     </aside>
    </div>
   </Section>
   </div>

   <Section title="Operational console" subtitle="Validation, provider operations, session logs, apply history, reconciliation and warnings for the current topology workspace.">
    <div className="topology-console-tabs" role="tablist" aria-label="Topology operational console">
     {["validation","provider","logs","apply-history","reconciliation","warnings"].map(tab=><button key={tab} type="button" role="tab" aria-selected={consoleTab===tab} onClick={()=>setConsoleTab(tab)}>{({validation:"Validation",provider:"Provider operations",logs:"Logs","apply-history":"Apply history",reconciliation:"Reconciliation",warnings:"Warnings"})[tab]}</button>)}
    </div>
    {consoleTab==="validation"?<div className="topology-console-panel" role="tabpanel">
     <div className="operations-detail-row"><span>Current draft</span><strong>{nodes.length} nodes · {links.length} links</strong></div>
     {validation?<div className="provider-plan"><p><StatusBadge value={validation.valid?"VALID":"INVALID"}/> {validation.valid?validation.node_count+" nodes · "+validation.link_count+" links · SHA-256 "+validation.content_sha256:validation.error}</p></div>:<p className="muted">No validation result exists for the current draft.</p>}
     {canManage||canPublish?<div className="button-row">
      {canManage?<><Button type="button" variant="outline" onClick={validateDraft} loading={validationLoading} disabled={!profileId||revisions.loading||mutation.loading}>Validate current draft</Button>
      <Button type="button" onClick={saveRevision} loading={mutation.loading} disabled={!profileId||revisions.loading||validationLoading}>Validate and save new draft revision</Button></>:null}
      {canPublish?<Button type="button" variant="outline" onClick={publishRevision} disabled={!revisionId||selectedRevision?.status!=="DRAFT"||mutation.loading}>Publish selected revision</Button>:null}
     </div>:null}
     <p className="muted">Validation is read-only. Saving creates a new immutable revision; publishing never overwrites an existing revision.</p>
    </div>:null}
    {consoleTab==="provider"?<div className="topology-console-panel" role="tabpanel">
     <div className="operations-detail-row"><span>Saved binding</span><StatusBadge value={!activeLabId?"NOT APPLICABLE":providerBinding.loading&&!providerBinding.data?"UNKNOWN":providerBinding.error?"UNKNOWN":binding?"CONFIGURED":"NOT CONFIGURED"}/></div>
     <div className="operations-detail-row"><span>Provider health</span><StatusBadge value="UNKNOWN"/></div>
     <p className="muted">A saved binding is not proof of provider availability. Catalogue, dry-run, apply and reconciliation retrieve actual provider observations.</p>
     {activeLabId?<Section title="Topology provider and apply" subtitle="Bind a supported private controller to this Lab, inspect its catalogue, plan changes and apply only after explicit confirmation.">
    <div className="module-intro">
     <div className="module-intro-icon">⇄</div>
     <div><strong>Explicit provider boundary</strong><p>Editing and publishing remain local-only. The provider is contacted only when you verify a binding, inspect the catalogue, request a dry-run, reconcile, apply, or explicitly start/stop a mapped node. Unmanaged resources are never pruned.</p></div>
    </div>
    {providerBinding.error?<InlineNotice tone="danger">{providerBinding.error.message}</InlineNotice>:null}
    {providerBinding.loading&&!providerBinding.data?<div className="context-caption">Loading saved provider binding metadata…</div>:binding?<div className="context-caption">Active binding · {binding.provider_id||"gns3"} · {binding.endpoint_url} · workspace {binding.provider_workspace_id||binding.gns3_project_id} · controller {binding.controller_device_id}</div>:providerBinding.error?<div className="context-caption">Saved provider binding is unavailable; its state is not inferred.</div>:<div className="context-caption">No active topology provider is bound to this Lab.</div>}
    {canManageProvider?<form className="form-grid" onSubmit={saveProviderBinding}>
     <Field label="Provider" required><select aria-label="Provider" value={bindingForm.provider_id||"gns3"} onChange={event=>setBindingForm({...bindingForm,provider_id:event.target.value,provider_workspace_id:"",gns3_project_id:""})}>
      <option value="gns3">GNS3</option><option value="cml">Cisco Modeling Labs</option><option value="eve-ng">EVE-NG</option>
     </select></Field>
     <Field label="Private controller URL" required><input value={bindingForm.endpoint_url} onChange={event=>setBindingForm({...bindingForm,endpoint_url:event.target.value})} placeholder="https://192.168.1.10:8443" required/></Field>
     <Field label="Provider workspace" required>
      {providerCatalog?.projects?.length?<select aria-label="Provider workspace ID" value={bindingForm.provider_workspace_id||""} onChange={event=>setBindingForm({...bindingForm,provider_workspace_id:event.target.value,gns3_project_id:event.target.value})} required>
       <option value="">Select observed provider workspace</option>
       {providerCatalog.projects.map(item=><option key={item.project_id} value={item.project_id}>{item.name||item.project_id} · {item.status||"UNKNOWN"} · {item.project_id}</option>)}
      </select>:<input aria-label="Provider workspace ID" value={bindingForm.provider_workspace_id||""} onChange={event=>setBindingForm({...bindingForm,provider_workspace_id:event.target.value,gns3_project_id:event.target.value})} maxLength={512} required/>}
      <span className="field-hint">{bindingForm.provider_id==="eve-ng"?"EVE-NG workspaces must be absolute .unl paths, for example /User1/Lab.unl.":"Enter the initial workspace identifier, then inspect the controller catalogue to select an observed workspace when changing the binding."}</span>
     </Field>
     <Field label="Registered controller device" required>
      <select aria-label="Registered controller device" value={bindingForm.controller_device_id} onChange={event=>setBindingForm({...bindingForm,controller_device_id:event.target.value,credential_id:""})} required>
       <option value="">Select device</option>
       {deviceRows.map(item=><option key={item.device_id} value={item.device_id}>{item.name} · {item.host}</option>)}
      </select>
     </Field>
     <Field label="OS-vault API credential" required>
      <select aria-label="OS-vault API credential" value={bindingForm.credential_id} onChange={event=>setBindingForm({...bindingForm,credential_id:event.target.value})} required>
       <option value="">Select active API credential</option>
       {credentialRows.map(item=><option key={item.credential_id} value={item.credential_id}>{item.label} · {item.credential_id}</option>)}
      </select>
     </Field>
     <div className="form-actions"><Button type="submit" loading={providerBusy} disabled={!activeLabId||!bindingForm.provider_id||!bindingForm.endpoint_url.trim()||!(bindingForm.provider_workspace_id||"").trim()||!bindingForm.controller_device_id||!bindingForm.credential_id}>Verify and bind provider</Button></div>
    </form>:null}
    {!deviceRows.length&&activeLabId?<InlineNotice tone="info">Register the provider controller as an active device in this Lab, then attach an API credential through the Credentials workspace.</InlineNotice>:null}
    {providerCredentials.error?<InlineNotice tone="danger">{providerCredentials.error.message}</InlineNotice>:null}
    {providerError?<InlineNotice tone="danger">{providerError}</InlineNotice>:null}
    {binding?<div className="button-row">
     <Button variant="outline" onClick={loadProviderCatalog} loading={providerBusy}>Inspect provider catalogue</Button>
     {canManageProvider?<Button variant="ghost" onClick={()=>runProvider(()=>api.archiveTopologyProvider(activeLabId).then(async result=>{await providerBinding.reload();return result;}),"Provider binding archived. No provider resources were deleted.")} loading={providerBusy}>Archive binding</Button>:null}
    </div>:null}
    {providerCatalog?<div className="form-grid">
     <div className="context-caption">{providerCatalog.provider?.name||binding?.provider_id||"Provider"} version · {providerCatalog.version?.version||"version unavailable"} · projects {providerCatalog.projects?.length||0} · templates {providerCatalog.templates?.length||0}</div>
     <div className="context-caption">Observed nodes {providerCatalog.nodes?.length||0} · links {providerCatalog.links?.length||0}</div>
     <div className="context-caption">Compute connectivity · {(providerCatalog.resources?.computes||[]).filter(item=>item.connected===true).length} connected / {(providerCatalog.resources?.computes||[]).length} reported · {(providerCatalog.resources?.computes||[]).filter(item=>item.connected===null||item.connected===undefined).length} unknown</div>
     <div className="context-caption">Node lifecycle · {Object.entries(providerCatalog.node_lifecycle||{}).map(([status,count])=>status+" "+count).join(" · ")||"No observed nodes"}</div>
     <div className="context-caption">Packet capture capability · {providerCatalog.capture_support?.supported?"reported at provider level":"not reported"}; link and compute readiness is checked separately.</div>
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
     <div className="provider-plan">
      <h5>Template and image compatibility</h5>
      {(providerPlan.plan.template_compatibility||[]).map(item=><div className="operations-detail-row" key={item.logical_node_id}>
       <span>{item.logical_node_id} · {item.template_name||item.template_id||"Unmapped template"} · compute {item.compute_id||"unknown"}</span>
       <strong><StatusBadge value={item.template_status==="AVAILABLE"?item.image_status:item.template_status}/> {item.compute_connected===true?"Compute connected":item.compute_connected===false?"Compute disconnected":"Compute connectivity unknown"}</strong>
       {item.missing_images?.length?<span>Missing images: {item.missing_images.join(", ")}</span>:null}
      </div>)}
      <p className="context-caption">An UNKNOWN image or compute observation is shown as unknown; only an observed missing image or disconnected assigned compute blocks the plan.</p>
     </div>
     <div className="context-caption">Provider compute resources · {(providerPlan.plan.resource_availability?.computes||[]).length} records · source observation is read-only.</div>
     {providerPlan.plan.conflicts.length?<ul>{providerPlan.plan.conflicts.map((item,index)=><li key={index}>{item.resource_id||"Provider"}: {item.reason}</li>)}</ul>:<p>No current template or port conflicts were found in the observed provider state.</p>}
     {canApplyTopology&&providerPlan.plan.can_apply?<label className="confirm-operation">
      <input type="checkbox" checked={confirmApply} onChange={event=>setConfirmApply(event.target.checked)}/>
      I reviewed this revision hash and authorize these explicit provider node/link changes for this Lab.
     </label>:null}
     {canApplyTopology?<div className="button-row"><Button onClick={applyPublishedTopology} loading={providerBusy} disabled={!providerPlan.plan.can_apply||!confirmApply}>Confirm and apply topology</Button></div>:null}
    </div>:null}
    {reconciliation?<div className="provider-plan">
     <h4>Observed-versus-desired reconciliation</h4>
     <p><StatusBadge value={reconciliation.status}/> {reconciliation.observed_managed_node_count} of {reconciliation.desired_node_count} managed nodes observed · {reconciliation.missing_nodes.length} missing nodes · {reconciliation.missing_links.length} missing links</p>
     {reconciliation.missing_nodes.length?<p>Missing nodes: {reconciliation.missing_nodes.join(", ")}</p>:null}
     {reconciliation.missing_links.length?<p>Missing links: {reconciliation.missing_links.join(", ")}</p>:null}
     {selectedProviderNodeId?<Button type="button" variant="outline" onClick={inspectSelectedProviderInterfaces} loading={providerBusy}>Inspect selected node provider interfaces</Button>:null}
     {providerInterfaces?.provider_node_id===selectedProviderNodeId&&selectedProviderNodeId?<div className="provider-plan">
      <h5>Observed interfaces · {providerInterfaces.provider_node_id}</h5>
      {providerInterfaces.interfaces?.length?<ul>{providerInterfaces.interfaces.map((item,index)=><li key={item.adapter_number+"-"+item.port_number+"-"+index}>Adapter {item.adapter_number} · Port {item.port_number} · {item.name||item.short_name||"Unnamed"} · {item.link_type||"type unknown"}</li>)}</ul>:<p className="muted">The provider returned no interfaces for this node.</p>}
     </div>:null}
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
    </Section>:null}
    </div>:null}
    {consoleTab==="logs"?<div className="topology-console-panel" role="tabpanel">
     <p className="muted">Session activity for this editor only; it is not a persistent audit history.</p>
     {sessionLogs.length?sessionLogs.map(entry=><div className="topology-console-log" key={entry.id}><time>{new Date(entry.at).toLocaleTimeString()}</time><StatusBadge value={entry.level}/><span>{entry.message}</span></div>):<EmptyState title="No session activity" message="Editor actions will be recorded here for this browser session."/>}
    </div>:null}
    {consoleTab==="apply-history"?<div className="topology-console-panel" role="tabpanel">
     {activeLabId?<DataTable caption="Topology apply and recovery history" rows={applyHistory.data?.items||[]} rowKey={item=>item.apply_id} columns={[
      {key:"apply_id",label:"Apply record",render:item=><code>{item.apply_id}</code>},
      {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
      {key:"revision_id",label:"Revision"},{key:"created_at",label:"Started",render:item=>new Date(item.created_at).toLocaleString()},
      {key:"completed_at",label:"Completed",render:item=>item.completed_at?new Date(item.completed_at).toLocaleString():"—"}
     ]} emptyTitle="No topology applies" emptyMessage="Dry-run plans do not create history. Confirmed provider operations are retained here, including partial results."/>:<p className="muted">Apply history requires a Lab-scoped topology profile.</p>}
    </div>:null}
    {consoleTab==="reconciliation"?<div className="topology-console-panel" role="tabpanel">
     {reconciliation?<><div className="operations-detail-row"><span>Observed reconciliation</span><StatusBadge value={reconciliation.status}/></div>
      <div className="operations-detail-row"><span>Managed nodes observed</span><strong>{reconciliation.observed_managed_node_count} / {reconciliation.desired_node_count}</strong></div>
      <div className="operations-detail-row"><span>Unmanaged provider nodes</span><strong>{reconciliation.unmanaged_provider_node_count}</strong></div>
      <div className="operations-detail-row"><span>Missing nodes</span><strong>{reconciliation.missing_nodes.join(", ")||"None"}</strong></div>
      <div className="operations-detail-row"><span>Missing links</span><strong>{reconciliation.missing_links.join(", ")||"None"}</strong></div>
      <div className="operations-detail-row"><span>Mismatched nodes / links</span><strong>{(reconciliation.mismatched_nodes||[]).length} / {(reconciliation.mismatched_links||[]).length}</strong></div>
      <p className="muted">These mappings and counts come from the actual provider read-back and stored mappings.</p>
     </>:<p className="muted">No reconciliation result has been retrieved for this immutable revision.</p>}
     {activeLabId?<Button type="button" variant="outline" onClick={refreshReconciliation} loading={providerBusy} disabled={!revisionId||!binding}>Refresh reconciliation</Button>:null}
    </div>:null}
    {consoleTab==="warnings"?<div className="topology-console-panel" role="tabpanel">
     {nodes.filter(node=>!node.template_id).map(node=><div className="topology-warning-row" key={"template-"+node.id}><StatusBadge value="UNMAPPED"/> {node.name} has no provider template mapping.</div>)}
     {links.filter(link=>(link.source_interface_name&&!nodes.find(node=>node.id===link.source_node_id)?.interfaces?.some(item=>item.name===link.source_interface_name))
      ||(link.target_interface_name&&!nodes.find(node=>node.id===link.target_node_id)?.interfaces?.some(item=>item.name===link.target_interface_name))).map(link=><div className="topology-warning-row" key={"interface-"+link.id}><StatusBadge value="INVALID"/> {link.id} references a missing interface.</div>)}
     {validation&&!validation.valid?<div className="topology-warning-row"><StatusBadge value="INVALID"/> {validation.error}</div>:null}
     {!nodes.some(node=>!node.template_id)&&!links.some(link=>(link.source_interface_name&&!nodes.find(node=>node.id===link.source_node_id)?.interfaces?.some(item=>item.name===link.source_interface_name))
      ||(link.target_interface_name&&!nodes.find(node=>node.id===link.target_node_id)?.interfaces?.some(item=>item.name===link.target_interface_name)))&&!(validation&&!validation.valid)?<p className="muted">No local topology warnings. Provider/controller health remains unknown until observed.</p>:null}
    </div>:null}
   </Section>
  </>:<EmptyState title="Select or create a topology profile" message="Choose a Project and a profile to open the local topology canvas."/>}
 </div>;
}
