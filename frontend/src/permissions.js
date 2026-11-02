export const ROLE_PERMISSIONS=Object.freeze({
 OWNER:Object.freeze(["view","execute","admin","owner"]),
 ADMIN:Object.freeze(["view","execute","admin"]),
 OPERATOR:Object.freeze(["view","execute"]),
 VIEWER:Object.freeze(["view"]),
});
export const ROUTE_PERMISSIONS=Object.freeze({
 dashboard:"view",runs:"view",run:"view",test:"view",artifacts:"view",readiness:"view",
 regressions:"view",performance:"view",telemetry:"view","lab-health":"view",
 baselines:"admin",operations:"execute",
});
export const canPerform=(role,permission)=>(ROLE_PERMISSIONS[String(role||"").toUpperCase()]||[]).includes(permission);
export const canView=role=>canPerform(role,"view");
export const canExecute=role=>canPerform(role,"execute");
export const canAdmin=role=>canPerform(role,"admin");
export const canOwner=role=>canPerform(role,"owner");
export const canAccessRoute=(role,routeName)=>{
 const required=ROUTE_PERMISSIONS[routeName];
 return Boolean(required&&canPerform(role,required));
};
