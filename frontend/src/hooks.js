import {useCallback,useEffect,useState} from "react";
export function useRoute(){
  const[route,setRoute]=useState(()=>({key:window.location.pathname+window.location.search,value:window.location.pathname}));
  useEffect(()=>{const onPopState=()=>setRoute({key:window.location.pathname+window.location.search,value:window.location.pathname});window.addEventListener("popstate",onPopState);return()=>window.removeEventListener("popstate",onPopState);},[]);
  return route;
}
export function useAsyncLoader(loader,dependencies=[],options={}){
  const{enabled=true,refreshMs=0}=options;
  const[state,setState]=useState({data:null,loading:enabled,error:null});
  const reload=useCallback(async()=>{
    if(!enabled)return;
    setState(current=>({...current,loading:true,error:null}));
    try{const data=await loader();setState({data,loading:false,error:null});return data;}
    catch(error){setState(current=>({...current,loading:false,error}));throw error;}
  },dependencies);
  useEffect(()=>{
    let active=true;
    if(!enabled){setState({data:null,loading:false,error:null});return undefined;}
    reload().catch(()=>{});
    if(!refreshMs)return undefined;
    const timer=window.setInterval(()=>{if(active)reload().catch(()=>{});},refreshMs);
    return()=>{active=false;window.clearInterval(timer);};
  },[reload,enabled,refreshMs]);
  return{...state,reload};
}
export function useMutation(){
  const[state,setState]=useState({loading:false,error:null,success:null});
  const run=async(action)=>{setState({loading:true,error:null,success:null});try{const data=await action();setState({loading:false,error:null,success:data});return data;}catch(error){setState({loading:false,error,success:null});throw error;}};
  return{...state,run,reset:()=>setState({loading:false,error:null,success:null})};
}