import React,{createContext,useCallback,useContext,useEffect,useMemo,useRef,useState} from "react";
import {useQueryClient} from "@tanstack/react-query";
import {api,clearCsrfToken} from "@/api";

const SessionContext=createContext(null);
const IDLE_TIMEOUT_MS=30*60*1000;
const WARNING_BEFORE_MS=3*60*1000;
const ACTIVITY_EVENTS=["pointerdown","keydown","touchstart","scroll","mousemove"];
const CHANNEL_NAME="netregress-session";

export function SessionProvider({children}){
 const queryClient=useQueryClient();
 const[status,setStatus]=useState("checking");
 const[user,setUser]=useState(null);
 const[sessionNotice,setSessionNotice]=useState("");
 const[idleRemaining,setIdleRemaining]=useState(IDLE_TIMEOUT_MS);
 const lastActivity=useRef(Date.now());
 const lastServerActivity=useRef(0);
 const expiring=useRef(false);
 const statusRef=useRef(status);
 const channelRef=useRef(null);
 const sessionEpoch=useRef(0);

 useEffect(()=>{statusRef.current=status;},[status]);

 const clearLocalSession=useCallback((message="")=>{
  sessionEpoch.current+=1;
  statusRef.current="anonymous";
  clearCsrfToken();
  queryClient.clear();
  setUser(null);
  setStatus("anonymous");
  setSessionNotice(message);
  setIdleRemaining(IDLE_TIMEOUT_MS);
 },[queryClient]);

 const finishSession=useCallback(async(message="")=>{
  if(expiring.current)return;
  expiring.current=true;
  try{await api.logout();}catch{/* The cookie may already have expired; clear local state regardless. */}
  clearLocalSession(message);
  try{channelRef.current?.postMessage({type:"logout"});}catch{/* A closing tab may have closed its channel. */}
  expiring.current=false;
 },[clearLocalSession]);

 const login=useCallback(async(username,password)=>{
  setStatus("authenticating");
  setSessionNotice("");
  clearCsrfToken();
  queryClient.clear();
  try{
   await api.login(username,password);
   const profile=await api.me();
   if(!profile?.username||!profile?.role)throw new Error("The Runner returned an incomplete identity profile.");
   lastActivity.current=Date.now();
   lastServerActivity.current=Date.now();
   setIdleRemaining(IDLE_TIMEOUT_MS);
   setUser(profile);
   setStatus("authenticated");
   try{channelRef.current?.postMessage({type:"login"});}catch{}
   return profile;
  }catch(error){
   clearCsrfToken();
   setStatus("anonymous");
   throw error;
  }
 },[queryClient]);

 const logout=useCallback(async()=>{await finishSession("");},[finishSession]);

 const continueSession=useCallback(async()=>{
  try{
   const profile=await api.me();
   if(!profile?.username)throw new Error("Your session profile is no longer valid.");
   lastActivity.current=Date.now();
   lastServerActivity.current=Date.now();
   setIdleRemaining(IDLE_TIMEOUT_MS);
   setSessionNotice("");
   try{channelRef.current?.postMessage({type:"activity"});}catch{}
   return profile;
  }catch(error){
   await finishSession("Your session expired. Sign in again.");
   throw error;
  }
 },[finishSession]);

 useEffect(()=>{
  let alive=true;
  const epoch=++sessionEpoch.current;
  api.me().then(profile=>{
   if(!alive||epoch!==sessionEpoch.current)return;
   if(profile?.username&&profile?.role){
    lastActivity.current=Date.now();
    lastServerActivity.current=Date.now();
    statusRef.current="authenticated";
    setUser(profile);
    setStatus("authenticated");
   }else{
    statusRef.current="anonymous";
    setUser(null);
    setStatus("anonymous");
   }
  }).catch(error=>{
   if(!alive||epoch!==sessionEpoch.current)return;
   statusRef.current="anonymous";
   setUser(null);
   setStatus("anonymous");
   if(error.code!=="UNAUTHENTICATED"&&error.status!==401)setSessionNotice("The Runner API is unavailable. Start the dashboard service and retry.");
  });
  return()=>{alive=false;};
 },[]);

 useEffect(()=>{
  if(typeof BroadcastChannel==="undefined")return undefined;
  const channel=new BroadcastChannel(CHANNEL_NAME);
  channelRef.current=channel;
  channel.onmessage=event=>{
   const type=event.data?.type;
   if(type==="activity"&&statusRef.current==="authenticated"){
    lastActivity.current=Date.now();
    setIdleRemaining(IDLE_TIMEOUT_MS);
    setSessionNotice("");
   }else if(type==="logout"){
    clearLocalSession("This session was signed out in another tab.");
   }else if(type==="login"&&(statusRef.current==="anonymous"||statusRef.current==="checking")){
    const epoch=++sessionEpoch.current;
    api.me().then(profile=>{
     if(epoch!==sessionEpoch.current||!profile?.username||!profile?.role)return;
     lastActivity.current=Date.now();
     lastServerActivity.current=Date.now();
     setIdleRemaining(IDLE_TIMEOUT_MS);
     statusRef.current="authenticated";
     setUser(profile);
     setStatus("authenticated");
     setSessionNotice("");
    }).catch(()=>{});
   }
  };
  return()=>{
   channel.onmessage=null;
   channel.close();
   if(channelRef.current===channel)channelRef.current=null;
  };
 },[clearLocalSession]);

 useEffect(()=>{
  const expired=()=>{void finishSession("Your session expired. Sign in again.");};
  window.addEventListener("netregress:auth-expired",expired);
  return()=>window.removeEventListener("netregress:auth-expired",expired);
 },[finishSession]);

 useEffect(()=>{
  if(status!=="authenticated"||!user)return undefined;
  let lastEvent=0,lastBroadcast=0;
  const touch=()=>{
   const now=Date.now();
   if(now-lastEvent<750)return;
   lastEvent=now;
   // Once the warning is visible, explicit Continue is required.
   if(IDLE_TIMEOUT_MS-(now-lastActivity.current)>WARNING_BEFORE_MS){
    lastActivity.current=now;
    if(now-lastBroadcast>=5000){
     lastBroadcast=now;
     try{channelRef.current?.postMessage({type:"activity"});}catch{}
    }
    if(now-lastServerActivity.current>=60000){
     lastServerActivity.current=now;
     api.activity().catch(error=>{
      if(error?.status===401){
       void finishSession("Your session could not be refreshed. Sign in again.");
      }
     });
    }
   }
  };
  ACTIVITY_EVENTS.forEach(name=>window.addEventListener(name,touch,{passive:true}));
  const check=()=>{
   const remaining=Math.max(0,IDLE_TIMEOUT_MS-(Date.now()-lastActivity.current));
   // Avoid re-rendering the full application every second during a normal session.
   if(remaining<=WARNING_BEFORE_MS)setIdleRemaining(remaining);
   if(remaining===0)void finishSession("You were signed out after 30 minutes without activity.");
  };
  const timer=window.setInterval(check,1000);
  const visibility=()=>{if(document.visibilityState==="visible")check();};
  document.addEventListener("visibilitychange",visibility);
  check();
  return()=>{
   ACTIVITY_EVENTS.forEach(name=>window.removeEventListener(name,touch));
   window.clearInterval(timer);
   document.removeEventListener("visibilitychange",visibility);
  };
 },[status,user,finishSession]);

 const value=useMemo(()=>({
  status,user,sessionNotice,idleRemaining,
  warningVisible:status==="authenticated"&&idleRemaining<=WARNING_BEFORE_MS,
  login,logout,continueSession,clearNotice:()=>setSessionNotice(""),
 }),[status,user,sessionNotice,idleRemaining,login,logout,continueSession]);
 return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(){
 const value=useContext(SessionContext);
 if(!value)throw new Error("useSession must be used within SessionProvider.");
 return value;
}
