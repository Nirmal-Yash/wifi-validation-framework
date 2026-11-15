import {describe,expect,it} from "vitest";
import {canAccessRoute,canAdmin,canExecute,canOwner,canPerform,canView,ROLE_PERMISSIONS} from "../permissions";

describe("NetRegress RBAC presentation matrix",()=>{
 it("matches the server-defined role capabilities",()=>{
  expect(ROLE_PERMISSIONS).toEqual({
   OWNER:["view","execute","admin","owner"],
   ADMIN:["view","execute","admin"],
   OPERATOR:["view","execute"],
   VIEWER:["view"],
  });
 });
 it("allows Operators to execute Runs but not administer governance",()=>{
  expect(canExecute("OPERATOR")).toBe(true);
  expect(canAdmin("OPERATOR")).toBe(false);
  expect(canAccessRoute("OPERATOR","operations")).toBe(true);
  expect(canAccessRoute("OPERATOR","baselines")).toBe(false);
 });
 it("keeps Viewer access read-only",()=>{
  expect(canView("VIEWER")).toBe(true);
  expect(canAccessRoute("VIEWER","dashboard")).toBe(true);
  expect(canAccessRoute("VIEWER","runs")).toBe(true);
  expect(canAccessRoute("VIEWER","operations")).toBe(false);
  expect(canExecute("VIEWER")).toBe(false);
 });
 it("gives Admin governance rights but not Owner-only privileges",()=>{
  expect(canAdmin("ADMIN")).toBe(true);
  expect(canOwner("ADMIN")).toBe(false);
 });
 it("maps legacy roles to the Stage C performance permission matrix",()=>{
  expect(canPerform("VIEWER","performance.read")).toBe(true);
  expect(canPerform("OPERATOR","performance.read")).toBe(true);
  expect(canPerform("ADMIN","performance.manage")).toBe(true);
  expect(canPerform("OWNER","performance.publish")).toBe(true);
  expect(canPerform("OPERATOR","performance.manage")).toBe(false);
 });
 it("respects persistent permission lists over legacy role fallback",()=>{
  expect(canPerform({role:"OWNER",permissions:["performance.read"]},"performance.read")).toBe(true);
  expect(canPerform({role:"OWNER",permissions:["performance.read"]},"performance.publish")).toBe(false);
 });
 it("maps legacy roles to Stage D device inventory permissions",()=>{
  expect(canPerform("VIEWER","devices.read")).toBe(true);
  expect(canPerform("OPERATOR","devices.read")).toBe(true);
  expect(canPerform("ADMIN","devices.manage")).toBe(true);
  expect(canPerform("OWNER","devices.operate")).toBe(true);
  expect(canPerform("OPERATOR","devices.manage")).toBe(false);
  expect(canAccessRoute("VIEWER","devices")).toBe(true);
 });
 it("maps topology permissions to built-in roles",()=>{
  expect(canPerform("VIEWER","topology.read")).toBe(true);
  expect(canPerform("OPERATOR","topology.read")).toBe(true);
  expect(canPerform("ADMIN","topology.manage")).toBe(true);
  expect(canPerform("OWNER","topology.publish")).toBe(true);
  expect(canPerform("OPERATOR","topology.manage")).toBe(false);
 });
 it("fails closed for unknown roles, permissions and routes",()=>{
  expect(canPerform("UNKNOWN","view")).toBe(false);
  expect(canPerform("OWNER","unknown")).toBe(false);
  expect(canAccessRoute("OWNER","not-found")).toBe(false);
 });
});
