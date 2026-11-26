import React,{useEffect,useMemo,useState} from "react";
import {layoutPipelineGraph,normalizePipelineSteps} from "@/pipeline-graph";
import {Button,Field,InlineNotice} from "@/components/ui";

const STEP_TYPES=[
 "WIFI_LAB_PROVISION","TOPOLOGY_APPLY","PROVIDER_RECONCILE",
 "CONFIGURATION_DEPLOY","VALIDATION_RUN"
];
const OUTCOMES=["SUCCESS","FAILURE","COMPLETED"];
const DEFAULT_INPUTS={
 WIFI_LAB_PROVISION:{confirmed:true},
 TOPOLOGY_APPLY:{profile_id:"",revision_id:"",expected_sha256:"",confirmed:true},
 PROVIDER_RECONCILE:{profile_id:"",revision_id:""},
 CONFIGURATION_DEPLOY:{profile_id:"",revision_id:"",configuration_hash:"",device_id:"",ssh_credential_id:"",wifi_psk_credential_id:"",confirmed:true},
 VALIDATION_RUN:{tests:["wifi.latency.threshold"],firmware_version:"v1.0"}
};

function uniqueKey(steps){
 let number=steps.length+1,key="step_"+number;
 while(steps.some(item=>item.key===key)){number+=1;key="step_"+number;}
 return key;
}

