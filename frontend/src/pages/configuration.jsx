import React,{useEffect,useMemo,useState} from "react";
import {KeyRound,LockKeyhole,RefreshCw,Settings2,ShieldCheck,UploadCloud} from "lucide-react";
import {api} from "@/api";
import {useAsyncLoader,useMutation} from "@/hooks";
import {canPerform} from "@/permissions";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

function useProjectSelection(){
 const projects=useAsyncLoader(()=>api.workspaceProjects({}),[],{queryKey:"configuration-projects"});
 const [projectId,setProjectId]=useState("");
 useEffect(()=>{
  const rows=projects.data?.items||[];
  if(!projectId&&rows.length)setProjectId(rows[0].project_id);
 },[projects.data,projectId]);
 return {projects,projectId,setProjectId};
}
function ProjectPicker({projects,projectId,onChange}){
 const rows=projects.data?.items||[];
 return <Field label="Project">
  <select value={projectId} onChange={event=>onChange(event.target.value)}>
   <option value="">Select a Project</option>
   {rows.map(project=><option key={project.project_id} value={project.project_id}>{project.name}</option>)}
  </select>
 </Field>;
}
function PageNotice({notice}){return notice?<InlineNotice tone="success">{notice}</InlineNotice>:null;}

export function CredentialsPage({user}){
 const {projects,projectId,setProjectId}=useProjectSelection();
 const records=useAsyncLoader(()=>api.credentials(projectId),[projectId],{enabled:Boolean(projectId),queryKey:"managed-credentials"});
 const mutation=useMutation();
 const canManage=canPerform(user,"credentials.manage");
 const canVerify=canPerform(user,"credentials.verify");
 const [form,setForm]=useState({device_id:"",label:"Primary SSH",credential_type:"SSH_PASSWORD",username:"",secret:""});
 const [rotation,setRotation]=useState({});
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const update=(key,value)=>setForm(current=>({...current,[key]:value}));
 async function perform(action,success){
  setError("");setNotice("");
  try{await mutation.run(action);setNotice(success);await records.reload();}
  catch(exc){setError(exc.message||"Credential operation failed.");}
 }
 async function create(event){
  event.preventDefault();
  await perform(()=>api.createCredential({...form,project_id:projectId}),"Credential saved in the operating-system vault.");
  setForm(current=>({...current,secret:""}));
 }
 async function rotate(item){
  const secret=rotation[item.credential_id]||"";
  if(!secret){setError("Enter the replacement secret before rotating.");return;}
  await perform(()=>api.rotateCredential(item.credential_id,{secret}),"Credential rotated. Verification has been reset.");
  setRotation(current=>({...current,[item.credential_id]:""}));
 }
 const columns=[
  {key:"label",label:"Credential",render:item=><div><strong>{item.label}</strong><div className="table-secondary">{item.device_id} · {item.username||"No username"}</div></div>},
  {key:"credential_type",label:"Type"},
  {key:"status",label:"Lifecycle",render:item=><StatusBadge value={item.status}/>},
  {key:"verification_status",label:"Verification",render:item=><div><StatusBadge value={item.verification_status}/><div className="table-secondary">{item.last_verified_at?new Date(item.last_verified_at).toLocaleString():"Not checked"}</div></div>},
  {key:"actions",label:"Actions",render:item=><div className="credential-actions">
   {canVerify?<Button size="sm" variant="outline" disabled={mutation.loading||item.status!=="ACTIVE"} onClick={()=>perform(()=>api.verifyCredential(item.credential_id),"Verification status updated.")}>Verify</Button>:null}
   {canManage&&item.status==="ACTIVE"?<>
    <div className="credential-rotate"><input aria-label={"Replacement secret for "+item.label} type="password" autoComplete="new-password" value={rotation[item.credential_id]||""} onChange={event=>setRotation(current=>({...current,[item.credential_id]:event.target.value}))} placeholder="New secret"/><Button size="sm" variant="outline" disabled={mutation.loading} onClick={()=>rotate(item)}>Rotate</Button></div>
    <Button size="sm" variant="destructive" disabled={mutation.loading} onClick={()=>perform(()=>api.revokeCredential(item.credential_id),"Credential revoked.")}>Revoke</Button>
   </>:null}
  </div>},
 ];
 return <div className="page-stack">
  <div className="module-intro"><div className="module-intro-icon"><LockKeyhole size={19}/></div><div><strong>Secrets stay outside SQLite</strong><p>The database stores credential metadata and an opaque provider reference only. Secret values are never shown again after save.</p></div></div>
  <Section title="Credential scope" subtitle="Choose the Project whose device credentials you are administering.">
   <div className="config-toolbar"><ProjectPicker projects={projects} projectId={projectId} onChange={setProjectId}/><span className="context-caption">Project membership is enforced by the API.</span></div>
  </Section>
  <PageNotice notice={notice}/>{error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  {canManage?<Section title="Attach a credential" subtitle="Create a named credential for a configured device. The secret is transmitted once and stored by the host operating system.">
   <form className="form-grid credential-form" onSubmit={create}>
    <Field label="Device ID" required><input value={form.device_id} onChange={event=>update("device_id",event.target.value)} placeholder="e.g. ap-01" required/></Field>
    <Field label="Credential label" required><input value={form.label} onChange={event=>update("label",event.target.value)} maxLength={120} required/></Field>
    <Field label="Credential type" required><select value={form.credential_type} onChange={event=>update("credential_type",event.target.value)}><option value="SSH_PASSWORD">SSH password</option><option value="SSH_PRIVATE_KEY">SSH private key</option><option value="WIFI_PSK">Wi-Fi PSK</option><option value="API_TOKEN">API token</option></select></Field>
    <Field label="Username"><input value={form.username} onChange={event=>update("username",event.target.value)} autoComplete="off" placeholder="Device login"/></Field>
    <Field label="Secret" required hint="Not stored in the application database. Never logged or returned by the API."><input type="password" autoComplete="new-password" value={form.secret} onChange={event=>update("secret",event.target.value)} required/></Field>
    <div className="form-actions"><Button type="submit" disabled={mutation.loading||!projectId}><KeyRound size={14}/>Save credential</Button></div>
   </form>
  </Section>:null}
  <Section title="Managed credentials" subtitle="Verification uses configured device connection details and rejects untrusted SSH host keys." actions={<Button size="sm" variant="outline" onClick={()=>records.reload()}><RefreshCw size={14}/>Refresh</Button>}>
   {!projectId?<EmptyState title="Select a Project" message="A Project is required to view credentials."/>:records.loading?<LoadingState label="Loading credential metadata…"/>:records.error?<ErrorState error={records.error} onRetry={records.reload}/>:<DataTable caption="Managed credentials" columns={columns} rows={records.data?.items||[]} rowKey={row=>row.credential_id} emptyTitle="No credentials yet" emptyMessage="Attach a credential to a configured device to get started."/>}
  </Section>
 </div>;
}

const DEFAULT_SCHEMA=JSON.stringify({
 type:"object",required:["ssid","channel"],additionalProperties:false,
 properties:{ssid:{type:"string",minLength:1,maxLength:32},channel:{type:"integer",minimum:1,maximum:165},country:{type:"string"}},
},null,2);
const DEFAULT_VALUES=JSON.stringify({ssid:"LabNet",channel:36,country:"IN"},null,2);
export function ConfigurationPage({user}){
 const {projects,projectId,setProjectId}=useProjectSelection();
 const schemas=useAsyncLoader(()=>api.configurationSchemas(projectId),[projectId],{enabled:Boolean(projectId),queryKey:"configuration-schemas"});
 const profiles=useAsyncLoader(()=>api.configurationProfiles(projectId),[projectId],{enabled:Boolean(projectId),queryKey:"configuration-profiles"});
 const assignments=useAsyncLoader(()=>api.configurationAssignments(projectId),[projectId],{enabled:Boolean(projectId),queryKey:"configuration-assignments"});
 const mutation=useMutation();
 const [schemaForm,setSchemaForm]=useState({schema_id:"network.wifi",name:"WiFi Network",definition:DEFAULT_SCHEMA});
 const [profileForm,setProfileForm]=useState({name:"Wireless Lab",description:"",scope_type:"LAB",scope_id:"",schema_record_id:""});
 const [selectedProfile,setSelectedProfile]=useState("");
 const [valuesText,setValuesText]=useState(DEFAULT_VALUES);
 const [yamlText,setYamlText]=useState("");
 const [revisionId,setRevisionId]=useState("");
 const [target,setTarget]=useState({target_type:"LAB",target_id:""});
 const [preview,setPreview]=useState(null);
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const selectedSchema=(schemas.data?.items||[]).find(item=>item.schema_record_id===profileForm.schema_record_id);
 const selectedProfileRecord=(profiles.data?.items||[]).find(item=>item.profile_id===selectedProfile);
 const revisions=useAsyncLoader(()=>api.configurationRevisions(selectedProfile),[selectedProfile],{enabled:Boolean(selectedProfile),queryKey:"configuration-revisions"});
 useEffect(()=>{
  if(!profileForm.schema_record_id&&(schemas.data?.items||[]).length){
   const item=schemas.data.items[0];setProfileForm(current=>({...current,schema_record_id:item.schema_record_id}));
  }
 },[schemas.data,profileForm.schema_record_id]);
 useEffect(()=>{
  if(!selectedProfile&&(profiles.data?.items||[]).length)setSelectedProfile(profiles.data.items[0].profile_id);
 },[profiles.data,selectedProfile]);
 async function perform(action,success,refresh=true){
  setError("");setNotice("");setPreview(null);
  try{
   const result=await mutation.run(action);
   setNotice(success);
   if(refresh){await Promise.all([schemas.reload(),profiles.reload(),assignments.reload(),revisions.reload().catch(()=>null)]);}
   return result;
  }catch(exc){setError(exc.message||"Configuration operation failed.");return null;}
 }
 async function registerSchema(event){
  event.preventDefault();
  let definition;
  try{definition=JSON.parse(schemaForm.definition);}catch{setError("Schema definition must be valid JSON.");return;}
  await perform(()=>api.registerConfigurationSchema({project_id:projectId,schema_id:schemaForm.schema_id,name:schemaForm.name,version:1,definition}),"Configuration schema registered.");
 }
 async function createProfile(event){
  event.preventDefault();
  const result=await perform(()=>api.createConfigurationProfile({...profileForm,project_id:projectId,scope_id:profileForm.scope_type==="PROJECT"?projectId:profileForm.scope_id}),"Configuration profile created.");
  if(result?.profile_id)setSelectedProfile(result.profile_id);
 }
 async function createRevision(event){
  event.preventDefault();
  let values;try{values=JSON.parse(valuesText);}catch{setError("Configuration values must be valid JSON.");return;}
  if(!selectedProfile){setError("Select a profile first.");return;}
  const result=await perform(()=>api.createConfigurationRevision(selectedProfile,{values,provenance:{source:"dashboard"}}),"Draft revision created.");
  if(result?.revision_id)setRevisionId(result.revision_id);
 }
 async function publish(){
  if(!selectedProfile||!revisionId){setError("Create or select a draft revision first.");return;}
  await perform(()=>api.publishConfigurationRevision(selectedProfile,{revision_id:revisionId}),"Configuration revision published.");
 }
 async function rollback(source){
  const result=await perform(()=>api.rollbackConfigurationRevision(selectedProfile,{source_revision_id:source}),"Rollback draft created from the selected historical revision.");
  if(result?.revision_id)setRevisionId(result.revision_id);
 }
 async function applyRevision(){
  if(!selectedProfile||!revisionId){setError("Select a published revision to assign.");return;}
  const result=await perform(()=>api.applyConfigurationRevision(selectedProfile,{revision_id:revisionId,...target}),"Published revision assigned. Provider deployment is a later topology/provisioning operation.");
  if(result?.assignment_id)setRevisionId(result.revision_id);
 }
 async function importYaml(event){
  event.preventDefault();
  if(!selectedProfile){setError("Select a profile first.");return;}
  const result=await perform(()=>api.importConfigurationYaml({profile_id:selectedProfile,yaml_text:yamlText}),"Safe YAML imported as a draft revision.");
  if(result?.revision_id){setRevisionId(result.revision_id);setValuesText(JSON.stringify(result.values,null,2));setYamlText("");}
 }
 async function resolveEffective(){
  if(!projectId){return;}
  const payload={project_id:projectId};
  if(target.target_type==="LAB")payload.lab_id=target.target_id;
  if(target.target_type==="DEVICE")payload.device_id=target.target_id;
  const result=await perform(()=>api.resolveConfiguration(payload),"Effective configuration resolved.",false);
  if(result?.values)setPreview(result);
 }
 const revisionColumns=[
  {key:"revision_number",label:"Revision"},
  {key:"configuration_hash",label:"Content hash",render:item=><code title={item.configuration_hash}>{item.configuration_hash.slice(0,12)}…</code>},
  {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
  {key:"created_at",label:"Created",render:item=>new Date(item.created_at).toLocaleString()},
  {key:"actions",label:"Actions",render:item=><div className="button-row"><Button size="sm" variant="outline" onClick={()=>{setRevisionId(item.revision_id);setValuesText(JSON.stringify(item.values,null,2));}}>Select</Button>{item.status==="PUBLISHED"?<Button size="sm" variant="ghost" onClick={()=>rollback(item.revision_id)}>Rollback</Button>:null}</div>},
 ];
 return <div className="page-stack">
  <div className="module-intro"><div className="module-intro-icon"><Settings2 size={19}/></div><div><strong>Versioned, schema-validated configuration</strong><p>Published revisions are immutable. Rollback creates a new revision. Applying a profile assigns its published version; it does not configure a physical device until provider workflows are delivered.</p></div></div>
  <Section title="Project and scope" subtitle="Schemas and profiles are isolated by Project.">
   <div className="config-toolbar"><ProjectPicker projects={projects} projectId={projectId} onChange={value=>{setProjectId(value);setSelectedProfile("");setRevisionId("");setPreview(null);}}/><span className="context-caption">{(schemas.data?.items||[]).length} schemas · {(profiles.data?.items||[]).length} profiles</span></div>
  </Section>
  <PageNotice notice={notice}/>{error?<InlineNotice tone="danger">{error}</InlineNotice>:null}
  {canPerform(user,"configurations.manage")?<Section title="Schema registry" subtitle="Register a typed object schema. Sensitive secret-like fields and open-ended properties are rejected.">
   <form className="form-grid" onSubmit={registerSchema}>
    <Field label="Schema ID"><input value={schemaForm.schema_id} onChange={event=>setSchemaForm({...schemaForm,schema_id:event.target.value})} required/></Field>
    <Field label="Schema name"><input value={schemaForm.name} onChange={event=>setSchemaForm({...schemaForm,name:event.target.value})} required/></Field>
    <Field label="Schema JSON" className="full-width"><textarea rows={7} value={schemaForm.definition} onChange={event=>setSchemaForm({...schemaForm,definition:event.target.value})}/></Field>
    <div className="form-actions"><Button type="submit" disabled={mutation.loading||!projectId}>Register schema v1</Button></div>
   </form>
   {schemas.data?.items?.length?<DataTable caption="Registered configuration schemas" columns={[{key:"schema_id",label:"Schema"},{key:"version",label:"Version"},{key:"name",label:"Name"},{key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>}]} rows={schemas.data.items} rowKey={item=>item.schema_record_id}/>:null}
  </Section>:null}
  {canPerform(user,"configurations.manage")?<Section title="Create a profile" subtitle="Project, Lab and configured Device scopes feed the existing deterministic resolver.">
   <form className="form-grid" onSubmit={createProfile}>
    <Field label="Profile name"><input value={profileForm.name} onChange={event=>setProfileForm({...profileForm,name:event.target.value})} required/></Field>
    <Field label="Scope"><select value={profileForm.scope_type} onChange={event=>setProfileForm({...profileForm,scope_type:event.target.value,scope_id:""})}><option value="PROJECT">Project defaults</option><option value="LAB">Lab</option><option value="DEVICE">Device</option></select></Field>
    {profileForm.scope_type!=="PROJECT"?<Field label={profileForm.scope_type==="LAB"?"Lab ID":"Device ID"}><input value={profileForm.scope_id} onChange={event=>setProfileForm({...profileForm,scope_id:event.target.value})} required/></Field>:null}
    <Field label="Description"><input value={profileForm.description} onChange={event=>setProfileForm({...profileForm,description:event.target.value})}/></Field>
    <Field label="Registered schema"><select value={profileForm.schema_record_id} onChange={event=>setProfileForm({...profileForm,schema_record_id:event.target.value})}><option value="">Select schema</option>{(schemas.data?.items||[]).map(item=><option key={item.schema_record_id} value={item.schema_record_id}>{item.schema_id} · v{item.version}</option>)}</select></Field>
    <div className="form-actions"><Button type="submit" disabled={mutation.loading||!projectId||!profileForm.schema_record_id}>Create profile</Button></div>
   </form>
  </Section>:null}
  <Section title="Profile revisions" subtitle="Edit a draft, inspect immutable history, publish, roll back or assign a known revision.">
   <div className="form-grid">
    <Field label="Selected profile"><select value={selectedProfile} onChange={event=>{setSelectedProfile(event.target.value);setRevisionId("");}}><option value="">Select profile</option>{(profiles.data?.items||[]).map(item=><option key={item.profile_id} value={item.profile_id}>{item.name} · {item.scope_type}</option>)}</select></Field>
    <Field label="Revision"><select value={revisionId} onChange={event=>setRevisionId(event.target.value)}><option value="">Select revision</option>{(revisions.data?.items||[]).map(item=><option key={item.revision_id} value={item.revision_id}>r{item.revision_number} · {item.status}</option>)}</select></Field>
   </div>
   {selectedProfileRecord?<div className="context-caption">{selectedProfileRecord.description||selectedProfileRecord.name} · {selectedProfileRecord.scope_type}:{selectedProfileRecord.scope_id} · {selectedProfileRecord.status}</div>:null}
   {canPerform(user,"configurations.manage")?<form className="form-grid" onSubmit={createRevision}>
    <Field label="Configuration values (JSON)" className="full-width" hint="Never include passwords, tokens, PSKs or private keys. Attach them through the credential vault."><textarea rows={8} value={valuesText} onChange={event=>setValuesText(event.target.value)}/></Field>
    <div className="form-actions"><Button type="submit" disabled={mutation.loading||!selectedProfile}>Create draft revision</Button></div>
   </form>:null}
   {revisions.loading?<LoadingState label="Loading revision history…"/>:revisions.error?<ErrorState error={revisions.error} onRetry={revisions.reload}/>:<DataTable caption="Configuration revision history" columns={revisionColumns} rows={revisions.data?.items||[]} rowKey={item=>item.revision_id} emptyTitle="No revisions" emptyMessage="Create the first draft revision for this profile."/>}
   <div className="button-row">
    {canPerform(user,"configurations.publish")?<Button disabled={!selectedProfile||!revisionId||mutation.loading} onClick={publish}><ShieldCheck size={14}/>Publish selected revision</Button>:null}
    {canPerform(user,"configurations.publish")?<Button variant="outline" disabled={!selectedProfile||!revisionId||mutation.loading} onClick={applyRevision}><UploadCloud size={14}/>Assign selected revision</Button>:null}
   </div>
  </Section>
  {canPerform(user,"configurations.manage")?<Section title="Import legacy YAML" subtitle="Imports are parsed with safe_load and rejected when they contain inline secret fields.">
   <form className="form-grid" onSubmit={importYaml}>
    <Field label="YAML source" className="full-width"><textarea rows={7} value={yamlText} onChange={event=>setYamlText(event.target.value)} placeholder={"ssid: LabNet\nchannel: 36"}/></Field>
    <div className="form-actions"><Button type="submit" variant="outline" disabled={!selectedProfile||!yamlText.trim()||mutation.loading}>Import as draft</Button></div>
   </form>
  </Section>:null}
  <Section title="Assignment and effective preview" subtitle="Inspect the exact merged values and source provenance before a validation run.">
   <div className="form-grid">
    <Field label="Target type"><select value={target.target_type} onChange={event=>setTarget({...target,target_type:event.target.value,target_id:event.target.value==="PROJECT"?projectId:""})}><option value="PROJECT">Project</option><option value="LAB">Lab</option><option value="DEVICE">Device</option></select></Field>
    {target.target_type!=="PROJECT"?<Field label="Target ID"><input value={target.target_id} onChange={event=>setTarget({...target,target_id:event.target.value})} placeholder="Configured target ID"/></Field>:null}
    <div className="form-actions"><Button variant="outline" onClick={resolveEffective} disabled={!projectId||mutation.loading}>Preview effective configuration</Button></div>
   </div>
   {preview?<div className="config-preview"><div className="config-preview-meta"><strong>Resolved configuration</strong><span>SHA-256 · {preview.configuration_hash}</span></div><pre>{JSON.stringify({values:preview.values,provenance:preview.provenance,assignments:preview.assignments},null,2)}</pre></div>:null}
   <DataTable caption="Configuration assignments" columns={[{key:"target_type",label:"Target"},{key:"target_id",label:"Target ID"},{key:"profile_id",label:"Profile"},{key:"revision_id",label:"Revision"},{key:"assigned_at",label:"Assigned",render:item=>new Date(item.assigned_at).toLocaleString()}]} rows={assignments.data?.items||[]} rowKey={item=>item.assignment_id} emptyTitle="No assignments" emptyMessage="Assign a published revision to a Project, Lab or Device."/>
  </Section>
 </div>;
}
