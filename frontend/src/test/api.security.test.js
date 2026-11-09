import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {api,clearCsrfToken} from "../api";

const response=(payload,status=200,contentType="application/json")=>({
 status,ok:status>=200&&status<300,
 headers:{get:()=>contentType},
 json:async()=>payload,
});
const success=data=>response({data});
const failure=(code,message,status)=>response({error:{code,message,details:{}}},status);

describe("Runner API session and CSRF client",()=>{
 beforeEach(()=>{clearCsrfToken();});
 afterEach(()=>{clearCsrfToken();vi.unstubAllGlobals();});

 it("sends mutations with an in-memory CSRF token and idempotency key",async()=>{
  const fetchMock=vi.fn()
   .mockResolvedValueOnce(success({csrf_token:"csrf-in-memory"}))
   .mockResolvedValueOnce(success({process_id:1,status:"STARTED"}));
  vi.stubGlobal("fetch",fetchMock);
  await api.launch({firmware_version:"v1.0",tests:[]});
  expect(fetchMock).toHaveBeenCalledTimes(2);
  const [csrfUrl,csrfInit]=fetchMock.mock.calls[0];
  const [launchUrl,launchInit]=fetchMock.mock.calls[1];
  expect(csrfUrl).toBe("/api/v1/auth/csrf");
  expect(csrfInit.method).toBe("GET");
  expect(launchUrl).toBe("/api/v1/runs");
  expect(launchInit.credentials).toBe("same-origin");
  expect(launchInit.cache).toBe("no-store");
  expect(launchInit.headers["X-CSRF-Token"]).toBe("csrf-in-memory");
  expect(launchInit.headers["Idempotency-Key"]).toBeTruthy();
  expect(localStorage.getItem("csrf-in-memory")).toBeNull();
 });

 it("refreshes CSRF once after CSRF_REQUIRED and preserves the idempotency key",async()=>{
  const fetchMock=vi.fn()
   .mockResolvedValueOnce(success({csrf_token:"stale-csrf"}))
   .mockResolvedValueOnce(failure("CSRF_REQUIRED","refresh required",403))
   .mockResolvedValueOnce(success({csrf_token:"fresh-csrf"}))
   .mockResolvedValueOnce(success({process_id:2,status:"STARTED"}));
  vi.stubGlobal("fetch",fetchMock);
  await api.launch({firmware_version:"v1.0",tests:[]});
  expect(fetchMock).toHaveBeenCalledTimes(4);
  const firstMutation=fetchMock.mock.calls[1][1].headers;
  const retryMutation=fetchMock.mock.calls[3][1].headers;
  expect(firstMutation["X-CSRF-Token"]).toBe("stale-csrf");
  expect(retryMutation["X-CSRF-Token"]).toBe("fresh-csrf");
  expect(retryMutation["Idempotency-Key"]).toBe(firstMutation["Idempotency-Key"]);
 });

 it("sends an authenticated heartbeat without persisting browser credentials",async()=>{
  const fetchMock=vi.fn()
   .mockResolvedValueOnce(success({csrf_token:"csrf-activity"}))
   .mockResolvedValueOnce(success({active:true}));
  vi.stubGlobal("fetch",fetchMock);
  await api.activity();
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/auth/activity");
  expect(fetchMock.mock.calls[1][1].headers["X-CSRF-Token"]).toBe("csrf-activity");
  expect(fetchMock.mock.calls[1][1].credentials).toBe("same-origin");
 });

 it("broadcasts session expiry after a protected endpoint returns 401",async()=>{
  const fetchMock=vi.fn().mockResolvedValueOnce(failure("UNAUTHENTICATED","session expired",401));
  vi.stubGlobal("fetch",fetchMock);
  const listener=vi.fn();
  window.addEventListener("netregress:auth-expired",listener);
  await expect(api.runs()).rejects.toMatchObject({status:401,code:"UNAUTHENTICATED"});
  expect(listener).toHaveBeenCalledTimes(1);
  window.removeEventListener("netregress:auth-expired",listener);
 });

 it("exposes the release-gate and waiver endpoints",async()=>{
  const fetchMock=vi.fn().mockResolvedValueOnce(success({accepted:false,issues:[]})).mockResolvedValueOnce(success({items:[]}));
  vi.stubGlobal("fetch",fetchMock);
  await api.releaseGate("run 1","base/1");
  await api.waivers();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/run%201/release-gate?baseline_run_id=base%2F1");
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/waivers");
 });
 it("rejects non-JSON proxy errors instead of interpreting them as API data",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response(null,502,"text/html")));
  await expect(api.health()).rejects.toMatchObject({status:502,code:"INVALID_API_RESPONSE"});
 });
});
