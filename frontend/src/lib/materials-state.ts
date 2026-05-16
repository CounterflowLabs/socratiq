import type { SourceEmbed, SourceResponse, SourceTaskSummary } from "./api";

export type MaterialPrimaryAction = "enter-course" | "view-details";
export type MaterialStatusCategory = "ready" | "processing" | "error";
export type MaterialStatusFilter = "all" | MaterialStatusCategory;

export interface MaterialPresentation {
  badge: string;
  supportingText: string;
  primaryAction: MaterialPrimaryAction;
  category: MaterialStatusCategory;
  isActive: boolean;
}

const STAGE_LABELS: Record<string, string> = {
  pending: "排队",
  processing: "处理",
  extracting: "提取",
  analyzing: "分析",
  storing: "存储",
  embedding: "向量化",
  waiting_donor: "复用",
  planning: "规划章节",
  generating: "生成",
  generating_lessons: "生成课文",
  generating_labs: "生成 Lab",
  assembling_course: "组装",
  ready: "已完成",
  error: "失败",
  cancelled: "已取消",
};

function isTaskActive(task: SourceTaskSummary | null | undefined): boolean {
  return task?.status === "pending" || task?.status === "running" || task?.status === "progress";
}

export function isCourseTaskActive(source: SourceResponse): boolean {
  return isTaskActive(source.latest_course_task);
}

export function formatMaterialStage(stage: string | null | undefined): string | null {
  if (!stage) return null;
  return STAGE_LABELS[stage] ?? stage;
}

function isSourceCancelled(source: SourceResponse): boolean {
  return (
    source.status === "cancelled" ||
    source.latest_processing_task?.status === "cancelled"
  );
}

function isSourceFailed(source: SourceResponse): boolean {
  return source.status === "error" || source.latest_processing_task?.status === "failure";
}

function isSourceProcessingActive(source: SourceResponse): boolean {
  return (
    isTaskActive(source.latest_processing_task) ||
    (source.status !== "ready" &&
      source.status !== "error" &&
      source.status !== "cancelled")
  );
}

function stageLabel(stage?: string | null): string | null {
  if (!stage) {
    return null;
  }

  return STAGE_LABELS[stage] ?? stage;
}

function progressText(subject: "资料" | "课程", stage?: string | null): string {
  const label = stageLabel(stage);
  return label ? `${subject}正在${label}中` : `${subject}正在处理中`;
}

export function deriveMaterialEmbed(source: SourceResponse): SourceEmbed | null | undefined {
  if (isSourceCancelled(source)) {
    return {
      ...(source.embed ?? {}),
      status: "cancelled",
    };
  }

  if (isSourceFailed(source)) {
    return {
      ...(source.embed ?? {}),
      status: "failed",
      error: source.embed?.error ?? source.latest_processing_task?.error_summary ?? null,
    };
  }

  const hasUsableCourse =
    Boolean(source.latest_course_id) &&
    source.latest_course_task?.status !== "failure" &&
    !isTaskActive(source.latest_course_task);
  if (hasUsableCourse && source.embed?.status === "stale") {
    return {
      ...source.embed,
      status: "ready",
      reason: null,
      error: null,
    };
  }

  return source.embed;
}

export function deriveMaterialPresentation(source: SourceResponse): MaterialPresentation {
  if (isSourceCancelled(source)) {
    return {
      badge: "已取消",
      supportingText: "资料处理已取消，可重试处理",
      primaryAction: "view-details",
      category: "error",
      isActive: false,
    };
  }

  if (source.status === "error") {
    return {
      badge: "资料处理失败",
      supportingText: "资料处理失败，请查看详情",
      primaryAction: "view-details",
      category: "error",
      isActive: false,
    };
  }

  if (isSourceProcessingActive(source)) {
    return {
      badge: "资料处理中",
      supportingText: progressText("资料", source.latest_processing_task?.stage ?? source.status),
      primaryAction: "view-details",
      category: "processing",
      isActive: true,
    };
  }

  if (source.latest_course_task?.status === "failure") {
    return {
      badge: "课程生成失败",
      supportingText: source.latest_course_task.error_summary
        ? `课程生成失败：${source.latest_course_task.error_summary}`
        : "课程生成失败",
      primaryAction: "view-details",
      category: "error",
      isActive: false,
    };
  }

  if (isTaskActive(source.latest_course_task)) {
    return {
      badge: "课程生成中",
      supportingText: progressText("课程", source.latest_course_task?.stage),
      primaryAction: "view-details",
      category: "processing",
      isActive: true,
    };
  }

  if (source.latest_course_id) {
    return {
      badge: "已生成课程",
      supportingText:
        source.course_count > 0
          ? `已生成 ${source.course_count} 门课程`
          : "课程已生成，可直接进入",
      primaryAction: "enter-course",
      category: "ready",
      isActive: false,
    };
  }

  if (source.status === "ready") {
    return {
      badge: "已就绪",
      supportingText: "资料已完成处理，可以继续生成课程",
      primaryAction: "view-details",
      category: "ready",
      isActive: false,
    };
  }

  return {
    badge: "处理中",
    supportingText: "资料正在处理",
    primaryAction: "view-details",
    category: "processing",
    isActive: true,
  };
}

export function isMaterialActive(source: SourceResponse): boolean {
  return deriveMaterialPresentation(source).isActive;
}

export function matchesMaterialStatusFilter(
  source: SourceResponse,
  filter: MaterialStatusFilter
): boolean {
  if (filter === "all") {
    return true;
  }

  return deriveMaterialPresentation(source).category === filter;
}
