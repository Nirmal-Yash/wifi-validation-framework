import React,{useState} from "react";
import {Activity,Eye,EyeOff,LockKeyhole,ShieldCheck,Wifi} from "lucide-react";
import {Button,Field,InlineNotice} from "@/components/ui";

export default function LoginPage({onLogin,onBootstrap,setupRequired=false,notice,onDismissNotice}){
 const[username,setUsername]=useState("owner");
 const[password,setPassword]=useState("");
 const[confirmPassword,setConfirmPassword]=useState("");
 const[showPassword,setShowPassword]=useState(false);
 const[error,setError]=useState(null);
 const[loading,setLoading]=useState(false);
 const submit=async event=>{
  event.preventDefault();setLoading(true);setError(null);
  try{
   if(setupRequired){
    if(password!==confirmPassword)throw new Error("The passwords do not match.");
    await onBootstrap(username.trim(),password);
   }else{
    await onLogin(username.trim(),password);
   }
   setPassword("");setConfirmPassword("");
  }
  catch(err){setError(err);}
  finally{setLoading(false);}
 };
 return <div className="login-shell">
  <section className="login-brand-panel">
   <div className="login-brand"><span className="brand-mark">NR</span><div><strong>NetRegress</strong><small>VALIDATION RUNNER</small></div></div>
   <div className="login-brand-copy"><div className="eyebrow"><span className="hero-live-dot"/>LOCAL-FIRST VALIDATION PLATFORM</div><h1>Engineering confidence, backed by evidence.</h1><p>Operate WiFi validation with traceable Runs, trustworthy environment checks, regression intelligence and integrity-verified evidence.</p></div>
   <div className="login-feature-grid">
    <div className="login-feature"><span><Activity size={17}/></span><div><strong>Execution visibility</strong><small>Understand lifecycle and test outcomes.</small></div></div>
    <div className="login-feature"><span><ShieldCheck size={17}/></span><div><strong>Evidence integrity</strong><small>Inspect recorded artifacts and provenance.</small></div></div>
    <div className="login-feature"><span><Wifi size={17}/></span><div><strong>Environment context</strong><small>Separate virtual lab results from RF certification.</small></div></div>
   </div>
   <div className="login-brand-footer"><span>STANDALONE RUNNER</span><span>LOCAL SESSION · API ENFORCED RBAC</span></div>
  </section>
  <section className="login-form-panel">
   <div className="login-form-wrap">
    <div className="mobile-login-brand"><span className="brand-mark">NR</span><strong>NetRegress</strong></div>
    <div className="login-heading"><div className="eyebrow">{setupRequired?"FIRST-TIME SETUP":"SECURE ACCESS"}</div><h2>{setupRequired?"Create your Owner account":"Welcome back"}</h2><p>{setupRequired?"Set the local Global Owner credentials for this Runner. This setup can only be completed once.":"Sign in to your local validation workspace."}</p></div>
    {notice?<div className="login-notice"><InlineNotice tone="warning">{notice}</InlineNotice>{onDismissNotice?<button type="button" onClick={onDismissNotice} aria-label="Dismiss message">×</button>:null}</div>:null}
    <form className="login-form" onSubmit={submit}>
     <Field label="Username" required><input value={username} onChange={event=>setUsername(event.target.value)} autoComplete="username" autoCapitalize="none" spellCheck="false" required placeholder="owner"/></Field>
     <Field label="Password" required><div className="password-field"><input value={password} onChange={event=>setPassword(event.target.value)} type={showPassword?"text":"password"} autoComplete={setupRequired?"new-password":"current-password"} minLength={setupRequired?12:undefined} required placeholder={setupRequired?"At least 12 characters":"Enter your password"}/><button type="button" aria-label={showPassword?"Hide password":"Show password"} onClick={()=>setShowPassword(value=>!value)}>{showPassword?<EyeOff size={16}/>:<Eye size={16}/>}</button></div></Field>
     {setupRequired?<Field label="Confirm password" required><input value={confirmPassword} onChange={event=>setConfirmPassword(event.target.value)} type="password" autoComplete="new-password" minLength={12} required placeholder="Enter the password again"/></Field>:null}
     {error?<InlineNotice tone="danger">{error.message||"Authentication failed."}</InlineNotice>:null}
     <Button className="login-submit" type="submit" loading={loading} disabled={!username.trim()||!password||(setupRequired&&(password.length<12||password!==confirmPassword||!onBootstrap))}>{setupRequired?"Create Owner account":"Sign in securely"} <LockKeyhole size={15}/></Button>
    </form>
    <div className="login-security"><ShieldCheck size={15}/><span>Protected by an HttpOnly session cookie, CSRF validation and server-enforced role permissions.</span></div>
    <p className="login-setup-help">{setupRequired?"The Owner account is stored in this local workspace. Your password is never included in the app bundle.":"Use your assigned local Runner account. Contact your workspace Owner if access is unavailable."}</p>
   </div>
  </section>
 </div>;
}
