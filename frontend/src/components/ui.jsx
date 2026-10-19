import React from "react";
import {
  AlertCircle, AlertTriangle, CheckCircle2, CircleDot, Download, FileSearch,
  Loader2, RefreshCw,
} from "lucide-react";
import {classifyTone,formatDate,formatBytes,formatNumber,humanizeStatus,metricMean,toFiniteNumber,validSamples} from "../utils";

const statusIcons = {
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: AlertCircle,
  info: CircleDot,
  neutral: CircleDot,
};

export function StatusBadge({value, className = ""}) {
  if (value === null || value === undefined || value === "") {
    return <span className={("badge neutral " + className).trim()}>Not recorded</span>;
  }
  const tone = classifyTone(value);
  const Icon = statusIcons[tone] || CircleDot;
  return <span className={("badge " + tone + " " + className).trim()}>
    <Icon size={12} strokeWidth={2.2} aria-hidden="true" />
    {humanizeStatus(value)}
  </span>;
}

export function Button({children,variant="primary",size="default",loading=false,disabled=false,className="",type="button",...props}) {
  const variantClass = ({default:"primary",primary:"primary",destructive:"danger",danger:"danger",secondary:"secondary",outline:"outline",ghost:"ghost",link:"link"})[variant] || "primary";
  const sizeClass = ({default:"",sm:" button-sm",lg:" button-lg",icon:" button-icon"})[size] ?? "";
  return <button
    type={type}
    className={("button " + variantClass + sizeClass + (loading?" is-loading":"") + " " + className).trim()}
    disabled={disabled || loading}
    aria-busy={loading || undefined}
    {...props}
  >
    {loading ? <Loader2 className="button-spinner" size={16} aria-hidden="true" /> : null}
    {children}
  </button>;
}

export function IconButton({label,children,className="",variant="ghost",...props}) {
  return <Button variant={variant} size="icon" className={className} aria-label={label} title={label} {...props}>{children}</Button>;
}

export function StatCard({label,value,hint,icon,footnote,tone="default"}) {
  return <article className={"stat-card " + tone}>
    <div className="stat-topline">
      <div className="stat-label">{label}</div>
      {icon ? <span className="stat-icon" aria-hidden="true">{icon}</span> : null}
    </div>
    <div className="stat-value">{value ?? "—"}</div>
    {hint ? <div className="stat-hint">{hint}</div> : null}
    {footnote ? <div className="stat-footnote">{footnote}</div> : null}
  </article>;
}

export function Section({title,subtitle,actions,children,className=""}) {
  return <section className={("panel " + className).trim()}>
    {(title || subtitle || actions) ? <div className="panel-heading">
      <div className="panel-heading-copy">
        {title ? <h2>{title}</h2> : null}
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="panel-actions">{actions}</div> : null}
    </div> : null}
    {children}
  </section>;
}

export function LoadingState({label="Loading data…"}) {
  return <div className="state-card loading-state" role="status" aria-live="polite">
    <Loader2 className="state-icon spin" size={19} aria-hidden="true" />
    <span>{label}</span>
  </div>;
}

export function EmptyState({title="Nothing to show",message="No records match the current view.",action,icon}) {
  const Icon = icon || FileSearch;
  return <div className="state-card empty">
    <span className="state-icon" aria-hidden="true"><Icon size={21}/></span>
    <strong>{title}</strong>
    <span>{message}</span>
    {action ? <div className="empty-action">{action}</div> : null}
  </div>;
}

export function ErrorState({error,onRetry,title="Unable to load this view"}) {
  return <div className="state-card error-state" role="alert">
    <span className="state-icon danger" aria-hidden="true"><AlertTriangle size={20}/></span>
    <strong>{title}</strong>
    <span>{error?.message || "An unexpected error occurred."}</span>
    {onRetry ? <Button variant="outline" onClick={onRetry}><RefreshCw size={14} aria-hidden="true"/> Retry</Button> : null}
  </div>;
}

