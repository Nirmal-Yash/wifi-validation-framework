import React from "react";
import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {beforeEach,describe,expect,it,vi} from "vitest";
import LoginPage from "../pages/auth";

describe("NetRegress login screen",()=>{
 beforeEach(()=>vi.clearAllMocks());
 it("keeps the form mounted and shows authentication errors",async()=>{
  const onLogin=vi.fn().mockRejectedValue(new Error("Invalid username or password."));
  render(<LoginPage onLogin={onLogin}/>);
  fireEvent.change(screen.getByLabelText("Username"),{target:{value:"owner"}});
  fireEvent.change(screen.getByLabelText("Password"),{target:{value:"wrong-password"}});
  fireEvent.click(screen.getByRole("button",{name:/sign in securely/i}));
  expect(await screen.findByText("Invalid username or password.")).toBeTruthy();
  expect(screen.getByLabelText("Username")).toBeTruthy();
  expect(onLogin).toHaveBeenCalledWith("owner","wrong-password");
 });
 it("prevents empty credentials from being submitted",()=>{
  const onLogin=vi.fn();
  render(<LoginPage onLogin={onLogin}/>);
  expect(screen.getByRole("button",{name:/sign in securely/i}).disabled).toBe(true);
  expect(onLogin).not.toHaveBeenCalled();
 });
 it("toggles password visibility without losing the entered value",()=>{
  render(<LoginPage onLogin={vi.fn()}/>);
  const password=screen.getByLabelText("Password");
  fireEvent.change(password,{target:{value:"local-owner-password"}});
  fireEvent.click(screen.getByRole("button",{name:"Show password"}));
  expect(screen.getByLabelText("Password").type).toBe("text");
  expect(screen.getByLabelText("Password").value).toBe("local-owner-password");
 });
 it("submits the normalized username and password to the session provider",async()=>{
  const onLogin=vi.fn().mockResolvedValue({username:"owner",role:"OWNER"});
  render(<LoginPage onLogin={onLogin}/>);
  fireEvent.change(screen.getByLabelText("Username"),{target:{value:" owner "}});
  fireEvent.change(screen.getByLabelText("Password"),{target:{value:"correct-password"}});
  fireEvent.click(screen.getByRole("button",{name:/sign in securely/i}));
  await waitFor(()=>expect(onLogin).toHaveBeenCalledWith("owner","correct-password"));
 });
});
