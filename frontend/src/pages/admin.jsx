import React,{useEffect,useMemo,useState} from "react";
import {api} from "@/api";
import {useAsyncLoader,useMutation} from "@/hooks";
import {formatDate} from "@/utils";
import {canPerform} from "@/permissions";
import {Button,DataTable,EmptyState,ErrorState,Field,InlineNotice,LoadingState,Section,StatusBadge} from "@/components/ui";

function TokenNotice({title,token,onDismiss}){
 if(!token)return null;
 return <InlineNotice tone="warning"><div className="token-notice">
  <strong>{title}</strong>
  <p>This token is displayed once. Copy it and deliver it through an approved secure channel. It is not emailed automatically.</p>
  <code className="token-value">{token}</code>
  <div className="button-row"><Button size="sm" variant="outline" onClick={()=>navigator.clipboard?.writeText(token)}>Copy token</Button><Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button></div>
 </div></InlineNotice>;
}

export function WorkspacePage({user}){
 const canCreateOrg=canPerform(user,"organizations.manage");
 const canCreateProject=canPerform(user,"projects.manage");
 const canManageLabs=canPerform(user,"labs.manage");
 const canManageMembers=canPerform(user,"members.manage");
 const organizations=useAsyncLoader(()=>api.workspaceOrganizations(),[],{queryKey:"workspace-organizations"});
 const [organizationId,setOrganizationId]=useState("");
 const projects=useAsyncLoader(()=>api.workspaceProjects({organization_id:organizationId}),[organizationId],{enabled:Boolean(organizationId),queryKey:"workspace-projects"});
 const [projectId,setProjectId]=useState("");
 const [showOrgForm,setShowOrgForm]=useState(false);
 const [showProjectForm,setShowProjectForm]=useState(false);
 const [organizationForm,setOrganizationForm]=useState({slug:"",name:""});
 const [projectForm,setProjectForm]=useState({slug:"",name:""});
 const [labForm,setLabForm]=useState({name:"",provider_id:"gns3"});
 const [memberForm,setMemberForm]=useState({username:"",role_id:"project_viewer"});
 const mutation=useMutation();
 const users=useAsyncLoader(()=>api.identityUsers(),[],{queryKey:"identity-users",enabled:canManageMembers});
 const projectRoles=useAsyncLoader(()=>api.identityRoles("PROJECT"),[],{queryKey:"project-roles"});
 const selectedProject=(projects.data?.items||[]).find(item=>item.project_id===projectId)||null;
 const members=useAsyncLoader(()=>projectId?api.workspaceMembers(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"project-members"});
 const labs=useAsyncLoader(()=>projectId?api.workspaceLabs(projectId):Promise.resolve({items:[]}),[projectId],{enabled:Boolean(projectId),queryKey:"project-labs"});
 const refresh=async()=>Promise.all([organizations.reload(),projects.reload(),members.reload(),labs.reload(),users.reload()]);
 const createOrganization=async event=>{
  event.preventDefault();
  try{const item=await mutation.run(()=>api.createOrganization(organizationForm));setOrganizationId(item.organization_id);setOrganizationForm({slug:"",name:""});setShowOrgForm(false);await organizations.reload();}
  catch{}
 };
 const createProject=async event=>{
  event.preventDefault();
  if(!organizationId)return;
  try{const item=await mutation.run(()=>api.createProject({...projectForm,organization_id:organizationId}));setProjectId(item.project_id);setProjectForm({slug:"",name:""});setShowProjectForm(false);await projects.reload();}
  catch{}
 };
 const createLab=async event=>{
  event.preventDefault();
  try{await mutation.run(()=>api.createWorkspaceLab(projectId,labForm));setLabForm({name:"",provider_id:"gns3"});await labs.reload();}
  catch{}
 };
 const addMember=async event=>{
  event.preventDefault();
  try{await mutation.run(()=>api.addWorkspaceMember(projectId,{username:memberForm.username,role_id:memberForm.role_id}));setMemberForm({username:"",role_id:"project_viewer"});await members.reload();}
  catch{}
 };
 const setMemberRole=async(item,roleId)=>{
  try{await mutation.run(()=>api.assignProjectRole(projectId,item.username,{role_id:roleId}));await members.reload();}
  catch{}
 };
 const removeMember=async username=>{
  try{await mutation.run(()=>api.removeWorkspaceMember(projectId,username));await members.reload();}
  catch{}
 };
 if(organizations.loading&&!organizations.data)return <LoadingState label="Loading workspace administration…"/>;
 if(organizations.error&&!organizations.data)return <ErrorState error={organizations.error} onRetry={organizations.reload}/>;
 return <div className="page-stack">
  <div className="page-actions-row"><span className="context-caption">Organization → Project → Lab · persisted ownership boundaries</span><span className="role-chip">{user?.role}</span></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:mutation.success?<InlineNotice tone="success">Workspace changes saved.</InlineNotice>:null}
  <Section title="Organizations" subtitle="Organizations group Projects. Access is derived from your assigned workspace scope." actions={canCreateOrg?<Button size="sm" variant="outline" onClick={()=>setShowOrgForm(value=>!value)}>{showOrgForm?"Cancel":"New organization"}</Button>:null}>
   <div className="filter-grid"><Field label="Organization"><select value={organizationId} onChange={event=>{setOrganizationId(event.target.value);setProjectId("");}}><option value="">Select organization</option>{(organizations.data?.items||[]).map(item=><option value={item.organization_id} key={item.organization_id}>{item.name} · {item.slug} · {item.status}</option>)}</select></Field></div>
   {showOrgForm?<form className="form-grid compact" onSubmit={createOrganization}><Field label="Name" required><input value={organizationForm.name} onChange={event=>setOrganizationForm({...organizationForm,name:event.target.value})} required maxLength={120}/></Field><Field label="Slug" required><input value={organizationForm.slug} onChange={event=>setOrganizationForm({...organizationForm,slug:event.target.value})} pattern="[a-z0-9][a-z0-9-]*" required maxLength={64}/></Field><div className="form-actions"><Button type="submit" loading={mutation.loading}>Create organization</Button></div></form>:null}
   {!organizations.data?.items?.length?<EmptyState title="No organizations in scope" message="An Owner can create an organization or assign you to a Project."/>:null}
  </Section>
  <Section title="Projects" subtitle="Project membership controls access to Runs, Labs, configuration and evidence." actions={canCreateProject?<Button size="sm" variant="outline" disabled={!organizationId} onClick={()=>setShowProjectForm(value=>!value)}>{showProjectForm?"Cancel":"New project"}</Button>:null}>
   <Field label="Project"><select value={projectId} onChange={event=>setProjectId(event.target.value)} disabled={!organizationId}><option value="">Select project</option>{(projects.data?.items||[]).map(item=><option value={item.project_id} key={item.project_id}>{item.name} · {item.slug}</option>)}</select></Field>
   {showProjectForm?<form className="form-grid compact" onSubmit={createProject}><Field label="Name" required><input value={projectForm.name} onChange={event=>setProjectForm({...projectForm,name:event.target.value})} required maxLength={120}/></Field><Field label="Slug" required><input value={projectForm.slug} onChange={event=>setProjectForm({...projectForm,slug:event.target.value})} pattern="[a-z0-9][a-z0-9-]*" required maxLength={64}/></Field><div className="form-actions"><Button type="submit" loading={mutation.loading}>Create project</Button></div></form>:null}
   {selectedProject?<InlineNotice tone="info">Selected: <strong>{selectedProject.name}</strong> · {selectedProject.project_id} · {selectedProject.status}</InlineNotice>:null}
  </Section>
  {selectedProject?<>
   <Section title="Labs" subtitle="Lab records identify provider targets. Saving a Lab here does not provision or mutate a GNS3 project.">
    {canManageLabs?<form className="filter-grid" onSubmit={createLab}><Field label="Lab name" required><input value={labForm.name} onChange={event=>setLabForm({...labForm,name:event.target.value})} required/></Field><Field label="Provider ID" required><input value={labForm.provider_id} onChange={event=>setLabForm({...labForm,provider_id:event.target.value})} required placeholder="gns3"/></Field><div className="filter-actions"><Button type="submit" loading={mutation.loading}>Add Lab</Button></div></form>:null}
    <DataTable rows={labs.data?.items||[]} rowKey={item=>item.lab_id} columns={[{key:"name",label:"Lab"},{key:"lab_id",label:"Lab ID",render:item=><span className="mono">{item.lab_id}</span>},{key:"provider_id",label:"Provider"},{key:"topology_version",label:"Topology revision"},{key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>}]} emptyTitle="No Labs" emptyMessage="Create a Lab record for this Project or request Lab administration access."/>
   </Section>
   <Section title="Project membership" subtitle="Membership and custom Project roles are re-evaluated by the API on every request.">
    {canManageMembers?<form className="filter-grid" onSubmit={addMember}><Field label="Account" required><select value={memberForm.username} onChange={event=>setMemberForm({...memberForm,username:event.target.value})} required><option value="">Select account</option>{(users.data?.items||[]).filter(item=>["ACTIVE","INVITED"].includes(item.status)).map(item=><option key={item.username} value={item.username}>{item.display_name||item.username} · {item.status}</option>)}</select></Field><Field label="Project role" required><select value={memberForm.role_id} onChange={event=>setMemberForm({...memberForm,role_id:event.target.value})}>{(projectRoles.data?.items||[]).map(item=><option key={item.role_id} value={item.role_id}>{item.name}{item.is_system?" · built-in":""}</option>)}</select></Field><div className="filter-actions"><Button type="submit" loading={mutation.loading}>Add member</Button></div></form>:null}
    <DataTable rows={members.data?.items||[]} rowKey={item=>item.username} columns={[
     {key:"username",label:"Account"},
     {key:"role",label:"Legacy role",render:item=><StatusBadge value={item.role}/>},
     {key:"role_id",label:"Effective Project role",render:item=>canManageMembers?<select aria-label={"Role for "+item.username} value={item.role_id||"project_viewer"} onChange={event=>setMemberRole(item,event.target.value)}>{(projectRoles.data?.items||[]).map(role=><option key={role.role_id} value={role.role_id}>{role.name}</option>)}</select>:item.role_id||item.role},
     {key:"created_by",label:"Assigned by"},
     {key:"created_at",label:"Assigned at",render:item=>formatDate(item.created_at)},
     {key:"actions",label:"Actions",render:item=>canManageMembers?<Button size="sm" variant="ghost" disabled={mutation.loading} onClick={()=>removeMember(item.username)}>Revoke</Button>:"—"},
    ]} emptyTitle="No members" emptyMessage="No users are assigned to this Project."/>
   </Section>
  </>:null}
 </div>;
}

