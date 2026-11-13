const base="/api/v1";
let csrfToken="";
let csrfPromise=null;
let csrfGeneration=0;

export class ApiError extends Error{
 constructor(message,status=0,code="REQUEST_FAILED",details={}){
  super(message);this.name="ApiError";this.status=status;this.code=code;this.details=details;
 }
}
const encode=value=>encodeURIComponent(String(value));
const newKey=()=>globalThis.crypto?.randomUUID?globalThis.crypto.randomUUID():"nr-"+Date.now()+"-"+Math.random().toString(36).slice(2);

export function clearCsrfToken(){csrfGeneration+=1;csrfToken="";csrfPromise=null;}
function notifyExpired(path){
 if(path==="/auth/login"||path==="/auth/me")return;
 clearCsrfToken();
 if(typeof window!=="undefined")window.dispatchEvent(new CustomEvent("netregress:auth-expired"));
}
async function rawRequest(path,options={}){
 let response;
 try{
  response=await fetch(base+path,{
   credentials:"same-origin",
   cache:"no-store",
   ...options,
   headers:{Accept:"application/json",...(options.body?{"Content-Type":"application/json"}:{}),...(options.headers||{})},
  });
 }catch(error){
  if(error instanceof TypeError)throw new ApiError("Cannot reach the Runner API. Start it with ./scripts/start_dashboard.sh from the repository root.",0,"API_UNREACHABLE");
  throw error;
 }
 const contentType=response.headers?.get?.("content-type")||"";
 const body=await response.json().catch(()=>null);
 if(response.status===401)notifyExpired(path);
 if(!body||typeof body!=="object"||!contentType.toLowerCase().includes("application/json"))throw new ApiError("The Runner returned an unexpected response. Check the backend port, proxy and service logs.",response.status,"INVALID_API_RESPONSE");
 if(!response.ok){
  const detail=body.error||{};
  throw new ApiError(detail.message||`Runner API request failed (HTTP ${response.status})`,response.status,detail.code||"REQUEST_FAILED",detail.details||{});
 }
 if(!Object.prototype.hasOwnProperty.call(body,"data"))throw new ApiError("The Runner API response is missing its data envelope. Update/restart the backend and frontend together.",response.status,"INVALID_API_RESPONSE");
 return body.data;
}
async function ensureCsrf(){
 if(csrfToken)return csrfToken;
 if(csrfPromise)return csrfPromise;
 const generation=csrfGeneration;
 csrfPromise=rawRequest("/auth/csrf",{method:"GET"}).then(data=>{
  const token=String(data?.csrf_token||"");
  if(!token)throw new ApiError("The Runner did not issue a CSRF token. Sign in again.",403,"CSRF_UNAVAILABLE");
  if(generation===csrfGeneration)csrfToken=token;
  return token;
 }).finally(()=>{if(generation===csrfGeneration)csrfPromise=null;});
 return csrfPromise;
}
async function request(path,options={}){
 const method=(options.method||"GET").toUpperCase();
 const isMutation=["POST","PUT","PATCH","DELETE"].includes(method);
 const headers={...(options.headers||{})};
 if(path==="/auth/login")clearCsrfToken();
 if(isMutation&&path!=="/auth/login"){
  headers["X-CSRF-Token"]=await ensureCsrf();
  if(method==="POST"&&!headers["Idempotency-Key"])headers["Idempotency-Key"]=newKey();
 }
 try{
  const data=await rawRequest(path,{...options,method,headers});
  if(path==="/auth/login")csrfToken=String(data?.csrf_token||"");
  if(path==="/auth/logout")clearCsrfToken();
  return data;
 }catch(error){
  if(isMutation&&path!=="/auth/login"&&error instanceof ApiError&&error.status===403&&error.code==="CSRF_REQUIRED"){
   clearCsrfToken();
   headers["X-CSRF-Token"]=await ensureCsrf();
   const data=await rawRequest(path,{...options,method,headers});
   if(path==="/auth/logout")clearCsrfToken();
   return data;
  }
  if(path==="/auth/logout")clearCsrfToken();
  throw error;
 }
}
const query=params=>{
 const search=new URLSearchParams();
 Object.entries(params||{}).forEach(([key,value])=>{if(value!==undefined&&value!==null&&value!=="")search.set(key,String(value));});
 const value=search.toString();return value?"?"+value:"";

 credentials:(projectId,deviceId)=>request("/credentials"+query({project_id:projectId,device_id:deviceId})),
 createCredential:payload=>request("/credentials",{method:"POST",body:JSON.stringify(payload)}),
 rotateCredential:(id,payload)=>request("/credentials/"+encode(id)+"/rotate",{method:"POST",body:JSON.stringify(payload)}),
 verifyCredential:id=>request("/credentials/"+encode(id)+"/verify",{method:"POST",body:"{}"}),
 revokeCredential:id=>request("/credentials/"+encode(id),{method:"DELETE"}),
 configurationSchemas:projectId=>request("/configuration/schemas"+query({project_id:projectId})),
 registerConfigurationSchema:payload=>request("/configuration/schemas",{method:"POST",body:JSON.stringify(payload)}),
 configurationProfiles:projectId=>request("/configuration/profiles"+query({project_id:projectId})),
 createConfigurationProfile:payload=>request("/configuration/profiles",{method:"POST",body:JSON.stringify(payload)}),
 configurationRevisions:id=>request("/configuration/profiles/"+encode(id)+"/revisions"),
 createConfigurationRevision:(id,payload)=>request("/configuration/profiles/"+encode(id)+"/revisions",{method:"POST",body:JSON.stringify(payload)}),
 publishConfigurationRevision:(id,payload)=>request("/configuration/profiles/"+encode(id)+"/publish",{method:"POST",body:JSON.stringify(payload)}),
 rollbackConfigurationRevision:(id,payload)=>request("/configuration/profiles/"+encode(id)+"/rollback",{method:"POST",body:JSON.stringify(payload)}),
 applyConfigurationRevision:(id,payload)=>request("/configuration/profiles/"+encode(id)+"/apply",{method:"POST",body:JSON.stringify(payload)}),
 configurationAssignments:projectId=>request("/configuration/assignments"+query({project_id:projectId})),
 resolveConfiguration:payload=>request("/configuration/resolve",{method:"POST",body:JSON.stringify(payload)}),
 importConfigurationYaml:payload=>request("/configuration/import-yaml",{method:"POST",body:JSON.stringify(payload)}),

};
export const api={
 health:()=>request("/health"),readiness:()=>request("/readiness"),
 login:(username,password)=>request("/auth/login",{method:"POST",body:JSON.stringify({username,password})}),
 logout:()=>request("/auth/logout",{method:"POST"}),me:()=>request("/auth/me"),
 activity:()=>request("/auth/activity",{method:"POST",body:"{}"}),
 runs:(params={},options={})=>request("/runs"+query(params),options),run:(id,options={})=>request("/runs/"+encode(id),options),
 tests:(id,options={})=>request("/runs/"+encode(id)+"/tests",options),test:(runId,testId,options={})=>request("/runs/"+encode(runId)+"/tests/"+encode(testId),options),
 runMetrics:(id,options={})=>request("/runs/"+encode(id)+"/metrics",options),metricsHistory:(id,options={})=>request("/tests/"+encode(id)+"/metrics",options),
 launch:payload=>request("/runs",{method:"POST",body:JSON.stringify(payload)}),
 cancel:(id,reason)=>request("/runs/"+encode(id)+"/cancel",{method:"POST",body:JSON.stringify({reason})}),
 retry:id=>request("/runs/"+encode(id)+"/retry",{method:"POST"}),
 regressions:(baseline,current,options={})=>request("/regressions"+query({baseline_run_id:baseline,current_run_id:current}),options),
 releaseGate:(id,baseline)=>request("/runs/"+encode(id)+"/release-gate"+query({baseline_run_id:baseline})),
 runRegressions:(id,baseline)=>request("/runs/"+encode(id)+"/regressions"+query({baseline_run_id:baseline})),
 telemetry:(id,options={})=>request("/runs/"+encode(id)+"/telemetry",options),
 healthForRun:(id,options={})=>request("/runs/"+encode(id)+"/health",options),
 labHealth:(id,options={})=>request("/labs/"+encode(id)+"/health",options),
 artifacts:(params={},options={})=>request("/artifacts"+query(params),options),artifact:id=>request("/artifacts/"+encode(id)),
 artifactDownloadUrl:id=>base+"/artifacts/"+encode(id)+"/download",
 baselines:()=>request("/baselines"),promoteBaseline:payload=>request("/baselines",{method:"POST",body:JSON.stringify(payload)}),
 promoteExistingBaseline:(id,payload)=>request("/baselines/"+encode(id)+"/promote",{method:"POST",body:JSON.stringify(payload)}),
 waivers:()=>request("/waivers"),
 syncQueue:(limit=50)=>request("/sync/queue"+query({limit})),
 createWaiver:payload=>request("/waivers",{method:"POST",body:JSON.stringify(payload)}),
 firmwareOperation:payload=>request("/firmware/operations",{method:"POST",body:JSON.stringify(payload)}),
 firmwareRollback:(id,payload)=>request("/firmware/"+encode(id)+"/rollback",{method:"POST",body:JSON.stringify(payload)}),

 identityUsers:()=>request("/identity/users"),
 inviteIdentityUser:payload=>request("/identity/invitations",{method:"POST",body:JSON.stringify(payload)}),
 updateIdentityUser:(username,payload)=>request("/identity/users/"+encode(username),{method:"PATCH",body:JSON.stringify(payload)}),
 resetIdentityPassword:username=>request("/identity/users/"+encode(username)+"/password-reset",{method:"POST",body:"{}"}),
 revokeIdentitySessions:username=>request("/identity/users/"+encode(username)+"/sessions/revoke",{method:"POST",body:"{}"}),
 identityRoles:(scope)=>request("/identity/roles"+query({scope})),
 createIdentityRole:payload=>request("/identity/roles",{method:"POST",body:JSON.stringify(payload)}),
 identityPermissions:()=>request("/identity/permissions"),
 setRolePermissions:(id,payload)=>request("/identity/roles/"+encode(id)+"/permissions",{method:"PUT",body:JSON.stringify(payload)}),
 deleteIdentityRole:id=>request("/identity/roles/"+encode(id),{method:"DELETE"}),
 assignGlobalRole:(username,payload)=>request("/identity/users/"+encode(username)+"/role",{method:"PUT",body:JSON.stringify(payload)}),
 assignProjectRole:(projectId,username,payload)=>request("/identity/projects/"+encode(projectId)+"/users/"+encode(username)+"/role",{method:"PUT",body:JSON.stringify(payload)}),
 identityAudit:(params={})=>request("/identity/audit"+query(params)),
 acceptInvitation:payload=>request("/auth/invitations/accept",{method:"POST",body:JSON.stringify(payload)}),
 completePasswordReset:payload=>request("/auth/password-resets/complete",{method:"POST",body:JSON.stringify(payload)}),
 workspaceOrganizations:()=>request("/workspace/organizations"),
 createOrganization:payload=>request("/workspace/organizations",{method:"POST",body:JSON.stringify(payload)}),
 updateOrganization:(id,payload)=>request("/workspace/organizations/"+encode(id),{method:"PATCH",body:JSON.stringify(payload)}),
 workspaceProjects:(params={})=>request("/workspace/projects"+query(params)),
 createProject:payload=>request("/workspace/projects",{method:"POST",body:JSON.stringify(payload)}),
 workspaceProject:id=>request("/workspace/projects/"+encode(id)),
 updateProject:(id,payload)=>request("/workspace/projects/"+encode(id),{method:"PATCH",body:JSON.stringify(payload)}),
 workspaceMembers:id=>request("/workspace/projects/"+encode(id)+"/members"),
 addWorkspaceMember:(id,payload)=>request("/workspace/projects/"+encode(id)+"/members",{method:"POST",body:JSON.stringify(payload)}),
 removeWorkspaceMember:(id,username)=>request("/workspace/projects/"+encode(id)+"/members/"+encode(username),{method:"DELETE"}),
 workspaceLabs:id=>request("/workspace/projects/"+encode(id)+"/labs"),
 createWorkspaceLab:(id,payload)=>request("/workspace/projects/"+encode(id)+"/labs",{method:"POST",body:JSON.stringify(payload)}),
 updateWorkspaceLab:(id,payload)=>request("/workspace/labs/"+encode(id),{method:"PATCH",body:JSON.stringify(payload)}),

};
