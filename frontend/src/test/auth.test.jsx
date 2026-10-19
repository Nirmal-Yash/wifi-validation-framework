import React from "react";
import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

vi.mock("../api", () => ({
  api: {login: vi.fn(), me: vi.fn(), logout: vi.fn()},
}));

import {api} from "../api";
import App from "../App";
import LoginPage from "../pages/auth";

describe("authentication UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows invalid credentials without dropping the login form", async () => {
    api.login.mockRejectedValueOnce(new Error("invalid credentials"));
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin}/>);

    fireEvent.change(screen.getByLabelText("Username"), {target: {value: "owner"}});
    fireEvent.change(screen.getByLabelText("Password"), {target: {value: "wrong-password"}});
    fireEvent.click(screen.getByRole("button", {name: "Sign in"}));

    expect(await screen.findByText("invalid credentials")).toBeTruthy();
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("completes sign-in after the API accepts the owner credentials", async () => {
    const profile = {username: "owner", role: "OWNER", projects: ["*"]};
    api.login.mockResolvedValueOnce({csrf_token: "csrf-test-token"});
    api.me.mockResolvedValueOnce(profile);
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin}/>);

    fireEvent.change(screen.getByLabelText("Username"), {target: {value: "owner"}});
    fireEvent.change(screen.getByLabelText("Password"), {target: {value: "valid-password"}});
    fireEvent.click(screen.getByRole("button", {name: "Sign in"}));

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(profile));
  });

  it("shows setup guidance instead of disguising an API outage as bad credentials", async () => {
    api.me.mockRejectedValueOnce(new Error("API is unreachable"));
    render(<App/>);

    expect(await screen.findByRole("heading", {name: "Runner connection problem"})).toBeTruthy();
    expect(screen.getByText("./scripts/start_dashboard.sh")).toBeTruthy();
  });
});