function UserActions({item,roles,onAssign,onStatus,onReset,onRevoke,loading}){
 const [roleId,setRoleId]=useState(item.global_role_id||"global_viewer");
 return <div className="admin-row-actions">
  <select aria-label={"Global role for "+item.username} value={roleId} onChange={event=>setRoleId(event.target.value)}>{roles.map(role=><option value={role.role_id} key={role.role_id}>{role.name}</option>)}</select>
  <Button size="sm" variant="outline" disabled={loading||roleId===item.global_role_id} onClick={()=>onAssign(item.username,roleId)}>Apply role</Button>
  {item.status==="ACTIVE"?<Button size="sm" variant="ghost" disabled={loading} onClick={()=>onStatus(item.username,"SUSPENDED")}>Suspend</Button>:item.status==="SUSPENDED"?<Button size="sm" variant="outline" disabled={loading} onClick={()=>onStatus(item.username,"ACTIVE")}>Reactivate</Button>:null}
  {item.status==="ACTIVE"?<Button size="sm" variant="ghost" disabled={loading} onClick={()=>onReset(item.username)}>Reset password</Button>:null}
  <Button size="sm" variant="ghost" disabled={loading} onClick={()=>onRevoke(item.username)}>Revoke sessions</Button>
 </div>;
}

export function AdministrationPage({user}){
 const canReadUsers=canPerform(user,"users.read");
 const canManageUsers=canPerform(user,"users.manage");
 const canReadRoles=canPerform(user,"roles.read")&&canPerform(user,"permissions.read");
 const canManageRoles=canPerform(user,"roles.manage");
 const canReadAudit=canPerform(user,"audit.read");
 const users=useAsyncLoader(()=>canReadUsers?api.identityUsers():Promise.resolve({items:[]}),[canReadUsers],{enabled:canReadUsers,queryKey:"admin-users"});
 const roles=useAsyncLoader(()=>canReadRoles?api.identityRoles():Promise.resolve({items:[]}),[canReadRoles],{enabled:canReadRoles,queryKey:"admin-roles"});
 const permissions=useAsyncLoader(()=>canReadRoles?api.identityPermissions():Promise.resolve({items:[]}),[canReadRoles],{enabled:canReadRoles,queryKey:"admin-permissions"});
 const audit=useAsyncLoader(()=>canReadAudit?api.identityAudit({limit:100}):Promise.resolve({items:[]}),[canReadAudit],{enabled:canReadAudit,queryKey:"admin-audit"});
 const mutation=useMutation();
 const [invite,setInvite]=useState({username:"",email:"",display_name:"",global_role_id:"global_viewer"});
 const [newRole,setNewRole]=useState({name:"",scope_type:"PROJECT",description:""});
 const [roleId,setRoleId]=useState("");
 const [permissionCodes,setPermissionCodes]=useState([]);
 const [issuedToken,setIssuedToken]=useState(null);
 const [lastAction,setLastAction]=useState("");
 const globalRoles=useMemo(()=>(roles.data?.items||[]).filter(item=>item.scope_type==="GLOBAL"),[roles.data]);
 const customRoles=useMemo(()=>(roles.data?.items||[]).filter(item=>!item.is_system),[roles.data]);
 const selectedRole=(roles.data?.items||[]).find(item=>item.role_id===roleId)||null;
 useEffect(()=>{setPermissionCodes(selectedRole?.permissions||[]);},[roleId,roles.data]);
 const reload=async()=>Promise.all([users.reload(),roles.reload(),permissions.reload(),audit.reload()]);
 const inviteUser=async event=>{
  event.preventDefault();
  try{const result=await mutation.run(()=>api.inviteIdentityUser(invite));setIssuedToken({title:"Invitation token for "+result.user.username,token:result.invitation_token});setInvite({username:"",email:"",display_name:"",global_role_id:"global_viewer"});await users.reload();await audit.reload();}
  catch{}
 };
 const assignRole=async(username,id)=>{
  try{await mutation.run(()=>api.assignGlobalRole(username,{role_id:id}));setLastAction("Global role updated for "+username);await users.reload();await audit.reload();}
  catch{}
 };
 const changeStatus=async(username,status)=>{
  try{await mutation.run(()=>api.updateIdentityUser(username,{status}));setLastAction("Account "+username+" is now "+status+".");await users.reload();await audit.reload();}
  catch{}
 };
 const resetPassword=async username=>{
  try{const result=await mutation.run(()=>api.resetIdentityPassword(username));setIssuedToken({title:"Password reset token for "+username,token:result.reset_token});await audit.reload();}
  catch{}
 };
 const revokeSessions=async username=>{
  try{const result=await mutation.run(()=>api.revokeIdentitySessions(username));setLastAction(result.revoked_sessions+" session(s) revoked for "+username+".");await audit.reload();}
  catch{}
 };
 const createRole=async event=>{
  event.preventDefault();
  try{const result=await mutation.run(()=>api.createIdentityRole(newRole));setRoleId(result.role_id);setNewRole({name:"",scope_type:"PROJECT",description:""});await roles.reload();await audit.reload();}
  catch{}
 };
 const savePermissions=async()=>{
  if(!selectedRole)return;
  try{await mutation.run(()=>api.setRolePermissions(selectedRole.role_id,{permissions:permissionCodes}));setLastAction("Permissions updated for "+selectedRole.name+".");await roles.reload();await audit.reload();}
  catch{}
 };
 const deleteRole=async()=>{
  if(!selectedRole||selectedRole.is_system)return;
  if(!window.confirm("Delete the custom role "+selectedRole.name+"? It must have no assignments."))return;
  try{await mutation.run(()=>api.deleteIdentityRole(selectedRole.role_id));setRoleId("");setLastAction("Role deleted.");await roles.reload();await audit.reload();}
  catch{}
 };
 if(canReadUsers&&users.loading&&!users.data)return <LoadingState label="Loading account administration…"/>;
 return <div className="page-stack">
  <div className="page-actions-row"><span className="context-caption">Persistent accounts · scoped roles · audited administrative actions</span><span className="role-chip">{user?.role}</span></div>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:lastAction?<InlineNotice tone="success">{lastAction}</InlineNotice>:mutation.success?<InlineNotice tone="success">Administrative change saved.</InlineNotice>:null}
  <TokenNotice {...(issuedToken||{})} onDismiss={()=>setIssuedToken(null)}/>
  {canManageUsers?<Section title="Invite a user" subtitle="Invitation tokens expire after 24 hours and are returned once for secure manual delivery.">
   <form className="form-grid" onSubmit={inviteUser}>
    <Field label="Username" required><input value={invite.username} onChange={event=>setInvite({...invite,username:event.target.value})} minLength={2} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9._-]+" required/></Field>
    <Field label="Display name" required><input value={invite.display_name} onChange={event=>setInvite({...invite,display_name:event.target.value})} maxLength={120} required/></Field>
    <Field label="Email"><input type="email" value={invite.email} onChange={event=>setInvite({...invite,email:event.target.value})}/></Field>
    <Field label="Global role" required><select value={invite.global_role_id} onChange={event=>setInvite({...invite,global_role_id:event.target.value})}>{globalRoles.map(role=><option key={role.role_id} value={role.role_id}>{role.name}</option>)}</select></Field>
    <div className="form-actions"><Button type="submit" loading={mutation.loading}>Create invitation</Button></div>
   </form>
  </Section>:null}
  {canReadUsers?<Section title="Accounts" subtitle={(users.data?.items||[]).length+" persisted account(s) · password hashes and token hashes are never returned"}>
   <DataTable rows={users.data?.items||[]} rowKey={item=>item.username} columns={[
    {key:"username",label:"Account",render:item=><><strong>{item.display_name||item.username}</strong><div className="muted mono">{item.username}</div></>},
    {key:"email",label:"Email"},
    {key:"global_role",label:"Global role",render:item=><StatusBadge value={item.global_role||"UNASSIGNED"}/>},
    {key:"status",label:"Status",render:item=><StatusBadge value={item.status}/>},
    {key:"created_at",label:"Created",render:item=>formatDate(item.created_at)},
    {key:"actions",label:"Administration",render:item=>canManageUsers?<UserActions item={item} roles={globalRoles} loading={mutation.loading} onAssign={assignRole} onStatus={changeStatus} onReset={resetPassword} onRevoke={revokeSessions}/>:item.status},
   ]} emptyTitle="No persistent accounts" emptyMessage="Invite a user to create a database-backed identity."/>
  </Section>:null}
  {canReadRoles?<Section title="Roles and permission registry" subtitle="Built-in roles are read-only. Create a custom Global or Project role, then grant only permissions within your own authority.">
   <div className="filter-grid">
    <Field label="Role"><select value={roleId} onChange={event=>setRoleId(event.target.value)}><option value="">Select role</option>{(roles.data?.items||[]).map(role=><option key={role.role_id} value={role.role_id}>{role.scope_type} · {role.name}{role.is_system?" · built-in":""}</option>)}</select></Field>
   </div>
   {canManageRoles?<form className="form-grid compact" onSubmit={createRole}>
    <Field label="New role name" required><input value={newRole.name} onChange={event=>setNewRole({...newRole,name:event.target.value})} minLength={2} maxLength={48} required/></Field>
    <Field label="Scope"><select value={newRole.scope_type} onChange={event=>setNewRole({...newRole,scope_type:event.target.value})}><option>PROJECT</option><option>GLOBAL</option></select></Field>
    <Field label="Description"><input value={newRole.description} onChange={event=>setNewRole({...newRole,description:event.target.value})} maxLength={240}/></Field>
    <div className="form-actions"><Button type="submit" variant="outline" loading={mutation.loading}>Create custom role</Button></div>
   </form>:null}
   {selectedRole?<div className="role-editor">
    <div className="role-editor-heading"><div><strong>{selectedRole.name}</strong><p>{selectedRole.description||"No description"} · {selectedRole.scope_type} scope</p></div><StatusBadge value={selectedRole.is_system?"BUILT_IN":"CUSTOM"}/></div>
    <div className="permission-grid">{(permissions.data?.items||[]).map(item=><label className="permission-option" key={item.code}><input type="checkbox" checked={permissionCodes.includes(item.code)} disabled={!canManageRoles||selectedRole.is_system} onChange={event=>setPermissionCodes(current=>event.target.checked?[...current,item.code]:current.filter(code=>code!==item.code))}/><span><strong>{item.code}</strong><small>{item.description}</small></span></label>)}</div>
    {canManageRoles&&!selectedRole.is_system?<div className="button-row"><Button loading={mutation.loading} onClick={savePermissions}>Save permissions</Button><Button variant="danger" loading={mutation.loading} onClick={deleteRole}>Delete role</Button></div>:<InlineNotice>Built-in permission sets are immutable. Create a custom role to change grants.</InlineNotice>}
   </div>:<EmptyState title="Select a role" message="Choose an existing role or create a custom role to inspect its permission set."/>}
   <DataTable rows={permissions.data?.items||[]} rowKey={item=>item.code} columns={[{key:"resource",label:"Resource"},{key:"action",label:"Action"},{key:"code",label:"Permission"},{key:"description",label:"Description"}]} emptyTitle="No permissions" emptyMessage="No registered permissions are available."/>
  </Section>:null}
  {canReadAudit?<Section title="Audit history" subtitle="Recent append-only identity and workspace administration events.">
   <DataTable rows={audit.data?.items||[]} rowKey={item=>item.audit_id} columns={[
    {key:"occurred_at",label:"When",render:item=>formatDate(item.occurred_at)},
    {key:"actor_username",label:"Actor"},
    {key:"action",label:"Action",render:item=><StatusBadge value={item.action}/>},
    {key:"resource_type",label:"Resource"},
    {key:"resource_id",label:"Resource ID",render:item=><span className="mono">{item.resource_id}</span>},
    {key:"details",label:"Details",render:item=><code className="audit-details">{JSON.stringify(item.details||{})}</code>},
   ]} emptyTitle="No audit events" emptyMessage="Identity and workspace changes will appear here."/>
  </Section>:null}
 </div>;
}


