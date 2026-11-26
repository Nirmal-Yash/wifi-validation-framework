const configuredBase=import.meta.env.VITE_API_BASE_URL||"/api/v1";
let resolvedBase=null;
let basePromise=null;

async function resolveApiBase(){
 if(resolvedBase)return resolvedBase;
 if(basePromise)return basePromise;
 const invoke=globalThis.window?.__TAURI__?.core?.invoke;
 if(typeof invoke==="function"){
  basePromise=Promise.resolve(invoke("api_base_url")).then(value=>{
   const origin=String(value||"").replace(/\/+$/,"");
   if(!/^http:\/\/127\.0\.0\.1:\d{1,5}$/.test(origin))throw new ApiError("The desktop backend returned an invalid local API address.",0,"INVALID_API_BASE");
   resolvedBase=origin+"/api/v1";
   return resolvedBase;
  }).finally(()=>{basePromise=null;});
  return basePromise;
 }
 resolvedBase=configuredBase;
 return resolvedBase;
}
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
  const base=await resolveApiBase();
  const credentials=base.startsWith("http://127.0.0.1:")?"include":"same-origin";
  response=await fetch(base+path,{
   credentials,
   cache:"no-store",
   ...options,
   headers:{Accept:"application/json",...(options.body&&!(typeof FormData!=="undefined"&&options.body instanceof FormData)?{"Content-Type":"application/json"}:{}),...(options.headers||{})},
  });
 }catch(error){
  if(error instanceof TypeError)throw new ApiError("Cannot reach the Runner API. Launch the NetRegress desktop app or start the developer launcher.",0,"API_UNREACHABLE");
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
};

