import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {cleanup,render,screen} from "@testing-library/react";
import {afterEach,describe,expect,it} from "vitest";
import {useAsyncLoader} from "../hooks";

function ParallelLoaders(){
 const run=useAsyncLoader(async()=>({kind:"run",run_id:"run-123"}),["run-123"]);
 const tests=useAsyncLoader(async()=>({kind:"tests",run_id:"run-123"}),["run-123"]);
 return <div><output data-testid="run">{run.data?.kind||"loading"}</output><output data-testid="tests">{tests.data?.kind||"loading"}</output></div>;
}
describe("server-state query identity",()=>{
 afterEach(()=>cleanup());
 it("keeps separate resources isolated when their dependency identifiers match",async()=>{
  const client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
  render(<QueryClientProvider client={client}><ParallelLoaders/></QueryClientProvider>);
  expect(await screen.findByText("run",{selector:"output"})).toBeTruthy();
  expect(await screen.findByText("tests",{selector:"output"})).toBeTruthy();
  const queries=client.getQueryCache().getAll();
  expect(queries).toHaveLength(2);
  expect(queries[0].queryKey).not.toEqual(queries[1].queryKey);
  expect(queries.every(item=>item.queryKey.includes("run-123"))).toBe(true);
  client.clear();
 });
});