export function InlineNotice({tone="info",children}) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "warning" ? AlertTriangle : tone === "danger" ? AlertCircle : CircleDot;
  return <div className={"notice " + tone} role={tone==="danger"?"alert":"status"}>
    <Icon size={16} aria-hidden="true" className="notice-icon"/>
    <div className="notice-content">{children}</div>
  </div>;
}

export function OutcomeBreakdown({items=[]}) {
  const count = (outcome) => items.filter((row) => String(row?.business_outcome || "").toUpperCase() === outcome).length;
  const buckets = [
    {key:"VALIDATED",label:"Validated",value:count("VALIDATED"),tone:"success"},
    {key:"VALIDATED_WITH_WARNINGS",label:"Validated with warnings",value:count("VALIDATED_WITH_WARNINGS"),tone:"warning"},
    {key:"REJECTED",label:"Rejected",value:count("REJECTED"),tone:"danger"},
    {key:"UNVALIDATED",label:"Unvalidated",value:count("UNVALIDATED"),tone:"neutral"},
    {key:"NO_OUTCOME",label:"No final outcome",value:items.length-count("VALIDATED")-count("VALIDATED_WITH_WARNINGS")-count("REJECTED")-count("UNVALIDATED"),tone:"muted"},
  ];
  const denominator = items.length;
  return <div className="outcome-breakdown">
    <div className="outcome-total"><strong>{denominator}</strong><span>recent Runs included</span></div>
    <div className="outcome-bars" role="list" aria-label="Business outcome distribution for visible Runs">
      {buckets.map((bucket) => {
        const percent = denominator ? (bucket.value / denominator) * 100 : 0;
        return <div className="outcome-row" role="listitem" key={bucket.key}>
          <div className="outcome-row-meta">
            <span className={"outcome-dot " + bucket.tone} aria-hidden="true"/>
            <span className="outcome-label">{bucket.label}</span>
            <strong>{bucket.value}</strong>
            <span className="outcome-percent">{denominator ? Math.round(percent) + "%" : "—"}</span>
          </div>
          <div className="progress-track" role="progressbar" aria-label={bucket.label} aria-valuemin={0} aria-valuemax={denominator} aria-valuenow={bucket.value}>
            <span className={"progress-fill " + bucket.tone} style={{width: percent + "%"}}/>
          </div>
        </div>;
      })}
    </div>
  </div>;
}

export function ConfirmDialog({open,title,message,confirmLabel="Confirm",danger=false,onCancel,onConfirm,loading=false}) {
  if(!open)return null;
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event)=>{if(event.target===event.currentTarget&&!loading)onCancel?.();}}>
    <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" aria-describedby="dialog-message">
      <h2 id="dialog-title">{title}</h2>
      <p id="dialog-message">{message}</p>
      <div className="dialog-actions">
        <Button variant="outline" onClick={onCancel} disabled={loading}>Cancel</Button>
        <Button variant={danger?"danger":"primary"} onClick={onConfirm} loading={loading}>{confirmLabel}</Button>
      </div>
    </div>
  </div>;
}

export function KeyValueGrid({items}) {
  return <dl className="key-grid">{items.map(item=><div className="key-item" key={item.label}>
    <dt>{item.label}</dt><dd>{item.value ?? "—"}</dd>
  </div>)}</dl>;
}