async function rawDownload(path){
 let response;
 try{
  const base=await resolveApiBase();
  const credentials=base.startsWith("http://127.0.0.1:")?"include":"same-origin";
  response=await fetch(base+path,{credentials,cache:"no-store",headers:{Accept:"application/octet-stream"}});
 }catch(error){
  if(error instanceof TypeError)throw new ApiError("Cannot reach the Runner API. Launch the NetRegress desktop app or start the developer launcher.",0,"API_UNREACHABLE");
  throw error;
 }
 if(!response.ok){
  const body=await response.json().catch(()=>null);
  const detail=body?.error||{};
  throw new ApiError(detail.message||`Runner API request failed (HTTP ${response.status})`,response.status,detail.code||"REQUEST_FAILED",detail.details||{});
 }
 const disposition=response.headers?.get?.("content-disposition")||"";
 const encodedName=disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
 const plainName=disposition.match(/filename="?([^";]+)"?/i)?.[1];
 let filename="native-topology-export";
 try{filename=encodedName?decodeURIComponent(encodedName):plainName||filename;}catch{filename=plainName||filename;}
 return {blob:await response.blob(),filename,report:response.headers?.get?.("X-NetRegress-Native-Report")||response.headers?.get?.("X-NetRegress-Export-Report")||""};
}
async function rawDownloadPost(path,body){
 let response;
 try{
  const base=await resolveApiBase();
  const credentials=base.startsWith("http://127.0.0.1:")?"include":"same-origin";
  response=await fetch(base+path,{method:"POST",body,credentials,cache:"no-store",headers:{Accept:"application/octet-stream"}});
 }catch(error){
  if(error instanceof TypeError)throw new ApiError("Cannot reach the Runner API. Launch the NetRegress desktop app or start the developer launcher.",0,"API_UNREACHABLE");
  throw error;
 }
 if(!response.ok){
  const body=await response.json().catch(()=>null);
  const detail=body?.error||{};
  throw new ApiError(detail.message||`Runner API request failed (HTTP ${response.status})`,response.status,detail.code||"REQUEST_FAILED",detail.details||{});
 }
 const disposition=response.headers?.get?.("content-disposition")||"";
 const encodedName=disposition.match(/filename\\*=UTF-8''([^;]+)/i)?.[1];
 const plainName=disposition.match(/filename="?([^";]+)"?/i)?.[1];
 let filename="native-topology-conversion";
 try{filename=encodedName?decodeURIComponent(encodedName):plainName||filename;}catch{filename=plainName||filename;}
 return {blob:await response.blob(),filename,report:response.headers?.get?.("X-NetRegress-Conversion-Report")||""};
}
export const api={
 health:()=>request("/health"),readiness:()=>request("/readiness"),
 setupStatus:()=>request("/setup/status"),
 bootstrapOwner:payload=>rawRequest("/setup/owner",{method:"POST",body:JSON.stringify(payload)}),
 credentials:(projectId,deviceId)=>request("/credentials"+query({project_id:projectId,device_id:deviceId})),
 createCredential:payload=>request("/credentials",{method:"POST",body:JSON.stringify(payload)}),
 rotateCredential:(id,payload)=>request("/credentials/"+encode(id)+"/rotate",{method:"POST",body:JSON.stringify(payload)}),
 verifyCredential:id=>request("/credentials/"+encode(id)+"/verify",{method:"POST",body:"{}"}),
 revokeCredential:id=>request("/credentials/"+encode(id),{method:"DELETE"}),
 devices:(projectId,labId,status="ACTIVE")=>request("/devices"+query({project_id:projectId,lab_id:labId,status})),
 deviceCapabilityReports:deviceId=>request("/devices/"+encode(deviceId)+"/capability-reports"),
 networkConfigAdapters:projectId=>request("/network-intent/compiler/adapters"+query({project_id:projectId})),
 pipelines:(projectId,labId)=>request("/pipelines"+query({project_id:projectId,lab_id})),
 pipeline:id=>request("/pipelines/"+encode(id)),
 createPipeline:payload=>request("/pipelines",{method:"POST",body:JSON.stringify(payload)}),
 createPipelineRevision:(id,payload)=>request("/pipelines/"+encode(id)+"/revisions",{method:"POST",body:JSON.stringify(payload)}),
 publishPipelineRevision:(id,payload)=>request("/pipelines/"+encode(id)+"/publish",{method:"POST",body:JSON.stringify(payload)}),
 pipelineExecutions:id=>request("/pipelines/"+encode(id)+"/executions"),
 enqueuePipelineExecution:(id,payload)=>request("/pipelines/"+encode(id)+"/executions",{method:"POST",body:JSON.stringify(payload)}),
 pipelineExecution:id=>request("/pipeline-executions/"+encode(id)),
 cancelPipelineExecution:id=>request("/pipeline-executions/"+encode(id)+"/cancel",{method:"POST",body:"{}"}),
 recoverPipelineExecution:id=>request("/pipeline-executions/"+encode(id)+"/recover",{method:"POST",body:JSON.stringify({confirmed:true})}),

 validateTopology:payload=>request("/topologies/validate",{method:"POST",body:JSON.stringify(payload)}),
 topologies:projectId=>request("/topologies"+query({project_id:projectId})),
 networkIntentProfiles:projectId=>request("/network-intent/profiles"+query({project_id:projectId})),
 createNetworkIntentProfile:payload=>request("/network-intent/profiles",{method:"POST",body:JSON.stringify(payload)}),
 networkIntentProfile:profileId=>request("/network-intent/profiles/"+encode(profileId)),
 networkIntentRevisions:profileId=>request("/network-intent/profiles/"+encode(profileId)+"/revisions"),
 compileNetworkIntentRevision:(profileId,revisionId,baselineArtifacts)=>request("/network-intent/profiles/"+encode(profileId)+"/revisions/"+encode(revisionId)+"/compile",{method:"POST",body:JSON.stringify(baselineArtifacts?{baseline_artifacts:baselineArtifacts}:{})}),
 infrastructureModules:projectId=>request("/infrastructure/modules"+query({project_id:projectId})),
 infrastructureWorkspaces:(projectId,labId)=>request("/infrastructure/workspaces"+query({project_id:projectId,lab_id:labId})),
 infrastructureWorkspace:workspaceId=>request("/infrastructure/workspaces/"+encode(workspaceId)),
 createInfrastructureWorkspace:payload=>request("/infrastructure/workspaces",{method:"POST",body:JSON.stringify(payload)}),
 createInfrastructurePlan:(workspaceId,kind="APPLY")=>request("/infrastructure/workspaces/"+encode(workspaceId)+"/plans",{method:"POST",body:JSON.stringify({kind})}),
 infrastructurePlans:(projectId,workspaceId)=>request("/infrastructure/plans"+query({project_id:projectId,workspace_id:workspaceId})),
 infrastructurePlan:planId=>request("/infrastructure/plans/"+encode(planId)),
 approveInfrastructurePlan:(planId,payload)=>request("/infrastructure/plans/"+encode(planId)+"/approve",{method:"POST",body:JSON.stringify(payload)}),
 applyInfrastructurePlan:(planId,payload)=>request("/infrastructure/plans/"+encode(planId)+"/apply",{method:"POST",body:JSON.stringify(payload)}),
 infrastructureState:workspaceId=>request("/infrastructure/workspaces/"+encode(workspaceId)+"/state"),
 infrastructureResources:workspaceId=>request("/infrastructure/workspaces/"+encode(workspaceId)+"/resources"),
 createInfrastructureResourceBinding:(workspaceId,payload)=>request("/infrastructure/workspaces/"+encode(workspaceId)+"/resources",{method:"POST",body:JSON.stringify(payload)}),
 infrastructureReconciliations:workspaceId=>request("/infrastructure/workspaces/"+encode(workspaceId)+"/reconciliations"),
 reconcileInfrastructure:workspaceId=>request("/infrastructure/workspaces/"+encode(workspaceId)+"/reconcile",{method:"POST",body:"{}"}),
 recoverInfrastructure:workspaceId=>request("/infrastructure/workspaces/"+encode(workspaceId)+"/recover",{method:"POST",body:JSON.stringify({confirmed:true})}),
 networkAnsiblePlans:projectId=>request("/network-intent/automation/ansible/plans"+query({project_id:projectId})),
 networkAnsiblePlan:planId=>request("/network-intent/automation/ansible/plans/"+encode(planId)),
 createNetworkAnsiblePlan:(profileId,revisionId,payload)=>request("/network-intent/profiles/"+encode(profileId)+"/revisions/"+encode(revisionId)+"/ansible-plan",{method:"POST",body:JSON.stringify(payload)}),
 approveNetworkAnsiblePlan:(planId,payload)=>request("/network-intent/automation/ansible/plans/"+encode(planId)+"/approve",{method:"POST",body:JSON.stringify(payload)}),
 executeNetworkAnsiblePlan:(planId,payload)=>request("/network-intent/automation/ansible/plans/"+encode(planId)+"/execute",{method:"POST",body:JSON.stringify(payload)}),
 createNetworkIntentRevision:(profileId,payload)=>request("/network-intent/profiles/"+encode(profileId)+"/revisions",{method:"POST",body:JSON.stringify(payload)}),
 publishNetworkIntentRevision:(profileId,payload)=>request("/network-intent/profiles/"+encode(profileId)+"/publish",{method:"POST",body:JSON.stringify(payload)}),
 rollbackNetworkIntentRevision:(profileId,payload)=>request("/network-intent/profiles/"+encode(profileId)+"/rollback",{method:"POST",body:JSON.stringify(payload)}),
 validateNetworkIntent:payload=>request("/network-intent/validate",{method:"POST",body:JSON.stringify(payload)}),
 importPacketTracerTopology:formData=>request("/topologies/import/packet-tracer",{method:"POST",body:formData}),
 topologyNativeSources:profileId=>request("/topologies/"+encode(profileId)+"/native-sources"),
 exportPacketTracerRevision:(profileId,sourceId,revisionId)=>rawDownload("/topologies/"+encode(profileId)+"/native-sources/"+encode(sourceId)+"/export"+query({revision_id:revisionId})),
  importNativeTopology:formData=>request("/topologies/import/native",{method:"POST",body:formData}),
  convertNativeTopology:formData=>rawDownloadPost("/topologies/convert/native",formData),
  nativeConfigurationSnapshots:(profileId,revisionId)=>request("/topologies/"+encode(profileId)+"/native-configurations"+query({revision_id:revisionId})),
  createNativeConfigurationSnapshot:(profileId,formData)=>request("/topologies/"+encode(profileId)+"/native-configurations",{method:"POST",body:formData}),
  downloadNativeConfigurationSnapshot:(profileId,snapshotId)=>rawDownload("/topologies/"+encode(profileId)+"/native-configurations/"+encode(snapshotId)+"/download"),
  topologyNativeArtifacts:profileId=>request("/topologies/"+encode(profileId)+"/native-artifacts"),
  exportNativeTopologyArtifact:(profileId,sourceId,revisionId,presentationId)=>rawDownload("/topologies/"+encode(profileId)+"/native-artifacts/"+encode(sourceId)+"/export"+query({revision_id:revisionId,presentation_id:presentationId})),
 createTopology:payload=>request("/topologies",{method:"POST",body:JSON.stringify(payload)}),
 topologyRevisions:profileId=>request("/topologies/"+encode(profileId)+"/revisions"),
 createTopologyRevision:(profileId,payload)=>request("/topologies/"+encode(profileId)+"/revisions",{method:"POST",body:JSON.stringify(payload)}),
 publishTopologyRevision:(profileId,payload)=>request("/topologies/"+encode(profileId)+"/publish",{method:"POST",body:JSON.stringify(payload)}),
 topologyPresentationRevisions:(profileId,revisionId)=>request("/topologies/"+encode(profileId)+"/revisions/"+encode(revisionId)+"/presentation-revisions"),
 createTopologyPresentationRevision:(profileId,revisionId,payload)=>request("/topologies/"+encode(profileId)+"/revisions/"+encode(revisionId)+"/presentation-revisions",{method:"POST",body:JSON.stringify(payload)}),
 publishTopologyPresentationRevision:(profileId,presentationId)=>request("/topologies/"+encode(profileId)+"/presentation-revisions/"+encode(presentationId)+"/publish",{method:"POST",body:"{}"}),
 topologyProviderBinding:labId=>request("/labs/"+encode(labId)+"/provider-binding"),
 bindTopologyProvider:(labId,payload)=>request("/labs/"+encode(labId)+"/provider-binding",{method:"PUT",body:JSON.stringify(payload),headers:{"Idempotency-Key":newKey()}}),
 archiveTopologyProvider:labId=>request("/labs/"+encode(labId)+"/provider-binding",{method:"DELETE",headers:{"Idempotency-Key":newKey()}}),
 topologyProviderCatalog:labId=>request("/labs/"+encode(labId)+"/provider-catalog"),
 providerObservations:(labId,limit=40)=>request("/labs/"+encode(labId)+"/provider-observations"+query({limit})),
 captureProviderObservation:labId=>request("/labs/"+encode(labId)+"/provider-observations",{method:"POST",headers:{"Idempotency-Key":newKey()},body:"{}"}),
 topologyProviderInterfaces:(labId,nodeId)=>request("/labs/"+encode(labId)+"/provider-nodes/"+encode(nodeId)+"/interfaces"),
 planTopologyApply:(profileId,payload)=>request("/topologies/"+encode(profileId)+"/plan",{method:"POST",body:JSON.stringify(payload)}),
 applyTopology:(profileId,payload)=>request("/topologies/"+encode(profileId)+"/apply",{method:"POST",body:JSON.stringify(payload)}),
 reconcileTopology:(profileId,revisionId)=>request("/topologies/"+encode(profileId)+"/reconciliation"+query({revision_id:revisionId})),
 topologyApplies:profileId=>request("/topologies/"+encode(profileId)+"/applies"),
 operateTopologyNode:(profileId,nodeId,action)=>request("/topologies/"+encode(profileId)+"/nodes/"+encode(nodeId)+"/"+encode(action).toLowerCase(),{method:"POST",body:"{}"}),
 createDevice:payload=>request("/devices",{method:"POST",body:JSON.stringify(payload)}),
 updateDevice:(id,payload)=>request("/devices/"+encode(id),{method:"PATCH",body:JSON.stringify(payload)}),
 device:id=>request("/devices/"+encode(id)),
 deviceObservations:(id,limit=50)=>request("/devices/"+encode(id)+"/observations"+query({limit})),
 captureDeviceObservation:id=>request("/devices/"+encode(id)+"/observations",{method:"POST",headers:{"Idempotency-Key":newKey()},body:"{}"}),
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

 configurationDeploymentPlan:(profileId,payload)=>request("/configuration/profiles/"+encode(profileId)+"/deploy-plan",{method:"POST",body:JSON.stringify(payload)}),
 deployConfiguration:(profileId,payload)=>request("/configuration/profiles/"+encode(profileId)+"/deploy",{method:"POST",body:JSON.stringify(payload)}),
 configurationDeploymentHistory:deviceId=>request("/configuration/devices/"+encode(deviceId)+"/deployments"),
 performancePolicies:projectId=>request("/performance/policies"+query({project_id:projectId})),
 createPerformancePolicy:payload=>request("/performance/policies",{method:"POST",body:JSON.stringify(payload)}),
 performanceRevisions:id=>request("/performance/policies/"+encode(id)+"/revisions"),
 createPerformanceRevision:(id,payload)=>request("/performance/policies/"+encode(id)+"/revisions",{method:"POST",body:JSON.stringify(payload)}),
 publishPerformanceRevision:(id,payload)=>request("/performance/policies/"+encode(id)+"/publish",{method:"POST",body:JSON.stringify(payload)}),
 assignPerformanceRevision:(id,payload)=>request("/performance/policies/"+encode(id)+"/assign",{method:"POST",body:JSON.stringify(payload)}),
 performanceAssignments:projectId=>request("/performance/assignments"+query({project_id:projectId})),
 evaluatePerformancePolicy:payload=>request("/performance/evaluate",{method:"POST",body:JSON.stringify(payload)}),
 login:(username,password)=>request("/auth/login",{method:"POST",body:JSON.stringify({username,password})}),
 logout:()=>request("/auth/logout",{method:"POST"}),me:()=>request("/auth/me"),
 activity:()=>request("/auth/activity",{method:"POST",body:"{}"}),
 operationsOverview:(projectId,labId)=>request("/dashboard/operations-overview"+query({project_id:projectId,lab_id:labId})),
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
 runNetworkObservability:(id,options={})=>request("/runs/"+encode(id)+"/network-observability",options),
 healthForRun:(id,options={})=>request("/runs/"+encode(id)+"/health",options),
 labHealth:(id,options={})=>request("/labs/"+encode(id)+"/health",options),
 artifacts:(params={},options={})=>request("/artifacts"+query(params),options),artifact:id=>request("/artifacts/"+encode(id)),
 artifactDownloadUrl:id=>(resolvedBase||configuredBase)+"/artifacts/"+encode(id)+"/download",
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
