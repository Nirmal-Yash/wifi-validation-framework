import React,{useState} from "react";
import {api} from "../api";
import {Button,InlineNotice} from "../components/ui";
export default function LoginPage({onLogin}){
 const[username,setUsername]=useState(""),[password,setPassword]=useState(""),[error,setError]=useState(null),[loading,setLoading]=useState(false);
 const submit=async event=>{event.preventDefault();setLoading(true);setError(null);try{await api.login(username.trim(),password);onLogin(await api.me());}catch(err){setError(err);}finally{setLoading(false);}};
 return<div className="login-shell"><div className="login-panel">
  <div className="brand brand-centered"><div className="brand-mark">NR</div><div><strong>NetRegress</strong><span>Validation Runner</span></div></div>
  <h1>Sign in</h1><p className="muted">Authenticate against the Runner session boundary. Authorization remains enforced by the API.</p>
  <form onSubmit={submit} className="form-stack">
   <label className="field"><span>Username</span><input value={username} onChange={event=>setUsername(event.target.value)} autoComplete="username" required/></label>
   <label className="field"><span>Password</span><input type="password" value={password} onChange={event=>setPassword(event.target.value)} autoComplete="current-password" required/></label>
   {error?<InlineNotice tone="danger">{error.message}</InlineNotice>:null}
   <Button loading={loading} type="submit">Sign in</Button>
  </form>
 </div></div>;
}