export function AccountAccessPage({mode="activate"}){
 const [token,setToken]=useState("");
 const [password,setPassword]=useState("");
 const [confirmPassword,setConfirmPassword]=useState("");
 const [complete,setComplete]=useState(false);
 const mutation=useMutation();
 const isReset=mode==="reset";
 const submit=async event=>{
  event.preventDefault();
  if(password!==confirmPassword)return;
  try{
   if(isReset)await mutation.run(()=>api.completePasswordReset({token,password}));
   else await mutation.run(()=>api.acceptInvitation({token,password}));
   setComplete(true);
  }catch{}
 };
 return <div className="connection-shell"><section className="connection-panel" aria-labelledby="account-access-heading">
  <div className="brand"><span className="brand-mark">NR</span><span className="brand-wordmark"><strong>NetRegress</strong><small>LOCAL ACCOUNT SECURITY</small></span></div>
  <h1 id="account-access-heading">{isReset?"Set a new password":"Activate your account"}</h1>
  <p>{isReset?"Use the one-time password-reset token supplied by your workspace Owner.":"Use the invitation token supplied by your workspace Owner to activate this local account."}</p>
  {mutation.error?<InlineNotice tone="danger">{mutation.error.message}</InlineNotice>:null}
  {complete?<InlineNotice tone="success">Your account is active. You can now sign in with your new password.</InlineNotice>:<form className="form-grid" onSubmit={submit}>
   <Field label={isReset?"Password reset token":"Invitation token"} required><input value={token} onChange={event=>setToken(event.target.value.trim())} autoComplete="off" required/></Field>
   <Field label="New password" hint="Use at least 12 characters." required><input type="password" value={password} onChange={event=>setPassword(event.target.value)} autoComplete="new-password" minLength={12} maxLength={1024} required/></Field>
   <Field label="Confirm password" required><input type="password" value={confirmPassword} onChange={event=>setConfirmPassword(event.target.value)} autoComplete="new-password" minLength={12} maxLength={1024} required/></Field>
   {password&&confirmPassword&&password!==confirmPassword?<InlineNotice tone="danger">The passwords do not match.</InlineNotice>:null}
   <div className="form-actions"><Button type="submit" loading={mutation.loading} disabled={!token||password.length<12||password!==confirmPassword}>{isReset?"Reset password":"Activate account"}</Button><a className="text-link" href="/">Back to sign in</a></div>
  </form>}
 </section></div>;
}
