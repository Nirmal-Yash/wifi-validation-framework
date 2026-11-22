import React,{createContext,useCallback,useContext,useEffect,useMemo,useRef,useState} from "react";
import {api} from "@/api";

const WorkspaceContext=createContext(null);

function readSelection(username){
 try{
  const raw=globalThis.sessionStorage?.getItem("netregress.workspace."+username);
  const value=raw?JSON.parse(raw):{};
  return value&&typeof value==="object"?value:{};
 }catch{return {};}
}

export function WorkspaceProvider({user,children}){
 const username=String(user?.username||"anonymous");
 const [organizations,setOrganizations]=useState([]);
 const [projects,setProjects]=useState([]);
 const [labs,setLabs]=useState([]);
 const [activeOrganizationId,setActiveOrganizationId]=useState("");
 const [activeProjectId,setActiveProjectId]=useState("");
 const [activeLabId,setActiveLabId]=useState("");
 const [organizationsLoading,setOrganizationsLoading]=useState(true);
 const [projectsLoading,setProjectsLoading]=useState(false);
 const [labsLoading,setLabsLoading]=useState(false);
 const [error,setError]=useState("");
 const savedSelection=useRef(readSelection(username));

 useEffect(()=>{
  let current=true;
  setOrganizationsLoading(true);setError("");
  const saved=readSelection(username);
  savedSelection.current=saved;
  api.workspaceOrganizations().then(result=>{
   if(!current)return;
   const rows=Array.isArray(result?.items)?result.items:[];
   setOrganizations(rows);
   const preferred=rows.some(item=>item.organization_id===saved.organizationId)?saved.organizationId:(rows[0]?.organization_id||"");
   setActiveOrganizationId(preferred);
   if(!preferred){setProjects([]);setLabs([]);setActiveProjectId("");setActiveLabId("");}
  }).catch(()=>{
   if(!current)return;
   setOrganizations([]);setProjects([]);setLabs([]);
   setActiveOrganizationId("");setActiveProjectId("");setActiveLabId("");
   setError("ORGANIZATIONS_UNAVAILABLE");
  }).finally(()=>{if(current)setOrganizationsLoading(false);});
  return()=>{current=false;};
 },[username]);

 useEffect(()=>{
  if(organizationsLoading)return undefined;
  if(!activeOrganizationId){
   setProjects([]);setLabs([]);setActiveProjectId("");setActiveLabId("");
   return undefined;
  }
  let current=true;
  setProjectsLoading(true);setProjects([]);setLabs([]);setActiveLabId("");
  api.workspaceProjects({organization_id:activeOrganizationId}).then(result=>{
   if(!current)return;
   const rows=Array.isArray(result?.items)?result.items:[];
   setProjects(rows);
   const saved=savedSelection.current;
   const preferred=rows.some(item=>item.project_id===saved.projectId)?saved.projectId:(rows[0]?.project_id||"");
   setActiveProjectId(preferred);
   if(!preferred)setActiveLabId("");
  }).catch(()=>{
   if(!current)return;
   setProjects([]);setLabs([]);setActiveProjectId("");setActiveLabId("");
   setError("PROJECTS_UNAVAILABLE");
  }).finally(()=>{if(current)setProjectsLoading(false);});
  return()=>{current=false;};
 },[activeOrganizationId,organizationsLoading,username]);

 useEffect(()=>{
  if(projectsLoading)return undefined;
  if(!activeProjectId){setLabs([]);setActiveLabId("");return undefined;}
  let current=true;
  setLabsLoading(true);setLabs([]);
  api.workspaceLabs(activeProjectId).then(result=>{
   if(!current)return;
   const rows=Array.isArray(result?.items)?result.items:[];
   setLabs(rows);
   const saved=savedSelection.current;
   setActiveLabId(rows.some(item=>item.lab_id===saved.labId)?saved.labId:"");
  }).catch(()=>{
   if(!current)return;
   setLabs([]);setActiveLabId("");
   setError("LABS_UNAVAILABLE");
  }).finally(()=>{if(current)setLabsLoading(false);});
  return()=>{current=false;};
 },[activeProjectId,projectsLoading,username]);

 useEffect(()=>{
  try{
   globalThis.sessionStorage?.setItem("netregress.workspace."+username,JSON.stringify({
    organizationId:activeOrganizationId,projectId:activeProjectId,labId:activeLabId
   }));
  }catch{/* Selection remains usable when storage is unavailable. */}
 },[username,activeOrganizationId,activeProjectId,activeLabId]);

 const selectOrganization=useCallback(id=>{
  savedSelection.current={organizationId:String(id||""),projectId:"",labId:""};
  setActiveOrganizationId(String(id||""));setActiveProjectId("");setActiveLabId("");setError("");
 },[]);
 const selectProject=useCallback(id=>{
  savedSelection.current={...savedSelection.current,organizationId:activeOrganizationId,projectId:String(id||""),labId:""};
  setActiveProjectId(String(id||""));setActiveLabId("");setError("");
 },[activeOrganizationId]);
 const selectLab=useCallback(id=>{
  savedSelection.current={...savedSelection.current,organizationId:activeOrganizationId,projectId:activeProjectId,labId:String(id||"")};
  setActiveLabId(String(id||""));setError("");
 },[activeOrganizationId,activeProjectId]);

 const value=useMemo(()=>({
  organizations,projects,labs,activeOrganizationId,activeProjectId,activeLabId,
  organizationsLoading,projectsLoading,labsLoading,
  loading:organizationsLoading||projectsLoading||labsLoading,
  error,selectOrganization,selectProject,selectLab
 }),[organizations,projects,labs,activeOrganizationId,activeProjectId,activeLabId,organizationsLoading,projectsLoading,labsLoading,error,selectOrganization,selectProject,selectLab]);
 return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(){
 const value=useContext(WorkspaceContext);
 if(!value)throw new Error("useWorkspace must be used within WorkspaceProvider.");
 return value;
}
