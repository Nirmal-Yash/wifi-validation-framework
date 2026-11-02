import {useCallback,useEffect,useId,useState} from "react";
import {useMutation as useTanstackMutation,useQuery} from "@tanstack/react-query";

export function useRoute(){
 const[route,setRoute]=useState(()=>({
  key:window.location.pathname+window.location.search,
  value:window.location.pathname,
 }));
 useEffect(()=>{
  const onPopState=()=>setRoute({
   key:window.location.pathname+window.location.search,
   value:window.location.pathname,
  });
  window.addEventListener("popstate",onPopState);
  return()=>window.removeEventListener("popstate",onPopState);
 },[]);
 return route;
}

export function useAsyncLoader(loader,dependencies=[],options={}){
 const{enabled=true,refreshMs=0,staleTime,queryKey}=options;
 const hookId=useId();
 const query=useQuery({
  // Each loader has its own namespace; Run ID alone is not a resource key.
  queryKey:["netregress",queryKey||hookId,...dependencies],
  queryFn:()=>loader(),
  enabled,
  staleTime:staleTime??(
   typeof refreshMs==="number"&&refreshMs
    ?Math.min(refreshMs,10000)
    :5000
  ),
  refetchInterval:typeof refreshMs==="function"?refreshMs:(refreshMs||false),
  refetchIntervalInBackground:false,
  refetchOnWindowFocus:true,
  refetchOnReconnect:true,
 });
 const reload=useCallback(async()=>{
  const result=await query.refetch();
  if(result.error)throw result.error;
  return result.data;
 },[query.refetch]);
 return{
  data:query.data??null,
  loading:query.isLoading,
  error:query.error,
  reload,
  isFetching:query.isFetching,
 };
}

export function useMutation(){
 const mutation=useTanstackMutation({mutationFn:action=>action()});
 return{
  loading:mutation.isPending,
  error:mutation.error,
  success:mutation.data,
  run:mutation.mutateAsync,
  reset:mutation.reset,
 };
}