export default function PipelineGraphEditor({value,onChange}){
 const steps=useMemo(()=>normalizePipelineSteps(value?.steps||[]),[value]);
 const [selectedKey,setSelectedKey]=useState(steps[0]?.key||"");
 const [inputText,setInputText]=useState("{}");
 const [inputError,setInputError]=useState("");
 const selected=steps.find(item=>item.key===selectedKey)||steps[0]||null;
 const graph=useMemo(()=>layoutPipelineGraph(steps),[steps]);

 useEffect(()=>{
  if(selected?.key&&selected.key!==selectedKey)setSelectedKey(selected.key);
  if(!selected&&selectedKey)setSelectedKey("");
 },[selected?.key,selectedKey]);
 useEffect(()=>{
  setInputText(JSON.stringify(selected?.input||{},null,2));
  setInputError("");
 },[selected?.key,JSON.stringify(selected?.input||{})]);

 function update(next){
  onChange({steps:next});
 }
 function updateStep(key,patch){
  update(steps.map(item=>item.key===key?{...item,...patch}:item));
 }
 function addStep(){
  if(steps.length>=32)return;
  const key=uniqueKey(steps);
  const previous=steps[steps.length-1];
  const type="VALIDATION_RUN";
  const next=[...steps,{
   key,type,name:"Run validation tests",timeout_seconds:900,max_attempts:1,
   input:{...DEFAULT_INPUTS[type]},
   depends_on:previous?[{step_key:previous.key,outcome:"SUCCESS"}]:[]
  }];
  update(next);setSelectedKey(key);
 }
 function removeStep(){
  if(!selected||steps.length<=1)return;
  const next=steps.filter(item=>item.key!==selected.key).map(item=>({
   ...item,depends_on:(item.depends_on||[]).filter(dep=>dep.step_key!==selected.key)
  }));
  update(next);setSelectedKey(next[0]?.key||"");
 }
 function changeType(type){
  updateStep(selected.key,{type,input:{...DEFAULT_INPUTS[type]}});
  setInputText(JSON.stringify(DEFAULT_INPUTS[type],null,2));setInputError("");
 }
 function toggleDependency(parentKey,checked){
  const current=selected.depends_on||[];
  const next=checked
   ? [...current,{step_key:parentKey,outcome:"SUCCESS"}]
   : current.filter(item=>item.step_key!==parentKey);
  updateStep(selected.key,{depends_on:next});
 }
 function changeDependencyOutcome(parentKey,outcome){
  updateStep(selected.key,{depends_on:(selected.depends_on||[]).map(item=>item.step_key===parentKey?{...item,outcome}:item)});
 }
 function changeInput(text){
  setInputText(text);
  try{
   const parsed=JSON.parse(text);
   if(!parsed||Array.isArray(parsed)||typeof parsed!=="object")throw new Error("Step input must be a JSON object.");
   updateStep(selected.key,{input:parsed});setInputError("");
  }catch(error){setInputError(error instanceof SyntaxError?"Step input JSON is incomplete or invalid.":error.message);}
 }

 return <div className="pipeline-graph-editor">
  <div className="pipeline-graph-toolbar">
   <div><strong>Workflow graph</strong><span className="muted">{steps.length} / 32 nodes · immutable after publishing</span></div>
   <div className="button-row"><Button size="sm" variant="outline" type="button" onClick={addStep} disabled={steps.length>=32}>Add node</Button><Button size="sm" variant="outline" type="button" onClick={removeStep} disabled={!selected||steps.length<=1}>Remove selected</Button></div>
  </div>
  <div className="pipeline-graph-viewport" role="region" aria-label="Pipeline dependency graph" tabIndex={0}>
   <div className="pipeline-graph-canvas" style={{width:graph.width,height:graph.height}}>
    <svg className="pipeline-graph-edges" width={graph.width} height={graph.height} aria-hidden="true">
     <defs><marker id="pipeline-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor"/></marker></defs>
     {graph.edges.map(edge=>{
      const from=graph.positions[edge.from],to=graph.positions[edge.to];
      const x1=from.x+from.width,y1=from.y+from.height/2,x2=to.x,y2=to.y+to.height/2;
      const middle=(x1+x2)/2;
      return <g key={edge.from+"-"+edge.to}>
       <path d={"M "+x1+" "+y1+" C "+middle+" "+y1+", "+middle+" "+y2+", "+x2+" "+y2} fill="none" stroke="currentColor" strokeWidth="1.7" markerEnd="url(#pipeline-arrow)" opacity=".55"/>
       <text x={middle} y={(y1+y2)/2-7} textAnchor="middle" className="pipeline-graph-edge-label">{edge.outcome}</text>
      </g>;
     })}
    </svg>
    {steps.map(step=>{
     const pos=graph.positions[step.key];
     return <button key={step.key} type="button" className={"pipeline-graph-node"+(selected?.key===step.key?" is-selected":"")} style={{left:pos.x,top:pos.y,width:pos.width,height:pos.height}} onClick={()=>setSelectedKey(step.key)} aria-pressed={selected?.key===step.key}>
      <span className="pipeline-node-type">{step.type.replaceAll("_"," ")}</span>
      <strong>{step.name||step.key}</strong>
      <span className="pipeline-node-key">{step.key}</span>
      <span className="pipeline-node-dependencies">{(step.depends_on||[]).length?((step.depends_on||[]).length+" prerequisite(s)"):"Start node"}</span>
     </button>;
    })}
   </div>
  </div>
  {selected?<div className="pipeline-node-inspector">
   <div className="pipeline-inspector-heading"><div><strong>Node properties</strong><span className="muted">Edit the selected operation and its dependency conditions.</span></div><span className="mono">{selected.key}</span></div>
   <div className="form-grid">
    <Field label="Step key" hint="Stable execution identity; create a new node to add a key."><input value={selected.key} readOnly aria-readonly="true"/></Field>
    <Field label="Operation type" required><select value={selected.type} onChange={event=>changeType(event.target.value)}>{STEP_TYPES.map(type=><option key={type}>{type}</option>)}</select></Field>
    <Field label="Display name" required><input value={selected.name||""} maxLength={120} onChange={event=>updateStep(selected.key,{name:event.target.value})}/></Field>
    <Field label="Timeout (seconds)"><input type="number" min="5" max="3600" value={selected.timeout_seconds||300} onChange={event=>updateStep(selected.key,{timeout_seconds:Number(event.target.value)})}/></Field>
    <Field label="Maximum attempts"><select value={selected.max_attempts||1} onChange={event=>updateStep(selected.key,{max_attempts:Number(event.target.value)})}>{[1,2,3,4,5].map(count=><option key={count} value={count}>{count}</option>)}</select></Field>
   </div>
   <div className="pipeline-dependencies">
    <strong>Run this node when prerequisites match</strong>
    <p className="muted">Multiple prerequisites use AND semantics. Choose a condition for each incoming edge.</p>
    {steps.filter(item=>item.key!==selected.key).map(parent=>{
     const dependency=(selected.depends_on||[]).find(item=>item.step_key===parent.key);
     return <div key={parent.key} className="pipeline-dependency-row">
      <label><input type="checkbox" checked={Boolean(dependency)} onChange={event=>toggleDependency(parent.key,event.target.checked)}/><span>{parent.name||parent.key}</span></label>
      {dependency?<select value={dependency.outcome} onChange={event=>changeDependencyOutcome(parent.key,event.target.value)} aria-label={"Condition for "+parent.key}>{OUTCOMES.map(outcome=><option key={outcome}>{outcome}</option>)}</select>:<span className="muted">Not connected</span>}
     </div>;
    })}
    {!steps.some(item=>item.key!==selected.key)?<span className="muted">Add another node to create a dependency.</span>:null}
   </div>
   <Field label="Operation input JSON" className="full-width" hint="Only the selected operation's documented input fields are accepted. Credential material and arbitrary commands are never accepted.">
    <textarea rows={8} value={inputText} onChange={event=>changeInput(event.target.value)} spellCheck="false"/>
   </Field>
   {inputError?<InlineNotice tone="danger">{inputError}</InlineNotice>:null}
   <InlineNotice tone="info">A node without prerequisites can start independently. SUCCESS, FAILURE and COMPLETED edges control conditional branches. The backend validates cycles, references, permissions and immutable confirmation boundaries before publishing.</InlineNotice>
  </div>:null}
 </div>;
}
