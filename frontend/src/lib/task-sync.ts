interface TaskStatusLike {
  state: string;
  result?: unknown;
  progress?: unknown;
}

interface SourceLike {
  status?: string;
  metadata_?: Record<string, unknown>;
}

interface DeriveTaskSyncStateInput {
  currentState: string;
  taskStatus: TaskStatusLike | null;
  source: SourceLike | null;
}

interface DeriveTaskSyncStateResult {
  state: string;
  shouldGenerateCourse: boolean;
  courseId?: string;
}

function getTaskStage(status: TaskStatusLike | null): string | null {
  if (!status) {
    return null;
  }

  if (
    status.state === "PROGRESS" &&
    status.progress &&
    typeof status.progress === "object" &&
    "stage" in status.progress &&
    typeof status.progress.stage === "string"
  ) {
    return status.progress.stage;
  }

  return status.state;
}

function extractCourseId(value: unknown): string | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  if ("course_id" in value && typeof value.course_id === "string" && value.course_id) {
    return value.course_id;
  }

  return undefined;
}

export function deriveTaskSyncState(
  input: DeriveTaskSyncStateInput
): DeriveTaskSyncStateResult {
  const courseId =
    extractCourseId(input.taskStatus?.result) ||
    (input.source?.status === "ready"
      ? extractCourseId(input.source?.metadata_)
      : undefined);

  if (courseId) {
    return {
      state: "SUCCESS",
      shouldGenerateCourse: false,
      courseId,
    };
  }

  if (input.source?.status === "error" || input.taskStatus?.state === "FAILURE") {
    return {
      state: "FAILURE",
      shouldGenerateCourse: false,
    };
  }

  const nextState = getTaskStage(input.taskStatus) || input.currentState;

  if (nextState === "assembling_course") {
    return {
      state: "assembling_course",
      shouldGenerateCourse: false,
    };
  }

  if (
    input.source?.status === "ready" ||
    input.taskStatus?.state === "SUCCESS"
  ) {
    return {
      state: "generating_course",
      shouldGenerateCourse: true,
    };
  }

  return {
    state: nextState,
    shouldGenerateCourse: false,
  };
}
