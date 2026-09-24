import React,{useEffect,useState}from"react";
import{api}from"./api";

const canExecute=(role)=>role!=="VIEWER";
const terminalStatuses=new Set(["COMPLETED","FAILED","LAB_FAILED","CANCELLED","ABORTED"]);

function Login({onLogin}){
  const[u,setU]=useState("admin"),[p,setP]=useState(""),[e,setE]=useState("");
  return <div className="login"><form onSubmit={async x=>{x.preventDefault();try{await api.login(u,p);onLogin(await api.me())}catch(err){setE(err.message)}}}>
    <h1>NetRegress Runner</h1><input value={u} onChange={e=>setU(e.target.value)} placeholder="Username"/>
    <input type="password" value={p} onChange={e=>setP(e.target.value)} placeholder="Password"/>
    <button>Sign in</button>{e&&<p className="error">{e}</p>}
  </form></div>
}

function Runs({select,user}){
  const[d,setD]=useState({items:[]}),[e,setE]=useState("");
  const load=()=>api.runs().then(setD).catch(x=>setE(x.message));
  useEffect(()=>{load();const timer=setInterval(load,5000);return()=>clearInterval(timer)},[]);
  return <section><div className="toolbar"><h2>Runs</h2>{canExecute(user.role)&&<button onClick={()=>api.launch({firmware_version:"v1.0"}).then(load)}>Start Run</button>}</div>
    {e&&<p className="error">{e}</p>}<table><thead><tr><th>Run</th><th>Firmware</th><th>Status</th><th>Health</th><th>Outcome</th></tr></thead>
    <tbody>{(d.items||[]).map(r=><tr key={r.run_id} onClick={()=>select(r.run_id)}><td>{r.display_id}</td><td>{r.firmware_version}</td><td>{r.lifecycle_status}</td><td>{r.environment_health||"—"}</td><td>{r.business_outcome||"—"}</td></tr>)}</tbody></table>
  </section>
}

function Detail({id,back,user}){
  const[d,setD]=useState(null),[tab,setTab]=useState("summary"),[e,setE]=useState("");
  const load=()=>api.run(id).then(setD).catch(x=>setE(x.message));
  useEffect(()=>{load();const timer=setInterval(()=>{if(d&&!terminalStatuses.has(d.lifecycle_status))load()},2000);return()=>clearInterval(timer)},[id,d?.lifecycle_status]);
  if(!d)return <section>{e?<p className="error">{e}</p>:"Loading…"}</section>;
  const view=tab==="health"?d.health:tab==="tests"?d.test_counts:tab==="artifacts"?d.artifacts:d;
  return <section><button onClick={back}>← Runs</button><h2>{d.display_id}</h2>
    <div className="grid">{["lifecycle_status","business_outcome","environment_health","failure_class","configuration_hash"].map(k=><div className="card" key={k}><small>{k}</small><strong>{d[k]||"—"}</strong></div>)}</div>
    <div className="tabs">{["summary","tests","health","telemetry","artifacts"].map(t=><button className={tab===t?"active":""} onClick={()=>setTab(t)} key={t}>{t}</button>)}</div>
    <pre>{JSON.stringify(tab==="telemetry"?d.telemetry:view,null,2)}</pre>
    {canExecute(user.role)&&<div className="toolbar"><button onClick={()=>api.cancel(id,"cancelled from UI").then(load)}>Cancel</button><button onClick={()=>api.retry(id).then(()=>load())}>Retry</button></div>}
  </section>
}

function App(){
  const[user,setUser]=useState(undefined),[selected,setSelected]=useState(null);
  useEffect(()=>{api.me().then(setUser).catch(()=>setUser(null))},[]);
  if(user===undefined)return <main>Loading…</main>;
  if(!user)return <Login onLogin={setUser}/>;
  return <main><header><h1>NetRegress Runner</h1><div>{user.username} · {user.role} <button onClick={()=>api.logout().then(()=>setUser(null))}>Logout</button></div></header>
    {selected?<Detail id={selected} back={()=>setSelected(null)} user={user}/>:<Runs select={setSelected} user={user}/>}</main>
}

export default App;
