import { describe, expect, it } from "vitest";

import type { SourceResponse } from "./api";
import { deriveMaterialEmbed, deriveMaterialPresentation } from "./materials-state";

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

  it("does not offer enter-course when the latest generation failed even with a stale course id", () => {
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

    expect(result.badge).toBe("课程生成失败");
    expect(result.primaryAction).toBe("view-details");
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

  it("keeps cancelled sources terminal instead of showing processing copy", () => {
    const source = makeSource({
      status: "cancelled",
      latest_processing_task: {
        task_type: "source_processing",
        status: "cancelled",
        stage: "cancelled",
      },
      embed: {
        status: "queued",
      },
    });
    const result = deriveMaterialPresentation(source);

    expect(result.badge).toBe("已取消");
    expect(result.supportingText).toBe("资料处理已取消，可重试处理");
    expect(result.category).toBe("error");
    expect(result.isActive).toBe(false);
    expect(deriveMaterialEmbed(source)?.status).toBe("cancelled");
  });

  it("treats ready sources with active course generation as processing", () => {
    const result = deriveMaterialPresentation(
      makeSource({
        latest_course_task: {
          task_type: "course_generation",
          status: "running",
          stage: "assembling_course",
        },
      })
    );

    expect(result.badge).toBe("课程生成中");
    expect(result.primaryAction).toBe("view-details");
  });

  it("does not let stale embedding hide an already generated course", () => {
    const source = makeSource({
      latest_course_id: "course-123",
      course_count: 1,
      embed: {
        status: "stale",
        reason: "embed model upgraded",
      },
      latest_course_task: {
        task_type: "course_generation",
        status: "success",
        stage: "ready",
      },
    });

    expect(deriveMaterialPresentation(source).badge).toBe("已生成课程");
    expect(deriveMaterialEmbed(source)?.status).toBe("ready");
  });

  it("prioritizes active source processing over queued course generation", () => {
    const result = deriveMaterialPresentation(
      makeSource({
        status: "analyzing",
        latest_processing_task: {
          task_type: "source_processing",
          status: "running",
          stage: "analyzing",
        },
        latest_course_task: {
          task_type: "course_generation",
          status: "pending",
          stage: "pending",
        },
      })
    );

    expect(result.badge).toBe("资料处理中");
    expect(result.supportingText).toBe("资料正在分析中");
    expect(result.isActive).toBe(true);
  });

  it("labels source section planning as a material-processing stage", () => {
    const result = deriveMaterialPresentation(
      makeSource({
        status: "planning",
        latest_processing_task: {
          task_type: "source_processing",
          status: "running",
          stage: "planning",
        },
      })
    );

    expect(result.badge).toBe("资料处理中");
    expect(result.supportingText).toBe("资料正在规划章节中");
  });
});
