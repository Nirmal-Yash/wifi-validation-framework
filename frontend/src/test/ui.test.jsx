import React from "react";
import {render,screen} from "@testing-library/react";
import {describe,expect,it} from "vitest";
import {StatusBadge} from "../components/ui";
describe("StatusBadge",()=>{it("exposes the semantic status text",()=>{render(<StatusBadge value="LAB_FAILED"/>);expect(screen.getByText("LAB FAILED")).toBeTruthy();});it("renders an explicit placeholder when state is unavailable",()=>{render(<StatusBadge value={null}/>);expect(screen.getByText("—")).toBeTruthy();});});