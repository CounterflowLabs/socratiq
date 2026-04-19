import { describe, expect, it } from "vitest";

import { deriveTaskSyncState } from "./task-sync";

describe("deriveTaskSyncState", () => {
  it("keeps the task in course generation while source is ready but no course exists yet", () => {
    const result = deriveTaskSyncState({
      currentState: "embedding",
      taskStatus: {
        state: "SUCCESS",
        result: {},
      },
      source: {
        status: "ready",
        metadata_: {},
      },
    });

    expect(result.state).toBe("generating_course");
    expect(result.shouldGenerateCourse).toBe(true);
    expect(result.courseId).toBeUndefined();
  });

  it("marks the task successful once the backend reports a course id", () => {
    const result = deriveTaskSyncState({
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
    expect(result.shouldGenerateCourse).toBe(false);
    expect(result.courseId).toBe("course-123");
  });
});
