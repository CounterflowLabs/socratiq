import type { SourceResponse, SourceTaskSummary } from "./api";

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

function isTaskActive(task: SourceTaskSummary | null | undefined): boolean {
  return task?.status === "pending" || task?.status === "running";
}

export function deriveMaterialPresentation(source: SourceResponse): MaterialPresentation {
  if (source.status === "error") {
    return {
      badge: "资料处理失败",
      supportingText: "资料处理失败，请查看详情",
      primaryAction: "view-details",
      category: "error",
      isActive: false,
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
      supportingText: source.latest_course_task?.stage
        ? `课程正在${source.latest_course_task.stage}中`
        : "课程正在生成中",
      primaryAction: "view-details",
      category: "processing",
      isActive: true,
    };
  }

  if (isTaskActive(source.latest_processing_task) || (source.status !== "ready" && source.status !== "error")) {
    return {
      badge: "资料处理中",
      supportingText: source.latest_processing_task?.stage
        ? `资料正在${source.latest_processing_task.stage}中`
        : "资料正在处理中",
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
