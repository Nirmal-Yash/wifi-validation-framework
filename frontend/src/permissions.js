export const ROLE_PERMISSIONS=Object.freeze({
 OWNER:Object.freeze(["view","execute","admin","owner"]),
 ADMIN:Object.freeze(["view","execute","admin"]),
 OPERATOR:Object.freeze(["view","execute"]),
 VIEWER:Object.freeze(["view"]),
});
export const ROUTE_PERMISSIONS=Object.freeze({
 dashboard:["workspace.read"],runs:["workspace.read"],run:["workspace.read"],test:["workspace.read"],
 artifacts:["workspace.read"],readiness:["workspace.read"],regressions:["workspace.read"],
 performance:["workspace.read"],telemetry:["workspace.read"],"lab-health":["workspace.read"],
 baselines:["baselines.manage"],operations:["runs.execute","firmware.manage"],
 workspace:["workspace.read"],
 credentials:["credentials.read"],configuration:["configurations.read"],
 administration:["users.read","roles.read","permissions.read","audit.read"],
});
const LEGACY_PERMISSION_ALIAS=Object.freeze({
 "workspace.read":"view","projects.read":"view","labs.read":"view","runs.read":"view",
 "evidence.read":"view","quality.read":"view","runs.execute":"execute",
 "firmware.manage":"execute","baselines.manage":"admin","workspace.manage":"admin",
 "users.read":"admin","users.manage":"admin","roles.read":"admin","roles.manage":"admin",
 "permissions.read":"admin","audit.read":"admin","system.manage":"owner",
 "organizations.manage":"admin","projects.manage":"admin","labs.manage":"admin",
 "members.manage":"admin",
 "credentials.read":"view","credentials.manage":"admin","credentials.verify":"execute",
 "configurations.read":"view","configurations.manage":"admin","configurations.publish":"admin",
});
export function canPerform(subject,permission){
 if(subject&&typeof subject==="object"&&Array.isArray(subject.permissions)){
  return subject.permissions.includes(permission);
 }
 const role=String(subject||"").toUpperCase();
 const legacyPermission=LEGACY_PERMISSION_ALIAS[permission]||permission;
 return (ROLE_PERMISSIONS[role]||[]).includes(legacyPermission);
}
export const canView=subject=>canPerform(subject,"workspace.read");
export const canExecute=subject=>canPerform(subject,"runs.execute");
export const canAdmin=subject=>canPerform(subject,"workspace.manage");
export const canOwner=subject=>canPerform(subject,"system.manage");
export const canAccessRoute=(subject,routeName)=>{
 const required=ROUTE_PERMISSIONS[routeName];
 return Boolean(required&&required.some(permission=>canPerform(subject,permission)));
};