export function DataTable({columns,rows=[],rowKey,emptyTitle,emptyMessage,onRowClick,caption,className=""}) {
  const data = Array.isArray(rows) ? rows : [];
  if(!data.length)return <EmptyState title={emptyTitle} message={emptyMessage}/>;
  return <div className={"table-wrap " + className}>
    <table aria-label={caption || "Data table"}>
      {caption ? <caption className="sr-only">{caption}</caption> : null}
      <thead><tr>{columns.map(column=><th key={column.key} scope="col" className={column.align==="right"?"numeric":""} style={column.width?{width:column.width}:undefined}>{column.label}</th>)}</tr></thead>
      <tbody>{data.map((row,index)=><tr
        key={rowKey?rowKey(row,index):(row?.id||index)}
        className={onRowClick?"clickable-row":""}
        tabIndex={onRowClick?0:undefined}
        aria-label={onRowClick?("Open "+String(row?.display_id||row?.test_id||row?.run_id||"record")):undefined}
        onClick={onRowClick?()=>onRowClick(row):undefined}
        onKeyDown={onRowClick?event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();onRowClick(row);}}:undefined}
      >{columns.map(column=><td key={column.key} className={[column.align==="right"?"numeric":"",column.className||""].filter(Boolean).join(" ")}>{column.render?column.render(row):row?.[column.key] ?? "—"}</td>)}</tr>)}</tbody>
    </table>
  </div>;
}

export function Pagination({page,pages,onChange}) {
  if(!pages||pages<=1)return null;
  return <nav className="pagination" aria-label="Table pagination">
    <Button variant="outline" size="sm" disabled={page<=1} onClick={()=>onChange(page-1)}>Previous</Button>
    <span>Page <strong>{page}</strong> of <strong>{pages}</strong></span>
    <Button variant="outline" size="sm" disabled={page>=pages} onClick={()=>onChange(page+1)}>Next</Button>
  </nav>;
}

export function JsonPanel({value}) {
  return <details className="json-details">
    <summary>Inspect raw JSON</summary>
    <pre className="json-panel">{JSON.stringify(value??{},null,2)}</pre>
  </details>;
}

export function MetricSampleTable({metric}) {
  const samples = Array.isArray(metric?.samples) ? metric.samples : [];
  if(!samples.length)return <EmptyState title="No samples" message="The metric has no recorded samples."/>;
  const validCount = validSamples(samples).length;
  const average = metricMean(metric);
  return <div className="metric-sample-table">
    <div className="metric-summary-strip">
      <span><strong>{validCount}</strong> valid measurement{validCount===1?"":"s"}</span>
      <span>Mean of valid, non-warm-up samples: <strong>{average===null?"—":formatNumber(average)+" "+(metric?.unit||"")}</strong></span>
      {metric?.authoritative===false?<span className="muted">Context only · not release-authoritative</span>:null}
    </div>
    <div className="table-wrap"><table aria-label={"Raw samples for "+(metric?.name||"metric")}>
      <thead><tr><th scope="col">Value</th><th scope="col">Status</th><th scope="col">Warm-up</th><th scope="col">Retried</th><th scope="col">Captured</th></tr></thead>
      <tbody>{samples.map((sample,index)=><tr key={sample.sample_id||index} className={sample.warmup?"sample-warmup":""}>
        <td className="numeric">{toFiniteNumber(sample.value)===null?"—":formatNumber(sample.value)+" "+(metric?.unit||"")}</td>
        <td><StatusBadge value={sample.status}/></td>
        <td>{sample.warmup?"Yes":"No"}</td>
        <td>{sample.retried?"Yes":"No"}</td>
        <td>{formatDate(sample.captured_at)}</td>
      </tr>)}</tbody>
    </table></div>
  </div>;
}

