import {describe,expect,it} from "vitest";
import {
 DEFAULT_TOPOLOGY_VIEWPORT,fitTopologyViewport,zoomTopologyViewport,
} from "@/pages/topologies";

describe("topology viewport helpers",()=>{
 it("fits the empty topology to the canonical default view",()=>{
  expect(fitTopologyViewport([])).toEqual(DEFAULT_TOPOLOGY_VIEWPORT);
 });
 it("fits all node coordinates with a margin and valid bounds",()=>{
  const view=fitTopologyViewport([{x:100,y:120},{x:700,y:440}]);
  expect(view.width).toBeGreaterThanOrEqual(860);
  expect(view.height).toBeCloseTo(view.width*0.62);
  expect(view.x).toBeGreaterThanOrEqual(0);
  expect(view.y).toBeGreaterThanOrEqual(0);
  expect(view.x+view.width).toBeLessThanOrEqual(10000);
  expect(view.y+view.height).toBeLessThanOrEqual(10000);
 });
 it("zooms around the pointer anchor while preserving aspect ratio",()=>{
  const initial={x:100,y:80,width:1000,height:620};
  const zoomed=zoomTopologyViewport(initial,0.8,0.25,0.75);
  expect(zoomed.width).toBe(800);
  expect(zoomed.height).toBeCloseTo(496);
  const oldAnchor={x:initial.x+initial.width*0.25,y:initial.y+initial.height*0.75};
  const newAnchor={x:zoomed.x+zoomed.width*0.25,y:zoomed.y+zoomed.height*0.75};
  expect(newAnchor.x).toBeCloseTo(oldAnchor.x);
  expect(newAnchor.y).toBeCloseTo(oldAnchor.y);
 });
 it("clamps extreme zoom requests to supported bounds",()=>{
  expect(zoomTopologyViewport(DEFAULT_TOPOLOGY_VIEWPORT,0.001).width).toBe(250);
  expect(zoomTopologyViewport(DEFAULT_TOPOLOGY_VIEWPORT,100).width).toBe(2500);
 });
});
