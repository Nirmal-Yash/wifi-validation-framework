import React,{useMemo,useState} from "react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader,useMutation} from "../hooks";
import {formatDate} from "../utils";
import {Button,DataTable,ErrorState,Field,InlineNotice,LoadingState,Pagination,Section,StatusBadge} from "../components/ui";
export default function RunsPage({user}){
 const[filters,setFilters]=useState({firmware:"",lab:"",profile:"",status:"",outcome:"",page:1});
 const[form,setForm]=useState({firmware_version:"v1.0",tests:""}),[showLaunch,setShowLaunch]=useState(false);
 const loader=useAsyncLoader(()=>api.runs({firmware:filters.firmware,lab:filters.lab,profile:filters.profile,status:filters.status,outcome:filters.outcome,page:filters.page,limit:25}),[filters.firmware,filters.lab,filters.profile,filters.status,filters.outcome,filters.page],{refreshMs:10000});
 const mutation=useMutation(),canLaunch=["OWNER","ADMIN","OPERATOR"].includes(user.role);
 const statusOptions=useMemo(()=>["","QUEUED","PREPARING","LAB_HEALTH_CHECK","RUNNING","FINALIZING","COMPLETED","FAILED","LAB_FAILED","CANCELLED","ABORTED"],[]);
 const apply=event=>{event.preventDefault();setFilters(current=>({...current,page:1}));};
 const startRun=async event=>{event.preventDefault();try{await mutation.run(()=>api.launch({firmware_version:form.firmware_version.trim()||"v1.0",tests:form.tests.split(",").map(item=>item.trim()).filter(Boolean)}));setShowLaunch(false);await loader.reload();}catch{}};
 if(loader.loading&&!loader.data)return<LoadingState label="Loading Runs…"/>;
 if(loader.error&&!loader.data)return<ErrorState error={loader.error} onRetry={loader.reload}/>;
 return<div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Operate</div><h2>Runs</h2><p className="muted">Filter persisted Runs and inspect their complete validation evidence.</p></div>{canLaunch?<Button onClick={()=>setShowLaunch(true)}>Start Run</Button>:null}</div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">Run process started. Refreshing the Run list.</InlineNotice>:null}
  <Section title="Filters"><form className="filter-grid" onSubmit={apply}>
   <Field label="Firmware"><input value={filters.firmware} onChange={e=>setFilters({...filters,firmware:e.target.value})}/></Field>
   <Field label="Lab"><input value={filters.lab} onChange={e=>setFilters({...filters,lab:e.target.value})}/></Field>
   <Field label="Profile"><input value={filters.profile} onChange={e=>setFilters({...filters,profile:e.target.value})}/></Field>
   <Field label="Status"><select value={filters.status} onChange={e=>setFilters({...filters,status:e.target.value})}>{statusOptions.map(value=><option key={value} value={value}>{value||"All"}</option>)}</select></Field>
   <Field label="Outcome"><select value={filters.outcome} onChange={e=>setFilters({...filters,outcome:e.target.value})}><option value="">All</option><option>VALIDATED</option><option>VALIDATED_WITH_WARNINGS</option><option>REJECTED</option><option>UNVALIDATED</option></select></Field>
   <div className="filter-actions"><Button type="submit">Apply</Button><Button type="button" variant="secondary" onClick={()=>setFilters({firmware:"",lab:"",profile:"",status:"",outcome:"",page:1})}>Reset</Button></div>
  </form></Section>
  <Section title="Historical Runs" subtitle={(loader.data?.total||0)+" Run(s)"}>
   <DataTable rows={loader.data?.items||[]} rowKey={row=>row.run_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(row.run_id))} columns={[
    {key:"display_id",label:"Run",render:row=><><strong>{row.display_id}</strong><div className="muted mono">{row.run_id}</div></>},
    {key:"firmware_version",label:"Firmware"},{key:"device_id",label:"Device"},{key:"lab_id",label:"Lab"},{key:"validation_profile",label:"Profile"},
    {key:"lifecycle_status",label:"Lifecycle",render:row=><StatusBadge value={row.lifecycle_status}/>},
    {key:"business_outcome",label:"Outcome",render:row=><StatusBadge value={row.business_outcome}/>},
    {key:"created_at",label:"Created",render:row=>formatDate(row.created_at)}
   ]} emptyTitle="No matching Runs" emptyMessage="Try removing one or more filters."/>
   <Pagination page={loader.data?.page||1} pages={loader.data?.pages||1} onChange={page=>setFilters({...filters,page})}/>
  </Section>
  {showLaunch?<div className="dialog-backdrop" role="presentation"><div className="dialog wide" role="dialog" aria-modal="true" aria-labelledby="launch-title">
   <h2 id="launch-title">Start validation Run</h2><p className="muted">The API validates authorization, configuration and idempotency. This form only submits the requested scope.</p>
   <form className="form-stack" onSubmit={startRun}>
    <Field label="Firmware version"><input value={form.firmware_version} onChange={e=>setForm({...form,firmware_version:e.target.value})} required/></Field>
    <Field label="Tests" hint="Optional comma-separated TestRegistry IDs. Leave empty for the configured default selection."><input value={form.tests} onChange={e=>setForm({...form,tests:e.target.value})}/></Field>
    {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:null}
    <div className="dialog-actions"><Button type="button" variant="secondary" onClick={()=>setShowLaunch(false)}>Close</Button><Button type="submit" loading={mutation.loading}>Start Run</Button></div>
   </form>
  </div></div>:null}
 </div>;
}