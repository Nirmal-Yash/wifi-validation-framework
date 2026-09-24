import React,{useState} from "react";
import {api} from "../api";
import {useAsyncLoader,useMutation} from "../hooks";
import {formatBytes,formatDate} from "../utils";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "../components/ui";
export function ArtifactsPage(){
 const[filters,setFilters]=useState({run_id:"",artifact_type:"",page:1});
 const loader=useAsyncLoader(()=>api.artifacts({run_id:filters.run_id,artifact_type:filters.artifact_type,page:filters.page,limit:50}),[filters.run_id,filters.artifact_type,filters.page]);
 if(loader.loading&&!loader.data)return<LoadingState label="Loading artifacts…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 const data=loader.data;
 return<div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Operate</div><h2>Artifact browser</h2><p className="muted">Artifacts are interpreted only after containment and SHA-256 verification by the backend.</p></div></div>
  <Section title="Filters"><div className="filter-grid"><Field label="Run ID"><input value={filters.run_id} onChange={e=>setFilters({...filters,run_id:e.target.value,page:1})}/></Field><Field label="Artifact type"><select value={filters.artifact_type} onChange={e=>setFilters({...filters,artifact_type:e.target.value,page:1})}><option value="">All</option><option>PCAP</option><option>TELEMETRY</option><option>LAB_HEALTH_SNAPSHOT</option><option>PROTOCOL_EVIDENCE</option><option>COMMAND_OUTPUT</option><option>DIAGNOSTIC_BUNDLE</option></select></Field></div></Section>
  <Section title="Registered evidence" subtitle={(data?.total||0)+" artifact(s)"}><DataTable rows={data?.items||[]} rowKey={row=>row.artifact_id} columns={[
   {key:"display_name",label:"Name",render:row=><><strong>{row.display_name}</strong><div className="muted mono">{row.artifact_id}</div></>},{key:"artifact_type",label:"Type"},{key:"run_id",label:"Run"},{key:"size_bytes",label:"Size",render:row=>formatBytes(row.size_bytes)},{key:"sha256",label:"SHA-256",render:row=><code className="hash">{row.sha256}</code>},{key:"evidence_state",label:"Evidence",render:row=><StatusBadge value={row.evidence_state}/>},{key:"created_at",label:"Created",render:row=>formatDate(row.created_at)},{key:"downloadable",label:"Action",render:row=>row.downloadable?<a className="text-link" href={api.artifactDownloadUrl(row.artifact_id)} target="_blank" rel="noreferrer">Download</a>:"Unavailable"}
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
  <div className="page-title-row"><div><div className="eyebrow">Analyze</div><h2>Lab health</h2><p className="muted">Read-only evidence for whether the environment was trustworthy. This UI never triggers repair.</p></div></div>
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
 return<div className="page-stack"><div className="page-title-row"><div><div className="eyebrow">Operate</div><h2>Runner readiness</h2><p className="muted">Structured readiness checks. This is deployment/runtime readiness, not proof of a REAL_LAB certification run.</p></div><StatusBadge value={data?.status}/></div><InlineNotice tone={data?.status==="ready"?"success":"warning"}>{data?.summary}</InlineNotice><Section title="Readiness checks"><DataTable rows={data?.checks||[]} rowKey={row=>row.check_id} columns={[{key:"check_id",label:"Check"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"message",label:"Message"}]} emptyTitle="No readiness checks" emptyMessage="The Runner returned no structured readiness checks."/></Section></div>;
}
export function BaselinesPage(){
 const loader=useAsyncLoader(()=>api.baselines(),[]),mutation=useMutation();
 const[form,setForm]=useState({run_id:"",name:"Golden",device_scope:"",firmware_major_scope:"",test_suite_version:"",lab_class:""});
 const promote=async event=>{event.preventDefault();try{await mutation.run(()=>api.promoteBaseline(form));await loader.reload();}catch{}};
 if(loader.loading&&!loader.data)return<LoadingState label="Loading baselines…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 return<div className="page-stack"><div className="page-title-row"><div><div className="eyebrow">Govern</div><h2>Baselines</h2><p className="muted">Baseline promotion is administrator-gated and remains a persisted Runner operation.</p></div></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">Baseline promoted successfully.</InlineNotice>:null}
  <Section title="Promote a Run"><form className="filter-grid" onSubmit={promote}>
   {Object.entries({run_id:"Run ID",name:"Name",device_scope:"Device scope",firmware_major_scope:"Firmware major scope",test_suite_version:"Test suite version",lab_class:"Lab class"}).map(([key,label])=><Field label={label} key={key}><input value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})} required={key==="run_id"||key==="name"}/></Field>)}<div className="filter-actions"><Button type="submit" loading={mutation.loading}>Promote baseline</Button></div>
  </form></Section>
  <Section title="Active baselines"><DataTable rows={loader.data?.items||[]} rowKey={row=>row.baseline_id} columns={[
   {key:"name",label:"Name"},{key:"baseline_id",label:"Baseline ID",render:row=><span className="mono">{row.baseline_id}</span>},{key:"baseline_run_id",label:"Run"},{key:"status",label:"Status",render:row=><StatusBadge value={row.status}/>},{key:"device_scope",label:"Device scope"},{key:"firmware_major_scope",label:"Firmware scope"},{key:"test_suite_version",label:"Suite"},{key:"lab_class",label:"Lab class"}
  ]} emptyTitle="No active baselines" emptyMessage="No baseline has been promoted yet."/></Section>
 </div>;
}
export function OperationsPage(){
 const mutation=useMutation(),[firmware,setFirmware]=useState({run_id:"",device_id:"",image_path:"",version:"",reason:"",compatible_models:"",expected_sha256:"",signature_path:""}),[rollback,setRollback]=useState({device_id:"",run_id:"",reason:""}),[waiver,setWaiver]=useState({scope:"RELEASE",target_id:"",issue_code:"",reason:"",expires_at:""});
 const update=(setter,state,key,value)=>setter({...state,[key]:value});
 const flash=async event=>{event.preventDefault();try{await mutation.run(()=>api.firmwareOperation({...firmware,compatible_models:firmware.compatible_models.split(",").map(value=>value.trim()).filter(Boolean)}));}catch{}};
 const rollbackRun=async event=>{event.preventDefault();try{await mutation.run(()=>api.firmwareRollback(rollback.device_id,{run_id:rollback.run_id,reason:rollback.reason||"Authorized firmware rollback"}));}catch{}};
 const createWaiver=async event=>{event.preventDefault();try{await mutation.run(()=>api.createWaiver(waiver));}catch{}};
 return<div className="page-stack"><div className="page-title-row"><div><div className="eyebrow">Govern</div><h2>Operational controls</h2><p className="muted">These forms request state changes. API-side RBAC, CSRF, idempotency and authorization remain authoritative.</p></div></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">The requested operation was accepted by the Runner.</InlineNotice>:null}
  <Section title="Firmware operation" subtitle="Firmware images are confined and validated by the backend before flashing."><form className="form-grid" onSubmit={flash}>
   {Object.entries({run_id:"Run ID",device_id:"Device ID",image_path:"Image path",version:"Version",compatible_models:"Compatible models",expected_sha256:"Expected SHA-256",signature_path:"Signature path",reason:"Authorization reason"}).map(([key,label])=><Field label={label} key={key}><input value={firmware[key]} onChange={e=>update(setFirmware,firmware,key,e.target.value)} required={["run_id","device_id","image_path","version","reason"].includes(key)} /></Field>)}<div className="form-actions"><Button type="submit" loading={mutation.loading}>Start firmware operation</Button></div>
  </form></Section>
  <Section title="Firmware rollback" subtitle="Rollback is explicit. It is never automatically triggered by this UI."><form className="form-grid compact" onSubmit={rollbackRun}><Field label="Device ID"><input value={rollback.device_id} onChange={e=>update(setRollback,rollback,"device_id",e.target.value)} required/></Field><Field label="Run ID"><input value={rollback.run_id} onChange={e=>update(setRollback,rollback,"run_id",e.target.value)} required/></Field><Field label="Authorization reason"><textarea value={rollback.reason} onChange={e=>update(setRollback,rollback,"reason",e.target.value)}/></Field><div className="form-actions"><Button type="submit" variant="danger" loading={mutation.loading}>Execute rollback</Button></div></form></Section>
  <Section title="Release waiver" subtitle="Waivers are administrator-gated and scoped by the backend. Prefer explicit expiry for temporary exceptions."><form className="form-grid" onSubmit={createWaiver}><Field label="Scope"><select value={waiver.scope} onChange={e=>update(setWaiver,waiver,"scope",e.target.value)}><option>TEST</option><option>RUN</option><option>REGRESSION</option><option>RELEASE</option></select></Field><Field label="Target ID"><input value={waiver.target_id} onChange={e=>update(setWaiver,waiver,"target_id",e.target.value)} required/></Field><Field label="Issue code"><input value={waiver.issue_code} onChange={e=>update(setWaiver,waiver,"issue_code",e.target.value)} required/></Field><Field label="Expires at"><input type="datetime-local" value={waiver.expires_at} onChange={e=>update(setWaiver,waiver,"expires_at",e.target.value)}/></Field><Field label="Reason"><textarea value={waiver.reason} onChange={e=>update(setWaiver,waiver,"reason",e.target.value)} required/></Field><div className="form-actions"><Button type="submit" loading={mutation.loading}>Create waiver</Button></div></form></Section>
  <InlineNotice tone="warning">Firmware mutation and waiver creation can change release posture or device state. Review the target, scope and authorization reason before submitting.</InlineNotice>
 </div>;
}