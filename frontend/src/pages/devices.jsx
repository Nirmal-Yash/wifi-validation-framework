import React,{useEffect,useState} from "react";
import {api} from "@/api";
import {useAsyncLoader,useMutation} from "@/hooks";
import {canPerform} from "@/permissions";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

const DEVICE_TYPES=["ROUTER","ACCESS_POINT","CLIENT","MONITOR","SWITCH","SERVER","OTHER"];
const CAPABILITIES={
 supports_wpa2:true,supports_wpa3:false,supports_2ghz:true,supports_5ghz:true,
 supports_6ghz:false,supports_reboot:true,supports_firmware_flash:false,
 supports_rollback:false,supports_rssi:true,supports_packet_capture:true,
 supports_ssh:true,supports_tftp:false
};
const emptyForm=()=>({
 name:"",device_key:"",device_type:"ROUTER",host:"",port:22,vendor:"",model:"",
 username:"",lab_id:"",capabilities:JSON.stringify(CAPABILITIES,null,2),metadata:"{}"
});

export default function DevicesPage({user}){
 const projects=useAsyncLoader(()=>api.workspaceProjects(),[],{queryKey:"device-inventory-projects"});
 const [projectId,setProjectId]=useState("");
 const [labId,setLabId]=useState("");
 const [form,setForm]=useState(emptyForm);
 const [showCreate,setShowCreate]=useState(false);
 const [selectedDeviceId,setSelectedDeviceId]=useState("");
 const [credentialReference,setCredentialReference]=useState("");
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const canManage=canPerform(user,"devices.manage");
 const labs=useAsyncLoader(()=>projectId?api.workspaceLabs(projectId):Promise.resolve({items:[]}),
  [projectId],{enabled:Boolean(projectId),queryKey:"device-inventory-labs"});
 const devices=useAsyncLoader(()=>projectId?api.devices(projectId,labId||undefined,"ACTIVE"):Promise.resolve({items:[]}),
  [projectId,labId],{enabled:Boolean(projectId),queryKey:"device-inventory-list"});
 const mutation=useMutation();
 const projectItems=projects.data?.items||[];
 const labItems=(labs.data?.items||[]).filter(item=>item.status==="ACTIVE");

 useEffect(()=>{if(!projectId&&projectItems.length)setProjectId(projectItems[0].project_id);},[projects.data,projectId]);
 useEffect(()=>{if(labId&&!labItems.some(item=>item.lab_id===labId))setLabId("");},[labs.data,labId]);
 async function createDevice(event){
  event.preventDefault();setError("");setNotice("");
  let capabilities,metadata;
  try{capabilities=JSON.parse(form.capabilities);metadata=JSON.parse(form.metadata);}
  catch{setError("Capabilities and metadata must be valid JSON objects.");return;}
  if(!capabilities||Array.isArray(capabilities)||typeof capabilities!=="object"||
     !metadata||Array.isArray(metadata)||typeof metadata!=="object"){
   setError("Capabilities and metadata must each be JSON objects.");return;
  }
  try{
   await mutation.run(()=>api.createDevice({
    project_id:projectId,lab_id:form.lab_id,device_key:form.device_key,
    name:form.name,device_type:form.device_type,host:form.host,
    port:Number(form.port),vendor:form.vendor,model:form.model,username:form.username,
    capabilities,metadata
   }));
   setNotice("Device inventory record created. No connection or network operation was started.");
   setForm(emptyForm());setShowCreate(false);await devices.reload();
  }catch(exc){setError(exc.message||"Device could not be created.");}
 }
 async function linkCredential(event){
  event.preventDefault();setError("");setNotice("");
  if(!selectedDeviceId||!credentialReference.trim()){setError("Choose a device and enter the credential ID.");return;}
  try{
   await mutation.run(()=>api.updateDevice(selectedDeviceId,{credential_id:credentialReference.trim()}));
   setNotice("Opaque vault credential reference linked. No secret value was read or returned.");
   setCredentialReference("");await devices.reload();
  }catch(exc){setError(exc.message||"Credential reference could not be linked.");}
 }
 async function archiveDevice(item){
  setError("");setNotice("");
  try{
   await mutation.run(()=>api.updateDevice(item.device_id,{status:"ARCHIVED"}));
   setNotice(item.name+" archived. The record and audit trail remain stored.");
   await devices.reload();
  }catch(exc){setError(exc.message||"Device could not be archived.");}
 }

 if(projects.loading&&!projects.data)return <LoadingState label="Loading Project inventory…"/>;
 if(projects.error&&!projects.data)return <ErrorState error={projects.error} onRetry={projects.reload}/>;
 return <div className="page-stack">
  <div className="module-intro"><div className="module-intro-icon"><RouterIcon/></div><div><strong>Managed device inventory</strong><p>Devices are owned by a Project and Lab. Secrets remain in the OS credential vault; the database stores only an opaque credential reference.</p></div></div>
  <Section title="Inventory scope" subtitle="Select the Project and optionally narrow the list to one Lab." actions={canManage?<Button size="sm" onClick={()=>{setForm({...emptyForm(),lab_id:labId});setShowCreate(value=>!value);}}>{showCreate?"Close":"Register device"}</Button>:null}>
   <div className="form-grid">
    <Field label="Project"><select value={projectId} onChange={event=>{setProjectId(event.target.value);setLabId("");setShowCreate(false);}}><option value="">Select Project</option>{projectItems.map(item=><option key={item.project_id} value={item.project_id}>{item.name} · {item.slug}</option>)}</select></Field>
    <Field label="Lab filter"><select value={labId} onChange={event=>setLabId(event.target.value)} disabled={!projectId||labs.loading}><option value="">All Labs</option>{labItems.map(item=><option key={item.lab_id} value={item.lab_id}>{item.name}</option>)}</select></Field>
   </div>
   {projects.error?<InlineNotice tone="danger">{projects.error.message}</InlineNotice>:null}
   {labs.error?<InlineNotice tone="danger">{labs.error.message}</InlineNotice>:null}
  </Section>
  {notice?<InlineNotice tone="success">{notice}</InlineNotice>:null}
  {error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  {showCreate&&canManage?<Section title="Register device" subtitle="This creates an inventory record only. It does not connect to the device or change its configuration.">
   <form className="form-grid" onSubmit={createDevice}>
    <Field label="Lab" required><select value={form.lab_id} onChange={event=>setForm({...form,lab_id:event.target.value})} required><option value="">Select active Lab</option>{labItems.map(item=><option key={item.lab_id} value={item.lab_id}>{item.name} · {item.lab_id.slice(0,8)}</option>)}</select></Field>
    <Field label="Device key" required hint="Stable, unique key within this Lab."><input value={form.device_key} onChange={event=>setForm({...form,device_key:event.target.value})} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" required/></Field>
    <Field label="Display name" required><input value={form.name} onChange={event=>setForm({...form,name:event.target.value})} maxLength={120} required/></Field>
    <Field label="Device type" required><select value={form.device_type} onChange={event=>setForm({...form,device_type:event.target.value})}>{DEVICE_TYPES.map(item=><option key={item}>{item}</option>)}</select></Field>
    <Field label="Host / IP address" required><input value={form.host} onChange={event=>setForm({...form,host:event.target.value})} maxLength={253} placeholder="192.168.10.1" required/></Field>
    <Field label="SSH port"><input type="number" min="1" max="65535" value={form.port} onChange={event=>setForm({...form,port:event.target.value})}/></Field>
    <Field label="Vendor"><input value={form.vendor} onChange={event=>setForm({...form,vendor:event.target.value})} maxLength={80}/></Field>
    <Field label="Model"><input value={form.model} onChange={event=>setForm({...form,model:event.target.value})} maxLength={120}/></Field>
    <Field label="SSH username"><input value={form.username} onChange={event=>setForm({...form,username:event.target.value})} maxLength={128}/></Field>
    <Field label="Capabilities JSON" className="full-width" hint="Only declared DeviceCapabilities keys and boolean values are accepted."><textarea rows={6} value={form.capabilities} onChange={event=>setForm({...form,capabilities:event.target.value})} spellCheck="false"/></Field>
    <Field label="Metadata JSON" className="full-width" hint="Never include passwords, tokens, PSKs, private keys or credential material."><textarea rows={4} value={form.metadata} onChange={event=>setForm({...form,metadata:event.target.value})} spellCheck="false"/></Field>
    <div className="form-actions"><Button type="submit" loading={mutation.loading} disabled={!projectId||!labItems.length}>Save inventory record</Button></div>
   </form>
   {!labItems.length?<InlineNotice tone="warning">Create an active Lab before registering devices.</InlineNotice>:null}
  </Section>:null}
  <Section title="Devices" subtitle={devices.data?.items?.length+" active record(s) in the selected scope"}>
   {devices.loading?<LoadingState label="Loading devices…"/>:devices.error?<ErrorState error={devices.error} onRetry={devices.reload}/>:null}
   <DataTable caption="Managed device inventory" rows={devices.data?.items||[]} rowKey={item=>item.device_id} columns={[
    {key:"name",label:"Device",render:item=><div className="run-table-identity"><strong>{item.name}</strong><span className="muted mono">{item.device_key}</span></div>},
    {key:"device_type",label:"Type",render:item=><StatusBadge value={item.device_type}/>},
    {key:"host",label:"Endpoint",render:item=><span className="mono">{item.host}:{item.port}</span>},
    {key:"lab_id",label:"Lab",render:item=><span className="mono">{item.lab_id.slice(0,12)}</span>},
    {key:"vendor",label:"Vendor / model",render:item=>(item.vendor||"—")+(item.model?" · "+item.model:"")},
    {key:"device_id",label:"Device ID",render:item=><code title={item.device_id}>{item.device_id}</code>},
    {key:"credential_id",label:"Vault reference",render:item=>item.credential_id?<code title={item.credential_id}>{item.credential_id}</code>:"Not linked"},
    {key:"actions",label:"Actions",render:item=>canManage?<Button size="sm" variant="ghost" disabled={mutation.loading} onClick={()=>archiveDevice(item)}>Archive</Button>:"—"}
   ]} emptyTitle="No devices in this scope" emptyMessage="Register the first device or choose another Lab."/>
  </Section>
  {canManage?<Section title="Link an OS-vault credential" subtitle="Create a device-bound credential in Credentials first, using the exact Device ID above. Then link its opaque credential ID here.">
   <form className="form-grid" onSubmit={linkCredential}>
    <Field label="Device"><select value={selectedDeviceId} onChange={event=>setSelectedDeviceId(event.target.value)} required><option value="">Select device</option>{(devices.data?.items||[]).map(item=><option key={item.device_id} value={item.device_id}>{item.name} · {item.device_id.slice(0,12)}</option>)}</select></Field>
    <Field label="Credential ID" required><input value={credentialReference} onChange={event=>setCredentialReference(event.target.value)} maxLength={128} placeholder="Opaque OS-vault credential ID" required/></Field>
    <div className="form-actions"><Button type="submit" variant="outline" disabled={mutation.loading||!devices.data?.items?.length}>Link credential reference</Button></div>
   </form>
  </Section>:null}
 </div>;
}

function RouterIcon(){return <span aria-hidden="true">◎</span>;}
