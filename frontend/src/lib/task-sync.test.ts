import { describe, expect, it } from "vitest";

import { deriveTaskSyncState } from "./task-sync";

describe("deriveTaskSyncState", () => {
  it("hands polling off to the backend-created next task id when source processing completes", () => {
    const result = deriveTaskSyncState({
      currentTaskId: "source-task-1",
      currentState: "embedding",
      taskStatus: {
        state: "SUCCESS",
        result: {},
      },
      source: {
        status: "ready",
        task_id: "course-task-1",
        metadata_: {},
      },
    });

    expect(result.state).toBe("generating_course");
    expect(result.nextTaskId).toBe("course-task-1");
    expect(result.courseId).toBeUndefined();
  });

  it("marks the task successful once the backend reports a course id", () => {
    const result = deriveTaskSyncState({
      currentTaskId: "course-task-1",
      currentState: "generating_course",
      taskStatus: {
        state: "SUCCESS",
        result: {
          course_id: "course-123",
        },
      },
      source: {
        status: "ready",
        metadata_: {},
      },
    });

    expect(result.state).toBe("SUCCESS");
    expect(result.nextTaskId).toBeUndefined();
    expect(result.courseId).toBe("course-123");
  });

  it("fails immediately when the latest backend course task has failed", () => {
    const result = deriveTaskSyncState({
      currentTaskId: "source-task-1",
      currentState: "generating_course",
      taskStatus: {
        state: "SUCCESS",
        result: {},
      },
      source: {
        status: "ready",
        task_id: "course-task-1",
        metadata_: {},
        latest_course_task: {
          task_type: "course_generation",
          status: "failure",
          stage: "error",
          error_summary: "broker unavailable",
          celery_task_id: "course-task-1",
        },
      },
    });

    expect(result.state).toBe("FAILURE");
    expect(result.error).toBe("broker unavailable");
    expect(result.nextTaskId).toBeUndefined();
  });
});
