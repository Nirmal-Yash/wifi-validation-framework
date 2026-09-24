const base="/api/v1";
let csrfToken="";

const newKey=()=>(
  globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID()
    : "ui-"+Date.now()+"-"+Math.random().toString(36).slice(2)
);

async function rawRequest(path,options={}){
  const r=await fetch(base+path,{
    credentials:"include",
    ...options,
    headers:{"Content-Type":"application/json",...(options.headers||{})},
  });
  const body=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(body?.error?.message||"Request failed");
  return body.data;
}

async function ensureCsrf(){
  if(csrfToken)return csrfToken;
  const data=await rawRequest("/auth/csrf",{method:"GET"});
  csrfToken=data?.csrf_token||"";
  return csrfToken;
}

async function request(path,options={}){
  const method=(options.method||"GET").toUpperCase();
  const headers={...(options.headers||{})};
  if(["POST","PUT","PATCH","DELETE"].includes(method) && path!=="/auth/login"){
    headers["X-CSRF-Token"]=await ensureCsrf();
    if(method==="POST" && !headers["Idempotency-Key"])headers["Idempotency-Key"]=newKey();
  }
  const data=await rawRequest(path,{...options,headers});
  if(path==="/auth/login")csrfToken=data?.csrf_token||"";
  if(path==="/auth/logout")csrfToken="";
  return data;
}

const id=(x)=>encodeURIComponent(x);

export const api={
  login:(u,p)=>request("/auth/login",{method:"POST",body:JSON.stringify({username:u,password:p})}),
  logout:()=>request("/auth/logout",{method:"POST"}),
  me:()=>request("/auth/me"),
  runs:()=>request("/runs"),
  run:(x)=>request("/runs/"+id(x)),
  tests:(x)=>request("/runs/"+id(x)+"/tests"),
  health:(x)=>request("/runs/"+id(x)+"/health"),
  telemetry:(x)=>request("/runs/"+id(x)+"/telemetry"),
  artifacts:(x)=>request("/artifacts?run_id="+id(x)),
  launch:(p)=>request("/runs",{method:"POST",body:JSON.stringify(p)}),
  cancel:(x,reason)=>request("/runs/"+id(x)+"/cancel",{method:"POST",body:JSON.stringify({reason})}),
  retry:(x)=>request("/runs/"+id(x)+"/retry",{method:"POST"}),
  baselines:()=>request("/baselines"),
  promote:(p)=>request("/baselines",{method:"POST",body:JSON.stringify(p)}),
};