export function LineChart({title,points=[],valueLabel="",maxPoints=60}) {
  const usable = (Array.isArray(points)?points:[])
    .map((point) => ({...point, numericValue:toFiniteNumber(point?.value)}))
    .filter((point) => point.numericValue!==null)
    .slice(-maxPoints);
  if(!usable.length)return <EmptyState title={"No "+title} message="The selected data contains no valid numeric measurements."/>;
  const width=820,height=276,padLeft=58,padRight=18,padTop=28,padBottom=38;
  const values=usable.map(point=>point.numericValue);
  const dataMin=Math.min(...values),dataMax=Math.max(...values);
  const spread=dataMax-dataMin;
  const padding=spread===0?Math.max(Math.abs(dataMax)*0.08,1):spread*0.12;
  const min=dataMin-padding,max=dataMax+padding;
  const range=max-min||1,plotWidth=width-padLeft-padRight,plotHeight=height-padTop-padBottom;
  const coords=usable.map((point,index)=>({
    ...point,
    x:padLeft+(index*plotWidth)/Math.max(1,usable.length-1),
    y:padTop+plotHeight-((point.numericValue-min)/range)*plotHeight,
  }));
  const path=coords.map((point,index)=>(index?"L":"M")+" "+point.x.toFixed(2)+" "+point.y.toFixed(2)).join(" ");
  const gridLines=[0,1,2,3,4].map(index=>{
    const ratio=index/4;
    return {y:padTop+ratio*plotHeight,value:max-ratio*range};
  });
  const average=values.reduce((sum,value)=>sum+value,0)/values.length;
  return <div className="chart-card">
    <div className="chart-header"><div><div className="chart-title">{title}</div><div className="muted chart-caption">{usable.length} plotted point{usable.length===1?"":"s"} · {valueLabel||"unit not recorded"}</div></div>
      <div className="chart-current"><span>Mean</span><strong>{formatNumber(average)} <small>{valueLabel}</small></strong></div>
    </div>
    <svg viewBox={"0 0 "+width+" "+height} role="img" aria-label={title+" line chart"}>
      <desc>Numeric measurements plotted in supplied order. Minimum {formatNumber(dataMin)} and maximum {formatNumber(dataMax)} {valueLabel}.</desc>
      {gridLines.map((line,index)=><g key={index}><line x1={padLeft} y1={line.y} x2={width-padRight} y2={line.y} className="chart-grid"/><text x={padLeft-10} y={line.y+4} textAnchor="end" className="chart-axis-label">{formatNumber(line.value)}</text></g>)}
      <line x1={padLeft} y1={padTop+plotHeight} x2={width-padRight} y2={padTop+plotHeight} className="axis"/>
      {usable.length>1?<path d={path} className="chart-line" fill="none"/>:null}
      {coords.map((point,index)=><circle key={(point.run_id||point.captured_at||"point")+"-"+index} cx={point.x} cy={point.y} r="4" className="chart-dot"><title>{(point.label||"Point "+(index+1))+": "+formatNumber(point.numericValue)+" "+valueLabel}</title></circle>)}
      <text x={padLeft} y={height-9} className="chart-axis-label">{usable[0]?.label||"First sample"}</text>
      {usable.length>1?<text x={width-padRight} y={height-9} textAnchor="end" className="chart-axis-label">{usable[usable.length-1]?.label||"Latest sample"}</text>:null}
    </svg>
    <div className="chart-table-wrap"><table aria-label={title+" plotted values"}>
      <thead><tr><th scope="col">Observation</th><th scope="col" className="numeric">Value</th></tr></thead>
      <tbody>{usable.map((point,index)=><tr key={(point.run_id||point.captured_at||"point")+"-"+index}><td>{point.label||"Observation "+(index+1)}</td><td className="numeric">{formatNumber(point.numericValue)} {valueLabel}</td></tr>)}</tbody>
    </table></div>
  </div>;
}

export function ArtifactLink({artifact}) {
  if(!artifact)return null;
  if(!artifact.downloadable)return <span className="muted">Unavailable</span>;
  return <a className="text-link inline-action" href={"/api/v1/artifacts/"+encodeURIComponent(artifact.artifact_id)+"/download"} target="_blank" rel="noreferrer"><Download size={13} aria-hidden="true"/>Download</a>;
}

export function Field({label,children,hint,required=false}) {
  return <label className="field">
    <span>{label}{required?<span className="field-required" aria-label="required"> *</span>:null}</span>
    {children}
    {hint?<small>{hint}</small>:null}
  </label>;
}

export function formatArtifact(artifact) {
  return (artifact?.display_name||"Artifact")+" · "+(artifact?.artifact_type||"unknown")+" · "+formatBytes(artifact?.size_bytes);
}
