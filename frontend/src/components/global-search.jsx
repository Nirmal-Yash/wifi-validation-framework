import React,{useEffect,useMemo,useRef,useState} from "react";
import {ArrowRight,Building2,FolderKanban,FlaskConical,Search,X} from "lucide-react";
import {navigate} from "@/router";

export function GlobalSearch({navigationItems,workspace}){
 const [open,setOpen]=useState(false);
 const [query,setQuery]=useState("");
 const [activeIndex,setActiveIndex]=useState(0);
 const inputRef=useRef(null);
 const triggerRef=useRef(null);
 const wasOpen=useRef(false);
 const entries=useMemo(()=>[
  ...navigationItems.map(item=>({
   id:"page-"+item.key,type:"page",label:item.label,
   description:item.group+" · Open module",keywords:item.key+" "+item.group,
   href:item.href,
  })),
  ...(workspace.organizations||[]).map(item=>({
   id:"organization-"+item.organization_id,type:"organization",label:item.name,
   description:"Organization · Switch workspace",keywords:"organization "+(item.slug||""),
   value:item.organization_id,
  })),
  ...(workspace.projects||[]).map(item=>({
   id:"project-"+item.project_id,type:"project",label:item.name,
   description:"Project · Current Organization",keywords:"project "+(item.slug||""),
   value:item.project_id,
  })),
  ...(workspace.labs||[]).map(item=>({
   id:"lab-"+item.lab_id,type:"lab",label:item.name,
   description:"Lab · Current Project",keywords:"lab "+(item.provider_id||""),
   value:item.lab_id,
  })),
 ],[navigationItems,workspace.organizations,workspace.projects,workspace.labs]);
 const results=useMemo(()=>{
  const needle=query.trim().toLowerCase();
  const ranked=entries.filter(item=>!needle||[item.label,item.description,item.keywords].join(" ").toLowerCase().includes(needle));
  return ranked.slice(0,14);
 },[entries,query]);

 useEffect(()=>{
  const handleShortcut=event=>{
   if((event.metaKey||event.ctrlKey)&&String(event.key).toLowerCase()==="k"){
    event.preventDefault();
    setQuery("");
    setActiveIndex(0);
    setOpen(true);
   }else if(open&&event.key==="Escape"){
    event.preventDefault();
    setOpen(false);
   }
  };
  window.addEventListener("keydown",handleShortcut);
  return()=>window.removeEventListener("keydown",handleShortcut);
 },[open]);
 useEffect(()=>{
  if(open){
   wasOpen.current=true;
   inputRef.current?.focus();
  }else if(wasOpen.current){
   wasOpen.current=false;
   triggerRef.current?.focus();
  }
 },[open]);
 useEffect(()=>setActiveIndex(0),[query]);

 const selectResult=item=>{
  setOpen(false);
  setQuery("");
  if(item.type==="organization"){
   workspace.selectOrganization(item.value);
   navigate("/workspace");
  }else if(item.type==="project"){
   workspace.selectProject(item.value);
   navigate("/");
  }else if(item.type==="lab"){
   workspace.selectLab(item.value);
   navigate("/");
  }else{
   navigate(item.href);
  }
 };
 const onInputKeyDown=event=>{
  if(event.key==="ArrowDown"){
   event.preventDefault();
   setActiveIndex(index=>Math.min(index+1,Math.max(0,results.length-1)));
  }else if(event.key==="ArrowUp"){
   event.preventDefault();
   setActiveIndex(index=>Math.max(0,index-1));
  }else if(event.key==="Enter"&&results[activeIndex]){
   event.preventDefault();
   selectResult(results[activeIndex]);
  }
 };
 const iconFor=item=>item.type==="organization"?<Building2 size={15}/>:item.type==="project"?<FolderKanban size={15}/>:item.type==="lab"?<FlaskConical size={15}/>:<ArrowRight size={15}/>;

 return <>
  <button ref={triggerRef} type="button" className="global-search-trigger"
   aria-label="Search pages and workspace" aria-haspopup="dialog" aria-expanded={open}
   onClick={()=>{setQuery("");setActiveIndex(0);setOpen(true);}}>
   <Search size={15} aria-hidden="true"/>
   <span>Search pages and workspace</span>
   <kbd>Ctrl K / ⌘ K</kbd>
  </button>
  {open?<div className="global-search-overlay" onMouseDown={event=>{if(event.target===event.currentTarget)setOpen(false);}}>
   <section className="global-search-dialog" role="dialog" aria-modal="true" aria-labelledby="global-search-title">
    <h2 id="global-search-title" className="sr-only">Search NetRegress</h2>
    <div className="global-search-input-wrap">
     <Search size={17} aria-hidden="true"/>
     <input ref={inputRef} type="search" aria-label="Search NetRegress"
      aria-controls="global-search-results" aria-activedescendant={results[activeIndex]?.id}
      placeholder="Find a page, Organization, Project or Lab…"
      value={query} onChange={event=>setQuery(event.target.value)} onKeyDown={onInputKeyDown}/>
     <button type="button" className="global-search-close" aria-label="Close search" onClick={()=>setOpen(false)}><X size={16}/></button>
    </div>
    <div className="global-search-hint">Search is limited to modules and workspace entries visible to your current account.</div>
    <div className="global-search-results" id="global-search-results" role="listbox" aria-label="Search results">
     {results.length?results.map((item,index)=><button key={item.id} id={item.id} type="button"
      role="option" aria-selected={activeIndex===index}
      className="global-search-result" onMouseEnter={()=>setActiveIndex(index)}
      onClick={()=>selectResult(item)}>
      <span className="global-search-result-icon">{iconFor(item)}</span>
      <span className="global-search-result-copy"><strong>{item.label}</strong><small>{item.description}</small></span>
      <ArrowRight size={14} aria-hidden="true"/>
     </button>):<p className="global-search-empty">No matching pages or workspace entries.</p>}
    </div>
    <div className="global-search-footer"><span>↑ ↓ Navigate</span><span>Enter Open</span><span>Esc Close</span></div>
   </section>
  </div>:null}
 </>;
}

export default GlobalSearch;
