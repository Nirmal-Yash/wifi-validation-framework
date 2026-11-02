import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {act,cleanup,render,screen} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";

vi.mock("@/api",()=>({
 api:{me:vi.fn(),login:vi.fn(),logout:vi.fn(),activity:vi.fn().mockResolvedValue({active:true})},
 clearCsrfToken:vi.fn(),
}));
import {api,clearCsrfToken} from "@/api";
import {SessionProvider,useSession} from "@/auth/session-provider";

const profile={username:"owner",role:"OWNER",projects:["*"]};
const channels=[];
class TestBroadcastChannel{
 constructor(name){this.name=name;this.onmessage=null;this.postMessage=vi.fn();this.close=vi.fn();channels.push(this);}
 send(data){this.onmessage?.({data});}
}
function SessionProbe(){
 const{status,user,warningVisible}=useSession();
 return <output>{status}:{user?.username||"none"}:{warningVisible?"warning":"normal"}</output>;
}
function mountSession(){
 const client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0},mutations:{retry:false}}});
 const view=render(<QueryClientProvider client={client}><SessionProvider><SessionProbe/></SessionProvider></QueryClientProvider>);
 return {...view,client};
}
describe("cross-tab secure session lifecycle",()=>{
 beforeEach(()=>{vi.clearAllMocks();channels.length=0;vi.stubGlobal("BroadcastChannel",TestBroadcastChannel);});
 afterEach(()=>{cleanup();vi.unstubAllGlobals();});
 it("restores identity from the authenticated Runner API",async()=>{
  api.me.mockResolvedValueOnce(profile);
  const {client}=mountSession();
  expect(await screen.findByText("authenticated:owner:normal")).toBeTruthy();
  client.clear();
 });
 it("clears local identity and query cache on a logout broadcast",async()=>{
  api.me.mockResolvedValueOnce(profile);
  const {client}=mountSession();
  expect(await screen.findByText("authenticated:owner:normal")).toBeTruthy();
  await act(async()=>{channels[0].send({type:"logout"});});
  expect(await screen.findByText("anonymous:none:normal")).toBeTruthy();
  expect(clearCsrfToken).toHaveBeenCalled();
  expect(api.logout).not.toHaveBeenCalled();
  client.clear();
 });
 it("revalidates the cookie when another tab broadcasts a login",async()=>{
  api.me.mockRejectedValueOnce({status:401,code:"UNAUTHENTICATED"});
  api.me.mockResolvedValueOnce(profile);
  const {client}=mountSession();
  expect(await screen.findByText("anonymous:none:normal")).toBeTruthy();
  await act(async()=>{channels[0].send({type:"login"});});
  expect(await screen.findByText("authenticated:owner:normal")).toBeTruthy();
  expect(api.me).toHaveBeenCalledTimes(2);
  client.clear();
 });
});
