const base="/api/v1";
let csrfToken="";
export class ApiError extends Error{
  constructor(message,status=0,code="REQUEST_FAILED",details={}){super(message);this.name="ApiError";this.status=status;this.code=code;this.details=details;}
}
const newKey=()=>globalThis.crypto?.randomUUID?globalThis.crypto.randomUUID():"ui-"+Date.now()+"-"+Math.random().toString(36).slice(2);
const encode=(value)=>encodeURIComponent(String(value));
async function rawRequest(path,options={}){
  const response=await fetch(base+path,{credentials:"include",...options,headers:{Accept:"application/json","Content-Type":"application/json",...(options.headers||{})}});
  const body=await response.json().catch(()=>({}));
  if(!response.ok){const error=body?.error||{};throw new ApiError(error.message||"Request failed",response.status,error.code||"REQUEST_FAILED",error.details||{});}
  return body.data;
}
async function ensureCsrf(){if(csrfToken)return csrfToken;const data=await rawRequest("/auth/csrf",{method:"GET"});csrfToken=data?.csrf_token||"";return csrfToken;}
async function request(path,options={}){
  const method=(options.method||"GET").toUpperCase();
  const headers={...(options.headers||{})};
  if(["POST","PUT","PATCH","DELETE"].includes(method)&&path!=="/auth/login"){
    headers["X-CSRF-Token"]=await ensureCsrf();
    if(method==="POST"&&!headers["Idempotency-Key"])headers["Idempotency-Key"]=newKey();
  }
  const data=await rawRequest(path,{...options,headers});
  if(path==="/auth/login")csrfToken=data?.csrf_token||"";
  if(path==="/auth/logout")csrfToken="";
  return data;
}
const query=(params={})=>{const search=new URLSearchParams();Object.entries(params).forEach(([key,value])=>{if(value!==undefined&&value!==null&&value!=="")search.set(key,value);});const text=search.toString();return text?"?"+text:"";};
export const api={
  health:()=>request("/health"),readiness:()=>request("/readiness"),
  login:(username,password)=>request("/auth/login",{method:"POST",body:JSON.stringify({username,password})}),
  logout:()=>request("/auth/logout",{method:"POST"}),me:()=>request("/auth/me"),
  runs:(params={})=>request("/runs"+query(params)),run:(runId)=>request("/runs/"+encode(runId)),
  tests:(runId)=>request("/runs/"+encode(runId)+"/tests"),
  test:(runId,testResultId)=>request("/runs/"+encode(runId)+"/tests/"+encode(testResultId)),
  runMetrics:(runId)=>request("/runs/"+encode(runId)+"/metrics"),
  metricsHistory:(testId)=>request("/tests/"+encode(testId)+"/metrics"),
  launch:(payload)=>request("/runs",{method:"POST",body:JSON.stringify(payload)}),
  cancel:(runId,reason)=>request("/runs/"+encode(runId)+"/cancel",{method:"POST",body:JSON.stringify({reason})}),
  retry:(runId)=>request("/runs/"+encode(runId)+"/retry",{method:"POST"}),
  regressions:(baselineRunId,currentRunId)=>request("/regressions"+query({baseline_run_id:baselineRunId,current_run_id:currentRunId})),
  runRegressions:(runId,baselineRunId)=>request("/runs/"+encode(runId)+"/regressions"+query({baseline_run_id:baselineRunId})),
  telemetry:(runId)=>request("/runs/"+encode(runId)+"/telemetry"),
  healthForRun:(runId)=>request("/runs/"+encode(runId)+"/health"),
  labHealth:(labId)=>request("/labs/"+encode(labId)+"/health"),
  artifacts:(params={})=>request("/artifacts"+query(params)),
  artifact:(artifactId)=>request("/artifacts/"+encode(artifactId)),
  artifactDownloadUrl:(artifactId)=>base+"/artifacts/"+encode(artifactId)+"/download",
  baselines:()=>request("/baselines"),
  promoteBaseline:(payload)=>request("/baselines",{method:"POST",body:JSON.stringify(payload)}),
  promoteExistingBaseline:(baselineId,payload)=>request("/baselines/"+encode(baselineId)+"/promote",{method:"POST",body:JSON.stringify(payload)}),
  createWaiver:(payload)=>request("/waivers",{method:"POST",body:JSON.stringify(payload)}),
  firmwareOperation:(payload)=>request("/firmware/operations",{method:"POST",body:JSON.stringify(payload)}),
  firmwareRollback:(deviceId,payload)=>request("/firmware/"+encode(deviceId)+"/rollback",{method:"POST",body:JSON.stringify(payload)})
};