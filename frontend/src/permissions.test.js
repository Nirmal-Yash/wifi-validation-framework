import {describe,expect,it} from "vitest";
import {canAccessRoute,canAdmin,canExecute,canPerform,canView} from "./permissions";

describe("permission-aware navigation",()=>{
 it("preserves the legacy built-in role behavior",()=>{
  expect(canView("VIEWER")).toBe(true);
  expect(canExecute("VIEWER")).toBe(false);
  expect(canExecute("OPERATOR")).toBe(true);
  expect(canAdmin("ADMIN")).toBe(true);
  expect(canAdmin("OPERATOR")).toBe(false);
 });
 it("uses persisted permission codes for custom roles",()=>{
  const scoped={role:"Network Analyst",permissions:["workspace.read","quality.read"]};
  expect(canView(scoped)).toBe(true);
  expect(canPerform(scoped,"quality.read")).toBe(true);
  expect(canAdmin(scoped)).toBe(false);
 });
 it("exposes workspace and administration routes according to grants",()=>{
  const viewer={role:"Custom Viewer",permissions:["workspace.read"]};
  const admin={role:"Custom Admin",permissions:["workspace.read","users.read","roles.read"]};
  expect(canAccessRoute(viewer,"workspace")).toBe(true);
  expect(canAccessRoute(viewer,"administration")).toBe(false);
  expect(canAccessRoute(admin,"administration")).toBe(true);
 });
});
