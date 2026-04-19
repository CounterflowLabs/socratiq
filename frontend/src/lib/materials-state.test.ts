import { describe, expect, it } from "vitest";

import type { SourceResponse } from "./api";
import { deriveMaterialPresentation } from "./materials-state";

function makeSource(overrides: Partial<SourceResponse> = {}): SourceResponse {
  return {
    id: "source-1",
    type: "youtube",
    status: "ready",
    metadata_: {},
    course_count: 0,
    latest_course_id: null,
    created_at: "2026-04-19T00:00:00.000Z",
    updated_at: "2026-04-19T00:00:00.000Z",
    ...overrides,
  };
}

describe("deriveMaterialPresentation", () => {
  it("surfaces course generation failure while keeping the source usable", () => {
    const result = deriveMaterialPresentation(
      makeSource({
        latest_processing_task: {
          task_type: "source_processing",
          status: "success",
          stage: "ready",
        },
        latest_course_task: {
          task_type: "course_generation",
          status: "failure",
          stage: "assembling_course",
          error_summary: "LLM timeout",
        },
      })
    );

    expect(result.badge).toBe("课程生成失败");
    expect(result.primaryAction).toBe("view-details");
    expect(result.supportingText).toContain("LLM timeout");
  });

  it("keeps enter-course when a course already exists even if the latest generation failed", () => {
    const result = deriveMaterialPresentation(
      makeSource({
        latest_course_id: "course-123",
        course_count: 1,
        latest_course_task: {
          task_type: "course_generation",
          status: "failure",
          stage: "assembling_course",
          error_summary: "LLM timeout",
        },
      })
    );

    expect(result.badge).toBe("已生成课程");
    expect(result.primaryAction).toBe("enter-course");
  });

  it("marks error sources as failed instead of processing", () => {
    const result = deriveMaterialPresentation(
      makeSource({
        status: "error",
      })
    );

    expect(result.badge).toBe("资料处理失败");
    expect(result.primaryAction).toBe("view-details");
    expect(result.supportingText).toContain("失败");
  });
});
