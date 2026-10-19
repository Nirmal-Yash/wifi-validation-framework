import React,{useMemo,useState} from "react";
import {Filter,Play,RotateCcw,Search} from "lucide-react";
import {api} from "../api";
import {navigate} from "../router";
import {useAsyncLoader,useMutation} from "../hooks";
import {formatDate} from "../utils";
import {Button,DataTable,ErrorState,Field,InlineNotice,LoadingState,Pagination,Section,StatusBadge} from "../components/ui";

export default function RunsPage({user}){
 const[filters,setFilters]=useState({firmware:"",lab:"",profile:"",status:"",outcome:"",page:1});
 const[form,setForm]=useState({firmware_version:"v1.0",tests:""}),[showLaunch,setShowLaunch]=useState(()=>new URLSearchParams(window.location.search).get("launch")==="1");
 const loader=useAsyncLoader(()=>api.runs({firmware:filters.firmware,lab:filters.lab,profile:filters.profile,status:filters.status,outcome:filters.outcome,page:filters.page,limit:25}),[filters.firmware,filters.lab,filters.profile,filters.status,filters.outcome,filters.page],{refreshMs:10000});
 const mutation=useMutation(),canLaunch=["OWNER","ADMIN","OPERATOR"].includes(user.role);
 const statusOptions=useMemo(()=>["","QUEUED","PREPARING","LAB_HEALTH_CHECK","RUNNING","FINALIZING","COMPLETED","FAILED","LAB_FAILED","CANCELLED","ABORTED"],[]);
 const apply=event=>{event.preventDefault();setFilters(current=>({...current,page:1}));};
 const clearFilters=()=>setFilters({firmware:"",lab:"",profile:"",status:"",outcome:"",page:1});
 const activeFilterCount=[filters.firmware,filters.lab,filters.profile,filters.status,filters.outcome].filter(Boolean).length;
 const startRun=async event=>{event.preventDefault();try{await mutation.run(()=>api.launch({firmware_version:form.firmware_version.trim()||"v1.0",tests:form.tests.split(",").map(item=>item.trim()).filter(Boolean)}));setShowLaunch(false);await loader.reload();}catch{}};
 if(loader.loading&&!loader.data)return <LoadingState label="Loading Run history…"/>;
 if(loader.error&&!loader.data)return <ErrorState error={loader.error} onRetry={loader.reload}/>;
 const data=loader.data;
 return <div className="page-stack">
  <div className="page-title-row"><div><div className="eyebrow">Operate / Execution history</div><h2>Runs</h2><p className="muted">Filter persisted executions and follow each result back to its evidence and validation outcome.</p></div>{canLaunch?<Button onClick={()=>setShowLaunch(true)}><Play size={15} aria-hidden="true"/>Start Run</Button>:null}</div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">The Runner accepted the Run request. Refreshing persisted history.</InlineNotice>:null}
  <Section title="Filter history" subtitle="Filters are applied by the Runner API." actions={<span className="filter-count">{activeFilterCount} active</span>}>
   <form className="filter-grid" onSubmit={apply}>
    <Field label="Firmware"><input value={filters.firmware} onChange={e=>setFilters({...filters,firmware:e.target.value,page:1})} placeholder="e.g. v1.0"/></Field>
    <Field label="Lab"><input value={filters.lab} onChange={e=>setFilters({...filters,lab:e.target.value,page:1})} placeholder="Lab ID"/></Field>
    <Field label="Profile"><input value={filters.profile} onChange={e=>setFilters({...filters,profile:e.target.value,page:1})} placeholder="Validation profile"/></Field>
    <Field label="Lifecycle status"><select value={filters.status} onChange={e=>setFilters({...filters,status:e.target.value,page:1})}>{statusOptions.map(value=><option key={value} value={value}>{value||"All statuses"}</option>)}</select></Field>
    <Field label="Business outcome"><select value={filters.outcome} onChange={e=>setFilters({...filters,outcome:e.target.value,page:1})}><option value="">All outcomes</option><option>VALIDATED</option><option>VALIDATED_WITH_WARNINGS</option><option>REJECTED</option><option>UNVALIDATED</option></select></Field>
    <div className="filter-actions"><Button type="submit"><Filter size={14}/>Apply filters</Button><Button type="button" variant="outline" onClick={clearFilters}><RotateCcw size={14}/>Reset</Button></div>
   </form>
  </Section>
  <Section title="Persisted Run history" subtitle={data?.total===undefined?"Results from the canonical Runner API":data.total+" total Run"+(data.total===1?"":"s")} actions={<Button variant="ghost" size="sm" onClick={()=>loader.reload().catch(()=>{})}><Search size={14}/>Refresh results</Button>}>
   <DataTable caption="Persisted Run history" rows={data?.items||[]} rowKey={row=>row.run_id} onRowClick={row=>navigate("/runs/"+encodeURIComponent(row.run_id))} columns={[
    {key:"display_id",label:"Run",width:"220px",render:row=><div className="run-table-identity"><strong>{row.display_id||row.run_id}</strong><span className="muted mono">{row.run_id}</span></div>},
    {key:"firmware_version",label:"Firmware"},{key:"device_id",label:"Device"},{key:"lab_id",label:"Lab"},{key:"validation_profile",label:"Profile"},
    {key:"lifecycle_status",label:"Lifecycle",render:row=><StatusBadge value={row.lifecycle_status}/>},
    {key:"business_outcome",label:"Outcome",render:row=><StatusBadge value={row.business_outcome}/>},
    {key:"created_at",label:"Created",render:row=>formatDate(row.created_at)}
   ]} emptyTitle="No matching Runs" emptyMessage={activeFilterCount?"Try clearing one or more filters.":"No Runs have been persisted yet."}/>
   <Pagination page={data?.page||1} pages={data?.pages||1} onChange={page=>setFilters({...filters,page})}/>
  </Section>
  {showLaunch?<div className="dialog-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget&&!mutation.loading)setShowLaunch(false);}}><div className="dialog wide" role="dialog" aria-modal="true" aria-labelledby="launch-title" aria-describedby="launch-description">
   <div className="dialog-icon"><Play size={18}/></div><h2 id="launch-title">Start validation Run</h2><p id="launch-description" className="muted">The Runner validates authorization, configuration and idempotency. This form submits the requested execution scope.</p>
   <form className="form-stack" onSubmit={startRun}>
    <Field label="Firmware version" required><input value={form.firmware_version} onChange={e=>setForm({...form,firmware_version:e.target.value})} required/></Field>
    <Field label="Tests" hint="Optional comma-separated TestRegistry IDs. Leave blank to use the configured default selection."><input value={form.tests} onChange={e=>setForm({...form,tests:e.target.value})} placeholder="wifi.latency.threshold, …"/></Field>
    {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:null}
    <div className="dialog-actions"><Button type="button" variant="outline" onClick={()=>setShowLaunch(false)} disabled={mutation.loading}>Close</Button><Button type="submit" loading={mutation.loading}><Play size={14}/>Start Run</Button></div>
   </form>
  </div></div>:null}
 </div>;
}
