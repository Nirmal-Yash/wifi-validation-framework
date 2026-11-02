import React from "react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";

const state=vi.hoisted(()=>({
 warningVisible:true,
 idleRemaining:125000,
 continueSession:vi.fn(),
 logout:vi.fn(),
}));
vi.mock("../auth/session-provider",()=>({useSession:()=>state}));
import SessionExpiryDialog from "../auth/session-dialog";

describe("session inactivity warning",()=>{
 beforeEach(()=>{vi.clearAllMocks();state.warningVisible=true;state.idleRemaining=125000;});
 afterEach(()=>cleanup());
 it("shows the idle countdown before automatic sign-out",()=>{
  render(<SessionExpiryDialog/>);
  expect(screen.getByRole("heading",{name:"Still working?"})).toBeTruthy();
  expect(screen.getByText("02:05")).toBeTruthy();
 });
 it("requires explicit Continue action to keep the session",()=>{
  render(<SessionExpiryDialog/>);
  fireEvent.click(screen.getByRole("button",{name:"Continue session"}));
  expect(state.continueSession).toHaveBeenCalledTimes(1);
 });
 it("offers an explicit sign-out action",()=>{
  render(<SessionExpiryDialog/>);
  fireEvent.click(screen.getByRole("button",{name:/sign out/i}));
  expect(state.logout).toHaveBeenCalledTimes(1);
 });
});
