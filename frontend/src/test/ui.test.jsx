import React from "react";
import {render,screen} from "@testing-library/react";
import {describe,expect,it} from "vitest";
import {StatusBadge} from "../components/ui";
import {summarizeRunOutcomes} from "../utils";
describe("StatusBadge",()=>{it("exposes the semantic status text",()=>{render(<StatusBadge value="LAB_FAILED"/>);expect(screen.getByText("LAB FAILED")).toBeTruthy();});it("renders an explicit placeholder when state is unavailable",()=>{render(<StatusBadge value={null}/>);expect(screen.getByText("—")).toBeTruthy();});});

describe("summarizeRunOutcomes",()=>{
  it("counts persisted business outcomes without treating PASS as a release outcome",()=>{
    const summary=summarizeRunOutcomes([
      {lifecycle_status:"RUNNING",business_outcome:null},
      {lifecycle_status:"COMPLETED",business_outcome:"VALIDATED"},
      {lifecycle_status:"COMPLETED",business_outcome:"VALIDATED_WITH_WARNINGS"},
      {lifecycle_status:"FAILED",business_outcome:"REJECTED"},
      {lifecycle_status:"LAB_FAILED",business_outcome:"UNVALIDATED"},
      {business_outcome:"PASS"},
    ]);
    expect(summary).toEqual({active:1,validated:2,needsReview:2});
  });
  it("does not infer active or successful Runs from missing state",()=>{
    expect(summarizeRunOutcomes([{}, {lifecycle_status:"COMPLETED"}])).toEqual({active:0,validated:0,needsReview:0});
  });
});
