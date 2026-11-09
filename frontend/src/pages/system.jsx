import React,{useState} from "react";
import {api} from "../api";
import {useAsyncLoader,useMutation} from "../hooks";
import {formatBytes,formatDate} from "../utils";
import {canAdmin} from "../permissions";
import {Button,ConfirmDialog,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "../components/ui";
export function ArtifactsPage(){
 const[filters,setFilters]=useState({run_id:"",artifact_type:"",page:1});
 const loader=useAsyncLoader(()=>api.artifacts({run_id:filters.run_id,artifact_type:filters.artifact_type,page:filters.page,limit:50}),[filters.run_id,filters.artifact_type,filters.page]);
 if(loader.loading&&!loader.data)return<LoadingState label="Loading artifacts…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 const data=loader.data;
 return<div className="page-stack">
  <div className="page-actions-row"><span className="context-caption">Registered, integrity-verified evidence only</span></div>
  <Section title="Filters"><div className="filter-grid"><Field label="Run ID"><input value={filters.run_id} onChange={e=>setFilters({...filters,run_id:e.target.value,page:1})}/></Field><Field label="Artifact type"><select value={filters.artifact_type} onChange={e=>setFilters({...filters,artifact_type:e.target.value,page:1})}><option value="">All</option><option>PCAP</option><option>TELEMETRY</option><option>LAB_HEALTH_SNAPSHOT</option><option>PROTOCOL_EVIDENCE</option><option>COMMAND_OUTPUT</option><option>DIAGNOSTIC_BUNDLE</option></select></Field></div></Section>
  <Section title="Registered evidence" subtitle={(data?.total||0)+" artifact(s)"}><DataTable rows={data?.items||[]} rowKey={row=>row.artifact_id} columns={[
   {key:"display_name",label:"Name",render:row=><><strong>{row.display_name}</strong><div className="muted mono">{row.artifact_id}</div></>},{key:"artifact_type",label:"Type"},{key:"run_id",label:"Run"},{key:"size_bytes",label:"Size",render:row=>formatBytes(row.size_bytes)},{key:"sha256",label:"SHA-256",render:row=><code className="hash">{row.sha256}</code>},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"sensitivity_class",label:"Sensitivity",render:row=><StatusBadge value={row.sensitivity_class}/>},{key:"created_at",label:"Created",render:row=>formatDate(row.created_at)},{key:"downloadable",label:"Action",render:row=>row.downloadable?<a className="text-link" href={api.artifactDownloadUrl(row.artifact_id)} target="_blank" rel="noreferrer">Download</a>:"Unavailable"}
  ]} emptyTitle="No artifacts" emptyMessage="No registered evidence matches the current filters."/>
  {data?.pages>1?<div className="pagination"><Button variant="secondary" disabled={data.page<=1} onClick={()=>setFilters({...filters,page:data.page-1})}>Previous</Button><span>Page {data.page} of {data.pages}</span><Button variant="secondary" disabled={data.page>=data.pages} onClick={()=>setFilters({...filters,page:data.page+1})}>Next</Button></div>:null}
  </Section>
 </div>;
}
export function LabHealthPage(){
 const[selector,setSelector]=useState(""),[mode,setMode]=useState("run"),[submitted,setSubmitted]=useState("");
 const loader=useAsyncLoader(()=>mode==="run"?api.healthForRun(submitted):api.labHealth(submitted),[submitted,mode],{enabled:Boolean(submitted)});
 const items=mode==="run"?(loader.data?.items||[]):(loader.data?.item?[loader.data.item]:[]);
 return<div className="page-stack">
  <div className="page-actions-row"><span className="context-caption">Read-only environment evidence · no repair actions from this view</span></div>
  <Section title="Inspect health"><div className="filter-grid"><Field label="Selector"><input value={selector} onChange={e=>setSelector(e.target.value)} placeholder={mode==="run"?"Run ID":"Lab ID"}/></Field><Field label="Mode"><select value={mode} onChange={e=>{setMode(e.target.value);setSubmitted("");}}><option value="run">Run</option><option value="lab">Lab</option></select></Field><div className="filter-actions"><Button onClick={()=>setSubmitted(selector.trim())} disabled={!selector.trim()}>Load</Button></div></div></Section>
  {loader.loading?<LoadingState label="Loading health evidence…"/>:null}{loader.error?<InlineNotice tone="danger">{loader.error.message}</InlineNotice>:null}
  {items.length?items.map((item,index)=>{const snapshot=item.snapshot||{};return<Section key={index} title={snapshot.phase||"Latest health"} subtitle={formatDate(snapshot.completed_at)} actions={<StatusBadge value={snapshot.overall_status}/>}><DataTable rows={snapshot.observations||[]} rowKey={(row,i)=>(row.component||"component")+"-"+i} columns={[
   {key:"component",label:"Component"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"required",label:"Required",render:row=>row.required?"Yes":"No"},{key:"summary",label:"Summary"},{key:"observed_at",label:"Observed",render:row=>formatDate(row.observed_at)}
  ]} emptyTitle="No observations" emptyMessage="No component observations were persisted."/></Section>;}):submitted&&!loader.loading?<EmptyState title="No health snapshots" message="No integrity-verified Lab Health evidence was found."/>:null}
 </div>;
}
export function ReadinessPage(){
 const loader=useAsyncLoader(()=>api.readiness(),[],{refreshMs:30000});
 if(loader.loading&&!loader.data)return<LoadingState label="Checking Runner readiness…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 const data=loader.data;
 return<div className="page-stack"><div className="page-actions-row"><span className="context-caption">Runtime readiness is not REAL_LAB certification</span><StatusBadge value={data?.status}/></div><InlineNotice tone={data?.status==="ready"?"success":"warning"}>{data?.summary}</InlineNotice><Section title="Readiness checks"><DataTable rows={data?.checks||[]} rowKey={row=>row.check_id} columns={[{key:"check_id",label:"Check"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"message",label:"Message"}]} emptyTitle="No readiness checks" emptyMessage="The Runner returned no structured readiness checks."/></Section></div>;
}
export function BaselinesPage(){
 const loader=useAsyncLoader(()=>api.baselines(),[]),mutation=useMutation();
 const[confirm,setConfirm]=useState(false);
 const[form,setForm]=useState({run_id:"",name:"Golden",device_scope:"",firmware_major_scope:"",test_suite_version:"",lab_class:""});
 const promote=event=>{event.preventDefault();setConfirm(true);};
 const executePromote=async()=>{
  try{await mutation.run(()=>api.promoteBaseline(form));setConfirm(false);await loader.reload();}
  catch{setConfirm(false);}
 };
 if(loader.loading&&!loader.data)return<LoadingState label="Loading baselines…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 return<div className="page-stack"><div className="page-actions-row"><span className="context-caption">Owner/Admin permission required · API authorization remains authoritative</span></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">Baseline promoted successfully.</InlineNotice>:null}
  <Section title="Promote a Run"><form className="filter-grid" onSubmit={promote}>
   {Object.entries({run_id:"Run ID",name:"Name",device_scope:"Device scope",firmware_major_scope:"Firmware major scope",test_suite_version:"Test suite version",lab_class:"Lab class"}).map(([key,label])=><Field label={label} key={key}><input value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})} required={key==="run_id"||key==="name"}/></Field>)}<div className="filter-actions"><Button type="submit" loading={mutation.loading}>Promote baseline</Button></div>
  </form></Section>
  <Section title="Active baselines"><DataTable rows={loader.data?.items||[]} rowKey={row=>row.baseline_id} columns={[
   {key:"name",label:"Name"},{key:"baseline_id",label:"Baseline ID",render:row=><span className="mono">{row.baseline_id}</span>},{key:"baseline_run_id",label:"Run"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"device_scope",label:"Device scope"},{key:"firmware_major_scope",label:"Firmware scope"},{key:"test_suite_version",label:"Suite"},{key:"lab_class",label:"Lab class"}
  ]} emptyTitle="No active baselines" emptyMessage="No baseline has been promoted yet."/></Section>
  <ConfirmDialog open={confirm} title="Promote this Run as a baseline?" message="Baseline promotion changes the reference used by future regression and release comparisons. Verify the Run ID, scope and test-suite context before proceeding." confirmLabel="Promote baseline" loading={mutation.loading} onCancel={()=>setConfirm(false)} onConfirm={executePromote}/>
 </div>;
}
export function OperationsPage({user}){
 const mutation=useMutation(),[confirm,setConfirm]=useState(null),[firmware,setFirmware]=useState({run_id:"",device_id:"",image_path:"",version:"",reason:"",compatible_models:"",expected_sha256:"",signature_path:""}),[rollback,setRollback]=useState({device_id:"",run_id:"",expected_version:"",reason:""}),[waiver,setWaiver]=useState({scope:"RELEASE",target_id:"",issue_code:"",reason:"",expires_at:""});
 const administrator=canAdmin(user?.role);
 const waiverLoader=useAsyncLoader(()=>administrator?api.waivers():Promise.resolve({items:[]}),[administrator],{enabled:administrator});
 const syncQueueLoader=useAsyncLoader(()=>administrator?api.syncQueue(50):Promise.resolve({summary:{},items:[]}),[administrator],{enabled:administrator,refreshMs:30000});
 const update=(setter,state,key,value)=>setter({...state,[key]:value});
 const flash=event=>{event.preventDefault();setConfirm("flash");};
 const rollbackRun=event=>{event.preventDefault();setConfirm("rollback");};
 const createWaiver=event=>{event.preventDefault();setConfirm("waiver");};
 const executeConfirmed=async()=>{
  try{
   if(confirm==="flash")await mutation.run(()=>api.firmwareOperation({...firmware,compatible_models:firmware.compatible_models.split(",").map(value=>value.trim()).filter(Boolean)}));
   if(confirm==="rollback")await mutation.run(()=>api.firmwareRollback(rollback.device_id,{run_id:rollback.run_id,expected_version:rollback.expected_version,reason:rollback.reason}));
   if(confirm==="waiver")await mutation.run(()=>api.createWaiver({...waiver,expires_at:waiver.expires_at?new Date(waiver.expires_at).toISOString():null}));
   setConfirm(null);
  }catch{setConfirm(null);}
 };
 return<div className="page-stack"><div className="page-actions-row"><span className="context-caption">State-changing controls · API-enforced authorization and audit</span><span className="role-chip">{user.role}</span></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">The requested operation was accepted by the Runner.</InlineNotice>:null}
  <Section title="Firmware operation" subtitle="Firmware images are confined and validated by the backend before flashing."><form className="form-grid" onSubmit={flash}>
   {Object.entries({run_id:"Run ID",device_id:"Device ID",image_path:"Image path",version:"Version",compatible_models:"Compatible models",expected_sha256:"Expected SHA-256",signature_path:"Signature path",reason:"Authorization reason"}).map(([key,label])=><Field label={label} key={key}><input value={firmware[key]} onChange={e=>update(setFirmware,firmware,key,e.target.value)} required={["run_id","device_id","image_path","version","reason"].includes(key)} /></Field>)}<div className="form-actions"><Button type="submit" loading={mutation.loading}>Start firmware operation</Button></div>
  </form></Section>
  <Section title="Firmware rollback" subtitle="Rollback is explicit. It is never automatically triggered by this UI."><form className="form-grid compact" onSubmit={rollbackRun}><Field label="Device ID"><input value={rollback.device_id} onChange={e=>update(setRollback,rollback,"device_id",e.target.value)} required/></Field><Field label="Run ID"><input value={rollback.run_id} onChange={e=>update(setRollback,rollback,"run_id",e.target.value)} required/></Field><Field label="Expected restored firmware version"><input value={rollback.expected_version} onChange={e=>update(setRollback,rollback,"expected_version",e.target.value)} required placeholder="e.g. v1.0.0"/></Field><Field label="Authorization reason" required><textarea value={rollback.reason} onChange={e=>update(setRollback,rollback,"reason",e.target.value)} required minLength={8}/></Field><div className="form-actions"><Button type="submit" variant="danger" loading={mutation.loading}>Execute rollback</Button></div></form></Section>
  {administrator?<Section title="Release waiver" subtitle="Owner/Admin only. Waivers should be narrowly scoped, justified and time-limited."><form className="form-grid" onSubmit={createWaiver}><Field label="Scope"><select value={waiver.scope} onChange={e=>update(setWaiver,waiver,"scope",e.target.value)}><option>TEST</option><option>RUN</option><option>REGRESSION</option><option>RELEASE</option></select></Field><Field label="Target ID"><input value={waiver.target_id} onChange={e=>update(setWaiver,waiver,"target_id",e.target.value)} required/></Field><Field label="Issue code"><input value={waiver.issue_code} onChange={e=>update(setWaiver,waiver,"issue_code",e.target.value)} required/></Field><Field label="Expires at"><input type="datetime-local" value={waiver.expires_at} onChange={e=>update(setWaiver,waiver,"expires_at",e.target.value)}/></Field><Field label="Reason"><textarea value={waiver.reason} onChange={e=>update(setWaiver,waiver,"reason",e.target.value)} required/></Field><div className="form-actions"><Button type="submit" loading={mutation.loading}>Create waiver</Button></div></form></Section>:null}
  {administrator?<Section title="Offline synchronization queue" subtitle="Read-only Runner-local queue status. Local Runs remain authoritative until an outbound HTTPS acknowledgement is persisted."><div className="metric-summary-strip">{Object.entries(syncQueueLoader.data?.summary||{}).map(([state,count])=><span key={state}>{state.replaceAll("_"," ")}: <strong>{count}</strong></span>)}</div>{syncQueueLoader.loading?<InlineNotice>Loading local queue…</InlineNotice>:null}{syncQueueLoader.error?<InlineNotice tone="danger">{syncQueueLoader.error.message}</InlineNotice>:null}<DataTable caption="Recent offline sync envelopes" rows={syncQueueLoader.data?.items||[]} rowKey={item=>item.envelope_id} columns={[{key:"state",label:"State",render:item=><StatusBadge value={item.state}/>},{key:"run_id",label:"Run"},{key:"attempt_count",label:"Attempts"},{key:"next_attempt_at",label:"Next retry",render:item=>formatDate(item.next_attempt_at)},{key:"updated_at",label:"Updated",render:item=>formatDate(item.updated_at)},{key:"last_error",label:"Last error",render:item=>item.last_error||"—"}]} emptyTitle="No offline envelopes" emptyMessage="No terminal Run snapshots are queued for synchronization."/><InlineNotice tone="warning">Synchronization is operator-triggered and outbound-only. Configure NETREGRESS_SYNC_URL and NETREGRESS_SYNC_TOKEN, then run <code>python scripts/netregress_sync.py</code>. This view does not mutate Run results or upload raw evidence.</InlineNotice></Section>:null}
  {administrator?<Section title="Active release waivers"  {administrator?<Section title="Active release waivers" subtitle="Only active, non-expired waiver records are listed."><DataTable caption="Active release waivers" rows={waiverLoader.data?.items||[]} rowKey={item=>item.waiver_id} columns={[{key:"scope",label:"Scope"},{key:"target_id",label:"Target"},{key:"issue_code",label:"Issue"},{key:"reason",label:"Reason"},{key:"created_by",label:"Created by"},{key:"expires_at",label:"Expires",render:item=>formatDate(item.expires_at)}]} emptyTitle="No active waivers" emptyMessage="No active waiver records are available."/></Section>:null}
  <InlineNotice tone="warning">Firmware flash, rollback and release waivers change device state or release posture. The UI requires a second confirmation; the API independently enforces role, CSRF and idempotency controls.</InlineNotice>
  <ConfirmDialog open={Boolean(confirm)} title={confirm==="flash"?"Confirm firmware operation":confirm==="rollback"?"Confirm firmware rollback":"Confirm release waiver"} message={confirm==="flash"?"The Runner will validate the image path, digest, signature policy and device compatibility before the firmware operation. Proceed only with explicit authorization.":confirm==="rollback"?"Rollback changes the target device firmware. Confirm the device, Run and authorization reason before proceeding.":"This waiver changes release-governance state. Verify scope, issue code, expiry and justification."} confirmLabel={confirm==="flash"?"Start firmware operation":confirm==="rollback"?"Execute rollback":"Create waiver"} danger={confirm!=="waiver"} loading={mutation.loading} onCancel={()=>setConfirm(null)} onConfirm={executeConfirmed}/>
 </div>;
}