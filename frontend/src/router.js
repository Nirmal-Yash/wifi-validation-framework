export function routeFor(pathname=window.location.pathname){
  const path=pathname.replace(/\/+$/,"")||"/";
  if(path==="/")return{name:"dashboard"};
  if(path==="/runs")return{name:"runs"};
  if(path.startsWith("/runs/")&&path.includes("/tests/")){const parts=path.split("/").filter(Boolean);return{name:"test",runId:parts[1],testResultId:parts[3]};}
  if(path.startsWith("/runs/"))return{name:"run",runId:path.split("/").filter(Boolean)[1]};
  if(path==="/regressions")return{name:"regressions"};
  if(path==="/performance")return{name:"performance"};
  if(path==="/telemetry")return{name:"telemetry"};
  if(path==="/lab-health")return{name:"lab-health"};
  if(path==="/artifacts")return{name:"artifacts"};
  if(path==="/baselines")return{name:"baselines"};
  if(path==="/operations")return{name:"operations"};
  if(path==="/readiness")return{name:"readiness"};
  return{name:"not-found"};
}
export function navigate(to){window.history.pushState({},"",to);window.dispatchEvent(new PopStateEvent("popstate"));}