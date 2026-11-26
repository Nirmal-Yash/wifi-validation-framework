import {describe,it,expect} from "vitest";
import {layoutPipelineGraph,normalizePipelineSteps} from "../pipeline-graph";

const steps=[
 {key:"prepare",type:"WIFI_LAB_PROVISION"},
 {key:"validate",type:"VALIDATION_RUN",depends_on:[{step_key:"prepare",outcome:"SUCCESS"}]},
 {key:"recover",type:"PROVIDER_RECONCILE",depends_on:[{step_key:"prepare",outcome:"FAILURE"}]},
 {key:"report",type:"VALIDATION_RUN",depends_on:[{step_key:"validate",outcome:"COMPLETED"}]},
];

describe("pipeline dependency graph",()=>{
 it("keeps historical definitions sequential",()=>{
  expect(normalizePipelineSteps([{key:"one"},{key:"two"},{key:"three"}]).map(s=>s.depends_on)).toEqual([
   [],[{step_key:"one",outcome:"SUCCESS"}],[{step_key:"two",outcome:"SUCCESS"}]
  ]);
 });
 it("preserves explicit parallel roots and conditional edges",()=>{
  const normalized=normalizePipelineSteps([{key:"a",depends_on:[]},{key:"b",depends_on:[]}]);
  expect(normalized.map(s=>s.depends_on)).toEqual([[],[]]);
 });
 it("places dependencies before their children and exposes all edges",()=>{
  const graph=layoutPipelineGraph(steps);
  expect(graph.positions.prepare.x).toBeLessThan(graph.positions.validate.x);
  expect(graph.positions.prepare.x).toBeLessThan(graph.positions.recover.x);
  expect(graph.positions.validate.x).toBeLessThan(graph.positions.report.x);
  expect(graph.edges.map(edge=>edge.outcome)).toEqual(["SUCCESS","FAILURE","COMPLETED"]);
 });
});
