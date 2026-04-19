import { describe, expect, it } from "vitest";

import { deriveMaterialPresentation } from "./materials-state";

describe("deriveMaterialPresentation", () => {
  it("surfaces course generation failure while keeping the source usable", () => {
    const result = deriveMaterialPresentation({
      status: "ready",
      latest_processing_task: { task_type: "source_processing", status: "success", stage: "ready" },
      latest_course_task: { task_type: "course_generation", status: "failure", stage: "assembling_course", error_summary: "LLM timeout" },
      latest_course_id: null,
      metadata_: {},
    } as any);

    expect(result.badge).toBe("课程生成失败");
    expect(result.primaryAction).toBe("view-details");
    expect(result.supportingText).toContain("LLM timeout");
  });
});
