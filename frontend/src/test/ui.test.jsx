import React from "react";
import {render,screen} from "@testing-library/react";
import {describe,expect,it} from "vitest";
import {StatusBadge} from "../components/ui";
import {mean,summarizeRunOutcomes,validSamples} from "../utils";

describe("StatusBadge",()=>{
  it("renders a human-readable semantic state",()=>{
    render(<StatusBadge value="LAB_FAILED"/>);
    expect(screen.getByText("Lab Failed")).toBeTruthy();
  });
  it("makes missing states explicit",()=>{
    render(<StatusBadge value={null}/>);
    expect(screen.getByText("Not recorded")).toBeTruthy();
  });
});

describe("Run outcome representation",()=>{
  it("does not treat warnings or pytest PASS as plain validation outcomes",()=>{
    const summary=summarizeRunOutcomes([
      {lifecycle_status:"RUNNING",business_outcome:null},
      {lifecycle_status:"COMPLETED",business_outcome:"VALIDATED"},
      {lifecycle_status:"COMPLETED",business_outcome:"VALIDATED_WITH_WARNINGS"},
      {lifecycle_status:"FAILED",business_outcome:"REJECTED"},
      {lifecycle_status:"LAB_FAILED",business_outcome:"UNVALIDATED"},
      {business_outcome:"PASS"},
    ]);
    expect(summary).toMatchObject({
      active:1,validated:1,validatedWithWarnings:1,rejected:1,unvalidated:1,
      missingOutcome:2,needsReview:2,
    });
  });
  it("does not infer active or successful Runs from missing lifecycle fields",()=>{
    expect(summarizeRunOutcomes([{}, {lifecycle_status:"COMPLETED"}])).toMatchObject({
      active:0,validated:0,validatedWithWarnings:0,rejected:0,unvalidated:0,needsReview:0,
    });
  });
});

describe("Metric sample representation",()=>{
  it("includes only valid, finite, non-warm-up numeric samples in summary statistics",()=>{
    const samples=[
      {status:"VALID",value:2},
      {status:"valid",value:"4.5"},
      {status:"VALID",value:100,warmup:true},
      {status:"INVALID",value:8},
      {status:"VALID",value:null},
      {status:"VALID",value:""},
      {status:"VALID",value:Infinity},
    ];
    expect(validSamples(samples).map(sample=>Number(sample.value))).toEqual([2,4.5]);
    expect(mean([2,null,"",NaN,"4"])).toBe(3);
    expect(mean([null,"",NaN])).toBeNull();
  });
});
