import React,{useId} from "react";
import {AlertCircle,AlertTriangle,ArrowDown,ArrowUp,CheckCircle2,CircleDot,Download,FileSearch,Loader2,RefreshCw,ShieldAlert} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import {Card,CardContent,CardDescription,CardHeader,CardTitle} from "@/components/ui/card";
import {Dialog,DialogContent,DialogDescription,DialogFooter,DialogHeader,DialogTitle} from "@/components/ui/dialog";
import {Table,TableBody,TableCell,TableHead,TableHeader,TableRow} from "@/components/ui/table";
import {classifyTone,formatBytes,formatDate,formatNumber,humanizeStatus,metricMean,toFiniteNumber,validSamples} from "@/utils";

export {Button,Card,CardContent,CardDescription,CardHeader,CardTitle};
const statusVariant={success:"success",warning:"warning",danger:"destructive",info:"info",neutral:"secondary"};
const statusIcon={success:CheckCircle2,warning:AlertTriangle,danger:AlertCircle,info:CircleDot,neutral:CircleDot};

export function StatusBadge({value,className=""}){
 if(value===null||value===undefined||value==="")return <Badge variant="secondary" className={className}>Not recorded</Badge>;
 const tone=classifyTone(value),Icon=statusIcon[tone]||CircleDot;
 return <Badge variant={statusVariant[tone]||"secondary"} className={className}><Icon size={12} aria-hidden="true"/>{humanizeStatus(value)}</Badge>;
}
export function StatCard({label,value,hint,icon,footnote,tone="default"}){
 return <Card className={"stat-card "+tone}><CardContent className="stat-card-content">
  <div className="stat-topline"><span className="stat-label">{label}</span>{icon?<span className="stat-icon" aria-hidden="true">{icon}</span>:null}</div>
  <div className="stat-value">{value??"—"}</div>{hint?<p className="stat-hint">{hint}</p>:null}{footnote?<span className="stat-footnote">{footnote}</span>:null}
 </CardContent></Card>;
}
export function Section({title,subtitle,actions,children,className="",contentClassName=""}){
 return <Card className={"panel "+className}>{(title||subtitle||actions)?<CardHeader className="panel-heading"><div className="panel-heading-copy">{title?<CardTitle>{title}</CardTitle>:null}{subtitle?<CardDescription>{subtitle}</CardDescription>:null}</div>{actions?<div className="panel-actions">{actions}</div>:null}</CardHeader>:null}<CardContent className={"panel-content "+contentClassName}>{children}</CardContent></Card>;
}
export function PageHeader({eyebrow,title,description,actions,icon:Icon}){
 return <header className="page-header"><div className="page-header-copy">{eyebrow?<div className="eyebrow">{eyebrow}</div>:null}<div className="page-heading-line">{Icon?<span className="page-heading-icon"><Icon size={18}/></span>:null}<h2>{title}</h2></div>{description?<p>{description}</p>:null}</div>{actions?<div className="page-header-actions">{actions}</div>:null}</header>;
}
export function LoadingState({label="Loading data…"}){return <div className="state-card loading-state" role="status" aria-live="polite"><Loader2 className="spin" size={18}/><span>{label}</span></div>;}
export function EmptyState({title="Nothing to show",message="No records match the current view.",action,icon:Icon=FileSearch}){return <div className="state-card empty-state"><span className="state-icon"><Icon size={20}/></span><strong>{title}</strong><p>{message}</p>{action?<div className="empty-action">{action}</div>:null}</div>;}
export function ErrorState({error,onRetry,title="Unable to load this view"}){return <div className="state-card error-state" role="alert"><span className="state-icon danger"><ShieldAlert size={20}/></span><strong>{title}</strong><p>{error?.message||"An unexpected error occurred."}</p>{onRetry?<Button variant="outline" onClick={()=>{Promise.resolve(onRetry()).catch(()=>{});}}><RefreshCw size={14}/>Try again</Button>:null}</div>;}
export function InlineNotice({tone="info",children}){const Icon=tone==="success"?CheckCircle2:tone==="warning"?AlertTriangle:tone==="danger"?AlertCircle:CircleDot;return <div className={"notice "+tone} role={tone==="danger"?"alert":"status"}><Icon className="notice-icon" size={16}/><div className="notice-content">{children}</div></div>;}
export function OutcomeBreakdown({items=[]}){
 const count=key=>items.filter(row=>String(row?.business_outcome||"").toUpperCase()===key).length;
 const known=["VALIDATED","VALIDATED_WITH_WARNINGS","REJECTED","UNVALIDATED"].reduce((sum,key)=>sum+count(key),0);
 const buckets=[{key:"VALIDATED",label:"Validated",value:count("VALIDATED"),tone:"success"},{key:"VALIDATED_WITH_WARNINGS",label:"Validated with warnings",value:count("VALIDATED_WITH_WARNINGS"),tone:"warning"},{key:"REJECTED",label:"Rejected",value:count("REJECTED"),tone:"danger"},{key:"UNVALIDATED",label:"Unvalidated",value:count("UNVALIDATED"),tone:"muted"},{key:"UNCLASSIFIED",label:"Unclassified / no business outcome",value:Math.max(0,items.length-known),tone:"neutral"}];
 return <div className="outcome-breakdown"><div className="outcome-total"><strong>{items.length}</strong><span>recent Runs included</span></div>{items.length?<div className="outcome-bars" role="list" aria-label="Business outcome distribution">{buckets.map(item=>{const percent=items.length?item.value/items.length*100:0;return <div className="outcome-row" role="listitem" key={item.key}><div className="outcome-row-meta"><span className={"outcome-dot "+item.tone}/><span className="outcome-label">{item.label}</span><strong>{item.value}</strong><span className="outcome-percent">{Math.round(percent)}%</span></div><div className="progress-track" role="progressbar" aria-label={item.label} aria-valuemin={0} aria-valuemax={items.length} aria-valuenow={item.value}><span className={"progress-fill "+item.tone+" progress-width-"+Math.round(percent)}/></div></div>;})}</div>:<EmptyState title="No Runs to classify" message="Persisted business outcomes will appear here after validation Runs are recorded."/>}</div>;
}
export function ConfirmDialog({open,title,message,confirmLabel="Confirm",danger=false,onCancel,onConfirm,loading=false}){
 return <Dialog open={open} onOpenChange={value=>{if(!value&&!loading)onCancel?.();}}><DialogContent><DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{message}</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={onCancel} disabled={loading}>Cancel</Button><Button variant={danger?"destructive":"default"} onClick={onConfirm} loading={loading}>{confirmLabel}</Button></DialogFooter></DialogContent></Dialog>;
}
export function KeyValueGrid({items=[]}){return <dl className="key-grid">{items.map(item=><div className="key-item" key={item.label}><dt>{item.label}</dt><dd>{item.value??"Not recorded"}</dd></div>)}</dl>;}
export function DataTable({columns=[],rows=[],rowKey,onRowClick,caption="Data table",emptyTitle,emptyMessage}){
 const data=Array.isArray(rows)?rows:[];
 if(!data.length)return <EmptyState title={emptyTitle||"No records"} message={emptyMessage||"There are no records to display."}/>;
 return <div className="table-wrap"><Table aria-label={caption}><TableHeader><TableRow>{columns.map(column=><TableHead key={column.key} className={column.align==="right"?"numeric":""}>{column.label}</TableHead>)}</TableRow></TableHeader><TableBody>{data.map((row,index)=><TableRow key={rowKey?rowKey(row,index):(row?.id||index)} className={onRowClick?"clickable-row":""} tabIndex={onRowClick?0:undefined} aria-label={onRowClick?"Open "+String(row?.display_id||row?.test_id||row?.run_id||"record"):undefined} onClick={onRowClick?()=>onRowClick(row):undefined} onKeyDown={onRowClick?event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();onRowClick(row);}}:undefined}>{columns.map(column=><TableCell key={column.key} className={[column.align==="right"?"numeric":"",column.className||""].filter(Boolean).join(" ")}>{column.render?column.render(row):row?.[column.key]??"—"}</TableCell>)}</TableRow>)}</TableBody></Table></div>;
}
export function Pagination({page,pages,onChange}){
 if(!pages||pages<=1)return null;
 return <nav className="pagination" aria-label="Pagination"><Button variant="outline" size="sm" disabled={page<=1} onClick={()=>onChange(page-1)}>Previous</Button><span>Page <strong>{page}</strong> of <strong>{pages}</strong></span><Button variant="outline" size="sm" disabled={page>=pages} onClick={()=>onChange(page+1)}>Next</Button></nav>;
}
export function JsonPanel({value}){return <details className="json-details"><summary>Inspect raw JSON</summary><pre className="json-panel">{JSON.stringify(value??{},null,2)}</pre></details>;}
export function MetricSampleTable({metric}){
 const samples=Array.isArray(metric?.samples)?metric.samples:[];
 if(!samples.length)return <EmptyState title="No samples" message="The metric has no recorded samples."/>;
 const eligible=validSamples(samples),average=metricMean(metric),policy=metric?.measurement_policy;
 const aggregate=policy?.aggregate?String(policy.aggregate).toUpperCase():"DESCRIPTIVE MEAN";
 const eligibleCount=policy?.eligible_samples??eligible.length,ready=policy?.status==="READY";
 return <div className="metric-sample-table"><div className="metric-summary-strip"><span><strong>{eligibleCount}</strong> eligible measurement{eligibleCount===1?"":"s"}{policy?.minimum_samples?" · "+policy.minimum_samples+" required":""}</span><span>{aggregate} decision value: <strong>{ready?formatNumber(policy.decision_value)+" "+(metric?.unit||""):"Not available"}</strong></span>{policy?.error?<span className="muted">{policy.error}</span>:!policy?<span className="muted">No registry policy · descriptive mean: {average===null?"—":formatNumber(average)+" "+(metric?.unit||"")}</span>:null}{metric?.authoritative===false||policy?.authoritative===false?<span className="muted">Context only · not release-authoritative</span>:null}</div><div className="table-wrap"><Table aria-label={"Raw samples for "+(metric?.name||"metric")}><TableHeader><TableRow><TableHead>Value</TableHead><TableHead>Status</TableHead><TableHead>Warm-up</TableHead><TableHead>Retried</TableHead><TableHead>Captured</TableHead></TableRow></TableHeader><TableBody>{samples.map((sample,index)=><TableRow key={sample.sample_id||index} className={sample.warmup?"sample-warmup":""}><TableCell className="numeric">{toFiniteNumber(sample.value)===null?"—":formatNumber(sample.value)+" "+(metric?.unit||"")}</TableCell><TableCell><StatusBadge value={sample.status}/></TableCell><TableCell>{sample.warmup?"Yes":"No"}</TableCell><TableCell>{sample.retried?"Yes":"No"}</TableCell><TableCell>{formatDate(sample.captured_at)}</TableCell></TableRow>)}</TableBody></Table></div></div>;
}
export function LineChart({title,points=[],valueLabel="",maxPoints=60}){
 const usable=(Array.isArray(points)?points:[]).map(point=>({...point,numericValue:toFiniteNumber(point?.value)})).filter(point=>point.numericValue!==null).slice(-maxPoints);
 if(!usable.length)return <EmptyState title={"No "+title} message="The selected data contains no valid numeric measurements."/>;
 const width=820,height=280,left=62,right=18,top=25,bottom=42,values=usable.map(point=>point.numericValue),minValue=Math.min(...values),maxValue=Math.max(...values),spread=maxValue-minValue,padding=spread===0?Math.max(Math.abs(maxValue)*.08,1):spread*.12,min=minValue-padding,max=maxValue+padding,range=max-min||1,plotWidth=width-left-right,plotHeight=height-top-bottom;
 const coordinates=usable.map((point,index)=>({...point,x:left+index*plotWidth/Math.max(1,usable.length-1),y:top+plotHeight-(point.numericValue-min)/range*plotHeight}));
 const path=coordinates.map((point,index)=>(index?"L":"M")+point.x.toFixed(2)+" "+point.y.toFixed(2)).join(" "),mean=values.reduce((sum,value)=>sum+value,0)/values.length,lines=[0,1,2,3,4].map(index=>({y:top+index*plotHeight/4,value:max-index*range/4}));
 return <div className="chart-card"><div className="chart-header"><div><h3>{title}</h3><p>{usable.length} numeric observation{usable.length===1?"":"s"} · {valueLabel||"unit not recorded"}</p></div><div className="chart-current"><span>Mean</span><strong>{formatNumber(mean)} <small>{valueLabel}</small></strong></div></div>
 <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title+" line chart"}><desc>Values are plotted in supplied order. Minimum {formatNumber(minValue)} and maximum {formatNumber(maxValue)} {valueLabel}.</desc>{lines.map((line,index)=><g key={index}><line x1={left} y1={line.y} x2={width-right} y2={line.y} className="chart-grid"/><text x={left-10} y={line.y+4} textAnchor="end" className="chart-axis-label">{formatNumber(line.value)}</text></g>)}{usable.length>1?<path d={path} className="chart-line" fill="none"/>:null}{coordinates.map((point,index)=><circle key={(point.run_id||point.captured_at||"point")+"-"+index} cx={point.x} cy={point.y} r="4" className="chart-dot"><title>{(point.label||"Observation "+(index+1))+": "+formatNumber(point.numericValue)+" "+valueLabel}</title></circle>)}<text x={left} y={height-10} className="chart-axis-label">{usable[0]?.label||"First observation"}</text>{usable.length>1?<text x={width-right} y={height-10} textAnchor="end" className="chart-axis-label">{usable[usable.length-1]?.label||"Latest observation"}</text>:null}</svg>
 <div className="chart-table-wrap"><Table aria-label={title+" plotted values"}><TableHeader><TableRow><TableHead>Observation</TableHead><TableHead className="numeric">Value</TableHead></TableRow></TableHeader><TableBody>{usable.map((point,index)=><TableRow key={(point.run_id||point.captured_at||"point")+"-"+index}><TableCell>{point.label||"Observation "+(index+1)}</TableCell><TableCell className="numeric">{formatNumber(point.numericValue)} {valueLabel}</TableCell></TableRow>)}</TableBody></Table></div></div>;
}
export function ArtifactLink({artifact}){if(!artifact)return null;if(!artifact.downloadable)return <span className="text-muted">Unavailable</span>;return <a className="text-link" href={"/api/v1/artifacts/"+encodeURIComponent(artifact.artifact_id)+"/download"} target="_blank" rel="noreferrer"><Download size={13}/>Download</a>;}
function bindFieldControl(node,id){
 if(!React.isValidElement(node))return node;
 if(typeof node.type==="string"&&["input","select","textarea"].includes(node.type)){
  return React.cloneElement(node,{id:node.props.id||id});
 }
 if(node.props?.children!==undefined){
  return React.cloneElement(node,undefined,React.Children.map(node.props.children,child=>bindFieldControl(child,id)));
 }
 return node;
}
export function Field({label,children,hint,required=false,className=""}){
 const controlId=useId();
 const controls=React.Children.map(children,child=>bindFieldControl(child,controlId));
 return <div className={"field "+className}>
  <label className={"field-label"+(required?" is-required":"")} htmlFor={controlId}>{label}</label>
  {controls}
  {hint?<small>{hint}</small>:null}
 </div>;
}
export function formatArtifact(artifact){return (artifact?.display_name||"Artifact")+" · "+(artifact?.artifact_type||"unknown")+" · "+formatBytes(artifact?.size_bytes);}
