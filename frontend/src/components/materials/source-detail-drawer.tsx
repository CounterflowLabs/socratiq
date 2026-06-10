"use client";

import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { useEffect, useState } from "react";
import {
  IcAlert,
  IcArrowRight as ArrowRight,
  IcCheck,
  IcDoc as FileText,
  IcLoader,
  IcRegen,
  IcSpark,
  IcTrash,
  IcVideo as Play,
  IcClose as X,
} from "@/components/icons";
import {
  cancelTask,
  deleteSource,
  generateCourseForSource,
  getSourceProgress,
  listSourceChunks,
  listSourceCitations,
  retryTask,
  retrySource,
  type SourceCitationCourse,
  type SourceChunkBrief,
  type SourceProgressResponse,
  type SourceResponse,
  type SourceTaskSummary,
} from "@/lib/api";
import { deriveMaterialPresentation } from "@/lib/materials-state";
import { useRunProgress } from "@/lib/use-run-progress";
import AgenticTimeline from "@/components/materials/agentic-timeline";

interface SourceDetailDrawerProps {
  open: boolean;
  source: SourceResponse | null;
  onClose: () => void;
  onDeleted?: (sourceId: string) => void;
  onChanged?: () => void;
}

type DetailTab = "chunks" | "courses" | "history";
type LifecycleState = "pending" | "current" | "done" | "error" | "cancelled";
type SectionAssemblyStatus = "pending" | "running" | "success" | "failure";

interface SectionAssemblyItem {
  key: string;
  title: string;
  status: SectionAssemblyStatus;
  order_index: number | null;
  error?: string | null;
}

interface SectionAssemblyProgress {
  mode?: string;
  total: number;
  completed: number;
  failed: number;
  active?: string | null;
  items: SectionAssemblyItem[];
}

function canRetryFor(source: SourceResponse): boolean {
  if (source.status === "error" || source.status === "cancelled") return true;
  const proc = source.latest_processing_task;
  if (proc?.status === "failure" || proc?.status === "cancelled") return true;
  // Stuck pending (no live task): processing_task says failure but source still says pending.
  if (source.status === "pending" && proc?.status !== "running") return true;
  return false;
}

function canGenerateCourseFor(source: SourceResponse): boolean {
  if (source.status !== "ready") return false;
  if (source.latest_course_id) return false;
  const ct = source.latest_course_task;
  // If a generation is already pending/running, don't offer to start another.
  if (isTaskActiveStatus(ct)) return false;
  return true;
}

function isTaskActiveStatus(task?: SourceTaskSummary | null): boolean {
  return task?.status === "pending" || task?.status === "running" || task?.status === "progress";
}

function getTaskActionId(task?: SourceTaskSummary | null): string | null {
  return task?.id ?? task?.celery_task_id ?? null;
}

// The AG-UI run id is the ARQ job id, which the backend pre-allocates as the
// task's celery_task_id (= enqueue job_id = worker run_id), NOT the DB row id.
// Subscribing by row id would listen on the wrong Redis stream and get nothing.
function getRunId(task?: SourceTaskSummary | null): string | null {
  return task?.celery_task_id ?? task?.id ?? null;
}

const STAGE_LABELS: Record<string, string> = {
  pending: "排队中",
  processing: "处理中",
  extracting: "提取中",
  analyzing: "分析中",
  storing: "存储中",
  embedding: "向量化",
  waiting_donor: "复用中",
  planning: "规划章节",
  generating_lessons: "生成课文",
  generating_labs: "生成 Lab",
  assembling_course: "组装课程",
  ready: "已完成",
  error: "失败",
  cancelled: "已取消",
};

const TASK_STATUS_LABELS: Record<string, string> = {
  pending: "排队中",
  running: "进行中",
  progress: "进行中",
  success: "已完成",
  failure: "失败",
  cancelled: "已取消",
};

const TASK_TYPE_LABELS: Record<string, string> = {
  source_processing: "资料处理",
  course_generation: "课程生成",
};

const TASK_STAGE_DETAILS: Record<string, Record<string, string[]>> = {
  source_processing: {
    pending: ["创建资料记录", "等待处理队列"],
    extracting: ["读取来源信息", "获取字幕或音频", "整理原始片段"],
    analyzing: ["识别主题线索", "拆分学习切片", "估算难度与时长"],
    storing: ["保存资料摘要", "写入切片内容", "关联来源元数据"],
    embedding: ["生成切片向量", "生成概念向量", "写入检索库"],
    ready: ["资料处理完成", "课程生成已接力"],
    error: ["记录失败原因", "等待重试"],
    cancelled: ["停止后台任务", "保留已完成记录"],
  },
  course_generation: {
    pending: ["创建课程任务", "等待生成队列"],
    planning: ["读取资料切片", "确定课程结构", "安排章节顺序"],
    assembling_course: ["确认章节顺序", "生成章节课文", "装配练习与学习入口"],
    generating_lessons: ["生成章节课文", "补齐示例与概念", "保存章节草稿"],
    generating_labs: ["生成练习任务", "准备评测信息", "绑定章节入口"],
    ready: ["课程已写入", "学习入口已开放"],
    error: ["记录失败原因", "等待重试"],
    cancelled: ["停止生成任务", "保留已完成记录"],
  },
};

const TASK_STAGE_FLOW: Record<string, string[]> = {
  source_processing: ["pending", "extracting", "analyzing", "storing", "embedding", "ready"],
  course_generation: ["pending", "planning", "assembling_course", "ready"],
};

function getSourceOrigin(source: SourceResponse): { label: string; href?: string } {
  const originalFilename = source.metadata_?.original_filename;
  if (typeof originalFilename === "string" && originalFilename.trim()) {
    return { label: originalFilename };
  }

  const mediaUrl = source.metadata_?.media_url;
  if (typeof mediaUrl === "string" && mediaUrl.trim()) {
    return { label: mediaUrl, href: mediaUrl };
  }

  if (source.url) {
    return { label: source.url, href: source.url };
  }

  return { label: source.type };
}

const COURSE_STAGE_FLOW = [
  {
    key: "source_ready",
    label: "资料处理",
    description: "完成后进入课程生成",
  },
  {
    key: "pending",
    label: "排队生成",
    description: "等待生成任务开始",
  },
  {
    key: "planning",
    label: "规划章节",
    description: "确定课程结构",
  },
  {
    key: "assembling_course",
    label: "生成组装",
    description: "生成课文并装配章节",
  },
  {
    key: "ready",
    label: "课程就绪",
    description: "可以进入学习",
  },
] as const;

function TypeIcon({ type }: { type: string }) {
  if (type === "youtube" || type === "bilibili") {
    return <Play className="w-4 h-4" style={{ color: "var(--accent)" }} />;
  }

  return <FileText className="w-4 h-4" style={{ color: "var(--ink-3)" }} />;
}

function getStageLabel(stage?: string | null): string | null {
  if (!stage) {
    return null;
  }

  return STAGE_LABELS[stage] ?? stage;
}

function getTaskLabel(task?: SourceTaskSummary | null): string {
  if (!task) {
    return "暂无任务";
  }

  return TASK_TYPE_LABELS[task.task_type] ?? task.task_type;
}

function getTaskSummary(task?: SourceTaskSummary | null): string {
  if (!task) {
    return "暂无记录";
  }

  if (task.error_summary) {
    return task.error_summary;
  }

  const stageLabel = getStageLabel(task.stage);
  if (stageLabel) {
    return stageLabel;
  }

  return TASK_STATUS_LABELS[task.status] ?? task.status;
}

function getTaskStatusLabel(status?: string | null): string | null {
  if (!status) {
    return null;
  }

  return TASK_STATUS_LABELS[status] ?? status;
}

function isSourceReadyForCourse(source: SourceResponse): boolean {
  return (
    source.status === "ready" ||
    source.latest_processing_task?.status === "success" ||
    Boolean(source.latest_course_id)
  );
}

function getCourseStageIndex(stage?: string | null): number {
  switch (stage) {
    case "pending":
      return 1;
    case "planning":
      return 2;
    case "assembling_course":
    case "generating":
    case "drafting":
    case "generating_lessons":
    case "generating_labs":
      return 3;
    case "ready":
      return 4;
    default:
      return 3;
  }
}

function deriveCourseLifecycle(source: SourceResponse): {
  steps: { key: string; label: string; description: string; state: LifecycleState }[];
  percent: number;
  headline: string;
  detail: string;
  tone: "ready" | "processing" | "error" | "neutral";
} {
  const courseTask = source.latest_course_task;
  const sourceReady = isSourceReadyForCourse(source);
  const hasGeneratedCourse = Boolean(source.latest_course_id);
  const courseReady =
    hasGeneratedCourse &&
    courseTask?.status !== "failure" &&
    !isTaskActiveStatus(courseTask);

  let currentIndex = sourceReady ? 1 : 0;
  let currentState: LifecycleState = sourceReady ? "current" : "current";
  let headline = sourceReady ? "资料就绪，等待生成课程" : "资料还在处理";
  let detail = sourceReady ? "可以从这里发起课程生成。" : "课程生成会在资料处理完成后继续。";
  let tone: "ready" | "processing" | "error" | "neutral" = sourceReady ? "neutral" : "processing";

  if (courseTask?.status === "failure") {
    currentIndex = getCourseStageIndex(courseTask.stage);
    currentState = "error";
    headline = "课程生成失败";
    detail = courseTask.error_summary ?? "可以重试课程生成。";
    tone = "error";
  } else if (courseTask?.status === "cancelled") {
    currentIndex = getCourseStageIndex(courseTask.stage);
    currentState = "cancelled";
    headline = "课程生成已取消";
    detail = "可以重新发起课程生成。";
    tone = "neutral";
  } else if (courseTask?.status === "pending") {
    currentIndex = 1;
    currentState = "current";
    headline = "课程正在排队";
    detail = "任务已进入生成队列。";
    tone = "processing";
  } else if (courseTask?.status === "running" || courseTask?.status === "progress") {
    currentIndex = getCourseStageIndex(courseTask.stage);
    currentState = "current";
    headline = getTaskSummary(courseTask);
    detail = "课程生成正在进行。";
    tone = "processing";
  } else if (courseReady) {
    currentIndex = COURSE_STAGE_FLOW.length - 1;
    currentState = "done";
    headline = "课程已就绪";
    detail =
      source.course_count > 0
        ? `这份资料已生成 ${source.course_count} 门课程。`
        : "课程已经生成，可以进入学习。";
    tone = "ready";
  }

  const steps = COURSE_STAGE_FLOW.map((step, index) => {
    let state: LifecycleState = "pending";
    if (courseReady) {
      state = "done";
    } else if (index < currentIndex) {
      state = "done";
    } else if (index === currentIndex) {
      state = currentState;
    }
    return { ...step, state };
  });

  const basePercent = [12, 30, 52, 76, 100][currentIndex] ?? 12;
  const percent =
    currentState === "done"
      ? 100
      : currentState === "error" || currentState === "cancelled"
        ? Math.max(10, basePercent - 6)
        : basePercent;

  return { steps, percent, headline, detail, tone };
}

function lifecycleToneStyle(tone: "ready" | "processing" | "error" | "neutral") {
  if (tone === "ready") {
    return {
      background: "var(--sage-soft)",
      color: "var(--sage-ink)",
      borderColor: "transparent",
    };
  }
  if (tone === "processing") {
    return {
      background: "var(--accent-soft)",
      color: "var(--accent-ink)",
      borderColor: "transparent",
    };
  }
  if (tone === "error") {
    return {
      background: "var(--error-soft)",
      color: "var(--error)",
      borderColor: "transparent",
    };
  }
  return undefined;
}

function LifecycleIcon({ state }: { state: LifecycleState }) {
  if (state === "done") return <IcCheck className="w-3.5 h-3.5" />;
  if (state === "error") return <IcAlert className="w-3.5 h-3.5" />;
  if (state === "cancelled") return <X className="w-3.5 h-3.5" />;
  if (state === "current") return <IcLoader className="w-3.5 h-3.5 spin" />;
  return <span className="h-2 w-2 rounded-full" style={{ background: "var(--ink-4)" }} />;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeSectionStatus(value: unknown): SectionAssemblyStatus {
  if (value === "running" || value === "success" || value === "failure") return value;
  return "pending";
}

function getSectionAssemblyProgress(
  task?: SourceTaskSummary | null,
): SectionAssemblyProgress | null {
  return normalizeSectionProgress(task?.metadata_?.section_progress);
}

// Shared by the polled path (task.metadata_) and the live AG-UI STATE_SNAPSHOT
// path — both carry the same section_progress shape.
function normalizeSectionProgress(raw: unknown): SectionAssemblyProgress | null {
  if (!isRecord(raw)) return null;
  const rawItems = Array.isArray(raw.items) ? raw.items : [];
  const items = rawItems.filter(isRecord).map((item, index) => ({
    key: String(item.key ?? index),
    title: String(item.title ?? `Section ${index + 1}`),
    status: normalizeSectionStatus(item.status),
    order_index: typeof item.order_index === "number" ? item.order_index : index,
    error: typeof item.error === "string" ? item.error : null,
  }));

  if (items.length === 0) return null;

  const completed =
    typeof raw.completed === "number"
      ? raw.completed
      : items.filter((item) => item.status === "success" || item.status === "failure").length;
  const failed =
    typeof raw.failed === "number"
      ? raw.failed
      : items.filter((item) => item.status === "failure").length;

  return {
    mode: typeof raw.mode === "string" ? raw.mode : undefined,
    total: typeof raw.total === "number" ? raw.total : items.length,
    completed,
    failed,
    active: typeof raw.active === "string" ? raw.active : null,
    items,
  };
}

function isTaskDetailVisible(task?: SourceTaskSummary | null): task is SourceTaskSummary {
  return Boolean(task && (isTaskActiveStatus(task) || task.status === "failure"));
}

function getTaskStageFlow(taskType: string): string[] {
  return TASK_STAGE_FLOW[taskType] ?? ["pending", "processing", "ready"];
}

function normalizeTaskStage(task: SourceTaskSummary): string {
  if (task.status === "failure") return task.stage ?? "error";
  if (task.status === "cancelled") return "cancelled";
  return task.stage ?? task.status;
}

function getTaskStageState(
  task: SourceTaskSummary,
  stage: string,
  index: number,
  currentIndex: number,
): LifecycleState {
  if (task.status === "failure" && index === currentIndex) return "error";
  if (task.status === "cancelled" && index === currentIndex) return "cancelled";
  if (index < currentIndex) return "done";
  if (index === currentIndex) return "current";
  return "pending";
}

function getStageDetails(taskType: string, stage: string, task: SourceTaskSummary): string[] {
  if (task.status === "failure" && task.error_summary && stage === normalizeTaskStage(task)) {
    return [task.error_summary];
  }

  return TASK_STAGE_DETAILS[taskType]?.[stage] ?? [getStageLabel(stage) ?? stage];
}

function TaskStageDetailPanel({ source }: { source: SourceResponse }) {
  const tasks = [source.latest_processing_task, source.latest_course_task].filter(
    isTaskDetailVisible,
  );

  if (tasks.length === 0) {
    return null;
  }

  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
            当前步骤
          </h3>
          <p className="mt-1 text-xs" style={{ color: "var(--ink-3)" }}>
            {tasks.length > 1 ? "多个任务正在推进。" : getTaskSummary(tasks[0])}
          </p>
        </div>
        <span className="text-xs" style={{ color: "var(--ink-4)" }}>
          {tasks.length} 个任务
        </span>
      </div>

      <div className="mt-3 space-y-3">
        {tasks.map((task) => (
          <TaskStageDetailGroup key={task.id ?? task.task_type} task={task} />
        ))}
      </div>
    </section>
  );
}

function TaskStageDetailGroup({ task }: { task: SourceTaskSummary }) {
  const flow = getTaskStageFlow(task.task_type);
  const currentStage = normalizeTaskStage(task);
  const rawIndex = flow.indexOf(currentStage);
  const currentIndex = rawIndex >= 0 ? rawIndex : 0;
  const visibleFlow = rawIndex >= 0 ? flow : [currentStage, ...flow];

  return (
    <div
      className="rounded-xl px-3 py-3"
      style={{
        background: "var(--surface-2)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium" style={{ color: "var(--ink)" }}>
              {getTaskLabel(task)}
            </span>
            <span className="chip">
              {getTaskStatusLabel(task.status)}
            </span>
          </div>
          <p className="mt-0.5 truncate text-xs" style={{ color: "var(--ink-3)" }}>
            {getStageLabel(currentStage) ?? currentStage}
          </p>
        </div>
      </div>

      <ol className="mt-3 space-y-3">
        {visibleFlow.map((stage, index) => {
          const state = getTaskStageState(task, stage, index, currentIndex);
          const details = getStageDetails(task.task_type, stage, task);

          return (
            <li key={stage} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span
                  className="inline-flex h-6 w-6 items-center justify-center rounded-full"
                  style={{
                    background:
                      state === "done"
                        ? "var(--sage-soft)"
                        : state === "current"
                          ? "var(--accent-soft)"
                          : state === "error"
                            ? "var(--error-soft)"
                            : "var(--surface)",
                    color:
                      state === "done"
                        ? "var(--sage-ink)"
                        : state === "current"
                          ? "var(--accent-ink)"
                          : state === "error"
                            ? "var(--error)"
                            : "var(--ink-3)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <LifecycleIcon state={state} />
                </span>
                {index < visibleFlow.length - 1 ? (
                  <span
                    className="mt-1 h-full min-h-7 w-px"
                    style={{ background: "var(--border)" }}
                  />
                ) : null}
              </div>
              <div className="min-w-0 flex-1 pb-1">
                <p className="text-sm font-medium" style={{ color: "var(--ink)" }}>
                  {getStageLabel(stage) ?? stage}
                </p>
                <ul className="mt-1 grid gap-1 sm:grid-cols-2">
                  {details.map((detail) => (
                    <li
                      key={detail}
                      className="rounded-md px-2 py-1 text-[11px]"
                      style={{
                        background: "var(--surface)",
                        color: "var(--ink-3)",
                      }}
                    >
                      {detail}
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function TaskRow({
  task,
  action,
}: {
  task?: SourceTaskSummary | null;
  action?: ReactNode;
}) {
  return (
    <div
      className="rounded-xl p-3"
      style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium" style={{ color: "var(--ink)" }}>
            {getTaskLabel(task)}
          </p>
          <p className="mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
            {getTaskSummary(task)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {task?.status && (
            <span className="chip">
              {getTaskStatusLabel(task.status)}
            </span>
          )}
          {action}
        </div>
      </div>
    </div>
  );
}

function CourseTaskAction({
  task,
  courseId,
  busyAction,
  onCancel,
  onRetry,
}: {
  task?: SourceTaskSummary | null;
  courseId: string | null;
  busyAction: "cancel" | "retry" | null;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const taskId = getTaskActionId(task);
  if (isTaskActiveStatus(task)) {
    return (
      <button
        type="button"
        aria-label="取消课程生成"
        disabled={!taskId || busyAction !== null}
        onClick={onCancel}
        className="btn btn-danger btn-sm"
      >
        {busyAction === "cancel" ? (
          <IcLoader className="w-3.5 h-3.5 spin" />
        ) : (
          <X className="w-3.5 h-3.5" />
        )}
        {busyAction === "cancel" ? "取消中…" : "取消生成"}
      </button>
    );
  }

  if (task?.status === "failure") {
    return (
      <button
        type="button"
        disabled={!taskId || busyAction !== null}
        onClick={onRetry}
        className="btn btn-outline btn-sm"
        style={{ color: "var(--warn)", borderColor: "var(--warn)" }}
      >
        {busyAction === "retry" ? (
          <IcLoader className="w-3.5 h-3.5 spin" />
        ) : (
          <IcRegen className="w-3.5 h-3.5" />
        )}
        {busyAction === "retry" ? "重试中…" : "重试生成"}
      </button>
    );
  }

  if (task?.status === "success" && courseId) {
    return (
      <Link
        href={`/path?courseId=${courseId}`}
        className="btn btn-outline btn-sm"
        style={{ color: "var(--accent)" }}
      >
        打开课程
        <ArrowRight className="w-3.5 h-3.5" />
      </Link>
    );
  }

  return null;
}

function CourseProgressPanel({
  source,
  generating,
  busyAction,
  onGenerate,
  onCancel,
  onRetry,
}: {
  source: SourceResponse;
  generating: boolean;
  busyAction: "cancel" | "retry" | null;
  onGenerate: () => void;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const lifecycle = deriveCourseLifecycle(source);

  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="eyebrow">课程状态</span>
            <span className="chip" style={lifecycleToneStyle(lifecycle.tone)}>
              {lifecycle.headline}
            </span>
          </div>
          <p className="mt-2 text-sm" style={{ color: "var(--ink-2)" }}>
            {lifecycle.detail}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {canGenerateCourseFor(source) ? (
            <button
              type="button"
              disabled={generating}
              onClick={onGenerate}
              className="btn btn-accent"
            >
              <IcSpark className="w-4 h-4" />
              {generating ? "正在派发…" : "生成课程"}
            </button>
          ) : source.latest_course_task?.status === "failure" ? (
            <CourseTaskAction
              task={source.latest_course_task}
              courseId={source.latest_course_id}
              busyAction={busyAction}
              onCancel={onCancel}
              onRetry={onRetry}
            />
          ) : isTaskActiveStatus(source.latest_course_task) ? (
            <>
              <CourseTaskAction
                task={source.latest_course_task}
                courseId={source.latest_course_id}
                busyAction={busyAction}
                onCancel={onCancel}
                onRetry={onRetry}
              />
              <Link href="/tasks" className="btn btn-outline btn-sm">
                查看任务
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </>
          ) : source.latest_course_id ? (
            <Link href={`/path?courseId=${source.latest_course_id}`} className="btn btn-primary">
              进入课程
              <ArrowRight className="w-4 h-4" />
            </Link>
          ) : null}
        </div>
      </div>

      <div className="mt-4">
        <div
          className="h-1.5 overflow-hidden rounded-full"
          style={{ background: "var(--surface-2)" }}
        >
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${lifecycle.percent}%`,
              background:
                lifecycle.tone === "ready"
                  ? "var(--sage)"
                  : lifecycle.tone === "error"
                    ? "var(--error)"
                    : "var(--accent)",
            }}
          />
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-5">
          {lifecycle.steps.map((step) => (
            <div
              key={step.key}
              className="min-w-0 rounded-xl p-3"
              style={{
                background:
                  step.state === "current"
                    ? "var(--accent-soft)"
                    : step.state === "done"
                      ? "var(--sage-soft)"
                      : step.state === "error"
                        ? "var(--error-soft)"
                        : "transparent",
                border: "1px solid var(--border)",
                color:
                  step.state === "done"
                    ? "var(--sage-ink)"
                    : step.state === "error"
                      ? "var(--error)"
                      : step.state === "current"
                        ? "var(--accent-ink)"
                        : "var(--ink-3)",
              }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                  style={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <LifecycleIcon state={step.state} />
                </span>
                <span className="truncate text-xs font-semibold">{step.label}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-[11px]">{step.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function SectionAssemblyPanel({
  task,
  live,
}: {
  task?: SourceTaskSummary | null;
  live?: Record<string, unknown> | null;
}) {
  // Prefer the live AG-UI snapshot; fall back to the last polled task metadata.
  const progress = normalizeSectionProgress(live) ?? getSectionAssemblyProgress(task);
  const showFallback =
    isTaskActiveStatus(task) && (task?.stage === "assembling_course" || task?.stage === "generating_lessons");

  if (!progress && !showFallback) {
    return null;
  }

  const percent = progress?.total
    ? Math.round((progress.completed / Math.max(progress.total, 1)) * 100)
    : 0;
  const statusStyle: Record<SectionAssemblyStatus, CSSProperties> = {
    pending: { background: "var(--surface-2)", color: "var(--ink-3)" },
    running: { background: "var(--accent-soft)", color: "var(--accent-ink)" },
    success: { background: "var(--sage-soft)", color: "var(--sage-ink)" },
    failure: { background: "var(--error-soft)", color: "var(--error)" },
  };
  const statusLabel: Record<SectionAssemblyStatus, string> = {
    pending: "等待",
    running: "生成中",
    success: "完成",
    failure: "失败",
  };

  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
            章节组装进度
          </h3>
          <p className="mt-1 text-xs" style={{ color: "var(--ink-3)" }}>
            {progress
              ? `已完成 ${progress.completed} / ${progress.total} 个 section${
                  progress.failed > 0 ? `，失败 ${progress.failed} 个` : ""
                }。`
              : "正在组装课程，当前任务还没有上报章节明细。"}
          </p>
        </div>
        {progress ? (
          <span className="chip chip-mono">
            {percent}%
          </span>
        ) : null}
      </div>

      {progress ? (
        <>
          <div
            className="mt-3 h-1.5 overflow-hidden rounded-full"
            style={{ background: "var(--surface-2)" }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${percent}%`,
                background: progress.failed > 0 ? "var(--warn)" : "var(--accent)",
              }}
            />
          </div>
          <div className="mt-3 grid max-h-[240px] gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {progress.items.map((item) => (
              <div
                key={item.key}
                className="rounded-xl p-3"
                style={{
                  background: item.status === "running" ? "var(--accent-soft)" : "var(--surface-2)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p
                      className="truncate text-xs font-semibold"
                      style={{ color: "var(--ink)" }}
                      title={item.title}
                    >
                      #{(item.order_index ?? 0) + 1} {item.title}
                    </p>
                    {item.error ? (
                      <p className="mt-1 line-clamp-2 text-[11px]" style={{ color: "var(--error)" }}>
                        {item.error}
                      </p>
                    ) : null}
                  </div>
                  <span
                    className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium"
                    style={statusStyle[item.status]}
                  >
                    {statusLabel[item.status]}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

function SourceFactsPanel({ source }: { source: SourceResponse }) {
  const sourceOrigin = getSourceOrigin(source);

  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
          资料概览
        </h3>
        <span className="chip chip-mono">{source.type}</span>
      </div>
      <dl className="mt-3 space-y-3">
        <InfoRow label="资料状态" value={getStageLabel(source.status) ?? source.status} />
        <InfoRow label="课程数量" value={`${source.course_count}`} />
        <InfoRow
          label="更新时间"
          value={new Date(source.updated_at).toLocaleString("zh-CN")}
        />
        <InfoRow label="资料来源" value={sourceOrigin.label} href={sourceOrigin.href} />
      </dl>
    </section>
  );
}

function TaskSnapshotPanel({
  source,
}: {
  source: SourceResponse;
}) {
  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
    >
      <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
        任务摘要
      </h3>
      <div className="mt-3 space-y-2">
        <TaskRow task={source.latest_processing_task} />
        <TaskRow task={source.latest_course_task} />
      </div>
    </section>
  );
}

function InfoRow({
  label,
  value,
  href,
}: {
  label: string;
  value: string;
  href?: string;
}) {
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] items-start gap-3 text-sm">
      <dt style={{ color: "var(--ink-3)" }}>{label}</dt>
      <dd className="min-w-0 text-right font-medium" style={{ color: "var(--ink)" }}>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="block truncate hover:underline"
            style={{ color: "var(--accent)" }}
          >
            {value}
          </a>
        ) : (
          <span className="block truncate">{value}</span>
        )}
      </dd>
    </div>
  );
}

function DetailTabs({
  active,
  onChange,
}: {
  active: DetailTab;
  onChange: (tab: DetailTab) => void;
}) {
  const tabs: { key: DetailTab; label: string }[] = [
    { key: "chunks", label: "切片" },
    { key: "courses", label: "课程" },
    { key: "history", label: "历史" },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className="btn btn-sm"
          style={{
            background: active === tab.key ? "var(--ink)" : "var(--surface)",
            color: active === tab.key ? "var(--surface)" : "var(--ink-2)",
            borderColor: active === tab.key ? "var(--ink)" : "var(--border)",
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export default function SourceDetailDrawer({
  open,
  source,
  onClose,
  onDeleted,
  onChanged,
}: SourceDetailDrawerProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [courseTaskAction, setCourseTaskAction] = useState<"cancel" | "retry" | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("chunks");
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setConfirmingDelete(false);
      setCourseTaskAction(null);
      setDetailTab("chunks");
      setActionError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) {
      document.body.style.overflow = "";
      return;
    }

    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  // Live course-generation progress over AG-UI SSE (replaces polling for the
  // section-assembly panel). Idles unless a course task is actively running; the
  // parent's source polling remains the fallback when no live stream exists.
  const liveCourse = useRunProgress(
    source?.id ?? null,
    getRunId(source?.latest_course_task),
    open && isTaskActiveStatus(source?.latest_course_task),
  );

  if (!source) {
    return null;
  }

  const presentation = deriveMaterialPresentation(source);
  const handleCourseTaskAction = async (action: "cancel" | "retry") => {
    const taskId = getTaskActionId(source.latest_course_task);
    if (!taskId) {
      setActionError("没有找到课程任务记录，请刷新后再试。");
      return;
    }

    setCourseTaskAction(action);
    setActionError(null);
    try {
      if (action === "cancel") {
        await cancelTask(taskId);
      } else {
        await retryTask(taskId);
      }
      onChanged?.();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : action === "cancel"
            ? "取消课程生成失败，请稍后再试"
            : "重试课程生成失败，请稍后再试",
      );
    } finally {
      setCourseTaskAction(null);
    }
  };
  const handleGenerateCourse = async () => {
    setGenerating(true);
    setActionError(null);
    try {
      await generateCourseForSource(source.id);
      onChanged?.();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "课程生成失败，请稍后重试");
    } finally {
      setGenerating(false);
    }
  };

  if (!open) {
    // Mount nothing when closed so we don't run the lazy data fetches in
    // the sub-sections below. Re-opening starts fresh — desired behavior
    // for the "preview latest data" feel.
    return null;
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="资料详情"
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6"
      onClick={(e) => {
        // Click on the backdrop (not the dialog itself) closes.
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      style={{
        background: "rgba(26, 22, 17, 0.45)",
        backdropFilter: "blur(2px)",
      }}
    >
      <div
        className="relative flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl shadow-2xl"
        style={{
          background: "var(--surface-alt)",
          border: "1px solid var(--border)",
          animation: "soc-modal-in 180ms ease-out",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <style>{`
          @keyframes soc-modal-in {
            from { opacity: 0; transform: translateY(8px) scale(0.98); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
          }
        `}</style>
        {/* No inner flex wrapper — the outer is already flex-col; an
            extra `h-full` here would resolve against an auto-height
            parent and collapse, breaking the body's overflow-y-auto. */}
        <>
          <div
            className="flex items-start justify-between gap-4 border-b px-5 py-4"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--ink-3)" }}>
                <TypeIcon type={source.type} />
                <span>{source.type}</span>
                <span className="chip" style={lifecycleToneStyle(deriveCourseLifecycle(source).tone)}>
                  {presentation.badge}
                </span>
              </div>
              <h2 className="mt-2 line-clamp-2 text-lg font-semibold" style={{ color: "var(--ink)" }}>
                {source.title || source.url || "未命名资料"}
              </h2>
            </div>
            <button
              aria-label="关闭"
              className="rounded-lg p-2 transition"
              style={{ color: "var(--ink-3)" }}
              onClick={onClose}
              type="button"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-5">
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="min-w-0 space-y-5">
                <CourseProgressPanel
                  source={source}
                  generating={generating}
                  busyAction={courseTaskAction}
                  onGenerate={() => void handleGenerateCourse()}
                  onCancel={() => void handleCourseTaskAction("cancel")}
                  onRetry={() => void handleCourseTaskAction("retry")}
                />
                <TaskStageDetailPanel source={source} />
                <AgenticTimeline
                  agentic={liveCourse.agentic}
                  running={liveCourse.runStatus === "running"}
                />
                <SectionAssemblyPanel task={source.latest_course_task} live={liveCourse.snapshot} />

                <section
                  className="rounded-2xl p-4"
                  style={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                        资料内容
                      </h3>
                      <p className="mt-1 text-xs" style={{ color: "var(--ink-3)" }}>
                        切片、已生成课程和任务历史集中在这里查看。
                      </p>
                    </div>
                    <DetailTabs active={detailTab} onChange={setDetailTab} />
                  </div>
                  <div
                    className="mt-4 max-h-[330px] min-h-[220px] overflow-y-auto rounded-xl p-3"
                    style={{
                      background: "var(--surface-2)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {detailTab === "chunks" && source.id ? (
                      <ChunksSection sourceId={source.id} />
                    ) : null}
                    {detailTab === "courses" && source.id ? (
                      <CitationsSection sourceId={source.id} />
                    ) : null}
                    {detailTab === "history" && source.id ? (
                      <HistorySection sourceId={source.id} />
                    ) : null}
                  </div>
                </section>
              </div>

              <aside className="min-w-0 space-y-4">
                <SourceFactsPanel source={source} />
                <TaskSnapshotPanel source={source} />
                <SectionPlannerSection metadata={source.metadata_} />
              </aside>
            </div>
          </div>

          <div
            className="space-y-3 border-t p-4"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            {actionError ? (
              <p
                className="rounded-md border px-3 py-2 text-xs"
                style={{
                  background: "var(--error-soft)",
                  borderColor: "var(--error)",
                  color: "var(--error)",
                }}
              >
                {actionError}
              </p>
            ) : null}
            {confirmingDelete ? (
              <div
                className="rounded-lg border p-3 text-sm"
                style={{
                  background: "var(--error-soft)",
                  borderColor: "var(--error)",
                  color: "var(--error)",
                }}
              >
                <p>
                  确认删除？资料会从列表中移除，
                  {presentation.isActive ? "进行中的后台任务会被停止。" : "已生成的内容仍会保留在数据库。"}
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmingDelete(false)}
                    disabled={deleting}
                    className="btn btn-outline btn-sm"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (!source) return;
                      setDeleting(true);
                      try {
                        await deleteSource(source.id);
                        onDeleted?.(source.id);
                        onClose();
                      } finally {
                        setDeleting(false);
                        setConfirmingDelete(false);
                      }
                    }}
                    disabled={deleting}
                    className="btn btn-danger btn-sm"
                  >
                    {deleting ? "删除中…" : "确认删除"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm" style={{ color: "var(--ink-3)" }}>
                  课程进度会随任务状态自动更新。
                </p>
                <div className="flex flex-wrap justify-end gap-2">
                  {canRetryFor(source) ? (
                    <button
                      type="button"
                      disabled={retrying}
                      onClick={async () => {
                        setRetrying(true);
                        setActionError(null);
                        try {
                          await retrySource(source.id);
                          onChanged?.();
                        } catch (err) {
                          setActionError(err instanceof Error ? err.message : "重试失败，请稍后再试");
                        } finally {
                          setRetrying(false);
                        }
                      }}
                      className="btn btn-outline"
                    >
                      <IcRegen className="w-4 h-4" />
                      {retrying ? "正在重试…" : "重试处理"}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setConfirmingDelete(true)}
                    className="btn btn-danger"
                  >
                    <IcTrash className="w-4 h-4" />
                    删除资料
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      </div>
    </div>
  );
}

/* PRD §11 Phase E — Chunks tab content. Lazy-loads on mount, paginates
   client-side with a "show more" button. Embeddings deliberately
   omitted (they bloat the wire by ~3KB per chunk). */
function ChunksSection({ sourceId }: { sourceId: string }) {
  const [data, setData] = useState<{
    items: SourceChunkBrief[];
    total: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [skip, setSkip] = useState(0);
  const PAGE = 5;

  useEffect(() => {
    let cancelled = false;
    listSourceChunks(sourceId, { skip: 0, limit: PAGE })
      .then((res) => {
        if (cancelled) return;
        setData({ items: res.items, total: res.total });
        setSkip(res.items.length);
      })
      .catch(() => {
        if (!cancelled) setData({ items: [], total: 0 });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  const loadMore = async () => {
    setLoading(true);
    const res = await listSourceChunks(sourceId, { skip, limit: PAGE });
    setData((prev) =>
      prev ? { items: [...prev.items, ...res.items], total: res.total } : { items: res.items, total: res.total },
    );
    setSkip((s) => s + res.items.length);
    setLoading(false);
  };

  return (
    <section>
      <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
        切片预览
        {data ? (
          <span className="ml-2 text-xs" style={{ color: "var(--ink-4)" }}>
            {data.total}
          </span>
        ) : null}
      </h3>
      <div className="mt-3 space-y-2">
        {!data && loading ? (
          <p className="text-xs" style={{ color: "var(--ink-3)" }}>加载切片中…</p>
        ) : null}
        {data?.items.length === 0 && !loading ? (
          <p className="text-xs" style={{ color: "var(--ink-3)" }}>暂无切片</p>
        ) : null}
        {data?.items.map((c, idx) => (
          <div
            key={c.id}
            className="rounded-xl p-3 text-xs"
            style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
          >
            <div
              className="mb-1 flex items-center justify-between text-[10px]"
              style={{ color: "var(--ink-4)" }}
            >
              <span className="mono">#{idx + 1}</span>
              <span className="mono">{c.length} chars</span>
            </div>
            <p className="line-clamp-3" style={{ color: "var(--ink-2)" }}>
              {c.text}
            </p>
          </div>
        ))}
        {data && skip < data.total ? (
          <button
            type="button"
            className="text-xs hover:underline disabled:opacity-50"
            style={{ color: "var(--accent)" }}
            disabled={loading}
            onClick={loadMore}
          >
            {loading ? "加载中…" : `继续加载 (${data.total - skip} 余)`}
          </button>
        ) : null}
      </div>
    </section>
  );
}

/* Courses generated from this source — surfaces every version so the
   user can jump to an older regenerate without going through the
   course-detail page's version chip. The latest version is the one
   the Library row's Sparkle CTA jumps to. */
function CitationsSection({ sourceId }: { sourceId: string }) {
  const [data, setData] = useState<{
    items: SourceCitationCourse[];
    total: number;
  } | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    listSourceCitations(sourceId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setData({ items: [], total: 0 });
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);
  if (!data) {
    return <p className="text-xs" style={{ color: "var(--ink-3)" }}>加载课程中…</p>;
  }
  if (data.items.length === 0) {
    return <p className="text-xs" style={{ color: "var(--ink-3)" }}>暂无生成课程</p>;
  }
  return (
    <section>
      <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
        该资料生成的课程
        <span className="ml-2 text-xs" style={{ color: "var(--ink-4)" }}>
          {data.total}
        </span>
      </h3>
      <ul className="mt-3 space-y-2">
        {data.items.map((course) => (
          <li
            key={course.course_id}
            className="rounded-xl p-3"
            style={
              course.is_latest
                ? {
                    border: "1px solid var(--accent)",
                    background: "var(--accent-soft)",
                  }
                : {
                    border: "1px solid var(--border)",
                    background: "var(--surface)",
                  }
            }
          >
            <div className="flex items-center gap-2">
              <span
                className="mono"
                style={{
                  fontSize: 10,
                  padding: "2px 6px",
                  borderRadius: 999,
                  background: course.is_latest
                    ? "var(--accent)"
                    : "var(--surface-2)",
                  color: course.is_latest ? "white" : "var(--ink-2)",
                  fontVariantNumeric: "tabular-nums",
                  flexShrink: 0,
                }}
              >
                v{course.version_index}
              </span>
              {course.is_latest ? (
                <span
                  className="mono"
                  style={{
                    fontSize: 10,
                    color: "var(--accent)",
                    flexShrink: 0,
                  }}
                >
                  最新
                </span>
              ) : null}
              <span
                style={{
                  fontSize: 10,
                  color: "var(--ink-3)",
                  marginLeft: "auto",
                  flexShrink: 0,
                }}
              >
                {new Date(course.created_at).toLocaleDateString("zh-CN", {
                  month: "short",
                  day: "numeric",
                })}
              </span>
            </div>

            <div className="mt-2 flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/learn?courseId=${course.course_id}`}
                  className="text-sm font-medium hover:underline"
                  style={{
                    color: "var(--accent)",
                    display: "block",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {course.course_title}
                </Link>
                {course.regeneration_directive ? (
                  <p
                    style={{
                      fontSize: 11,
                      color: "var(--ink-3)",
                      marginTop: 2,
                      fontStyle: "italic",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    &ldquo;{course.regeneration_directive}&rdquo;
                  </p>
                ) : null}
              </div>
              <Link
                href={`/learn?courseId=${course.course_id}`}
                className="btn btn-outline btn-sm"
                style={{ color: "var(--ink-2)", flexShrink: 0 }}
              >
                打开
                <ArrowRight className="w-3 h-3" />
              </Link>
            </div>

            {course.sections.length > 0 ? (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  setExpandedId((prev) =>
                    prev === course.course_id ? null : course.course_id,
                  );
                }}
                style={{
                  marginTop: 8,
                  background: "transparent",
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                  color: "var(--ink-3)",
                  fontSize: 11,
                }}
              >
                {expandedId === course.course_id
                  ? "收起"
                  : `引用 ${course.sections.length} 个章节 ▾`}
              </button>
            ) : null}
            {expandedId === course.course_id ? (
              <ul className="mt-2 space-y-1 text-xs" style={{ color: "var(--ink-3)" }}>
                {course.sections.slice(0, 6).map((s) => (
                  <li key={s.section_id}>· {s.title}</li>
                ))}
                {course.sections.length > 6 ? (
                  <li>· …+{course.sections.length - 6}</li>
                ) : null}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/* History — every recorded task row for this source, newest first. */
function HistorySection({ sourceId }: { sourceId: string }) {
  const [data, setData] = useState<SourceProgressResponse | null>(null);
  useEffect(() => {
    let cancelled = false;
    getSourceProgress(sourceId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);
  if (!data) {
    return <p className="text-xs" style={{ color: "var(--ink-3)" }}>加载历史中…</p>;
  }
  if (data.tasks.length === 0) {
    return <p className="text-xs" style={{ color: "var(--ink-3)" }}>暂无任务历史</p>;
  }
  return (
    <section>
      <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
        历史{" "}
        <span className="ml-2 text-xs" style={{ color: "var(--ink-4)" }}>
          {data.tasks.length}
        </span>
      </h3>
      <ul className="mt-3 space-y-2">
        {data.tasks.map((t) => (
          <li
            key={`${t.task_type}-${t.celery_task_id ?? t.created_at}`}
            className="rounded-xl p-3 text-xs"
            style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-medium" style={{ color: "var(--ink-2)" }}>
                {t.task_type}
              </span>
              <span
                style={{
                  color:
                    t.status === "success"
                      ? "var(--sage)"
                      : t.status === "failure"
                        ? "var(--error)"
                        : "var(--ink-3)",
                }}
              >
                {getTaskStatusLabel(t.status)}
              </span>
            </div>
            {t.stage ? (
              <p className="mt-1 text-[11px] mono" style={{ color: "var(--ink-3)" }}>
                {getStageLabel(t.stage) ?? t.stage}
              </p>
            ) : null}
            {t.error_summary ? (
              <p className="mt-1 text-[11px]" style={{ color: "var(--error)" }}>
                {t.error_summary}
              </p>
            ) : null}
            <p className="mt-1 text-[10px] mono" style={{ color: "var(--ink-4)" }}>
              {new Date(t.created_at).toLocaleString("zh-CN")}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* SectionPlanner stats — surfaces the per-source metadata that the
   section floor (``course_generator.ensure_section_buckets``) writes at
   course-generation time. Source.metadata_["section_planner_stats"] is
   optional; sources that never generated a course don't render this block. */
function SectionPlannerSection({
  metadata,
}: {
  metadata: Record<string, unknown>;
}) {
  const stats = (metadata?.section_planner_stats ?? null) as
    | import("@/lib/api").SectionPlannerStats
    | null;
  if (!stats) return null;

  const tierLabel: Record<string, string> = {
    short_circuit: "短源单桶",
    embedding_only: "向量分桶（Layer 3）",
    fallback: "按大小兜底（Layer 4）",
    // 旧版（v2 之前）写入的 tier 值，存量数据仍可能出现：
    skeleton: "整段（Layer 1，旧版）",
    windowed: "分窗（Layer 2，旧版）",
  };
  const tierStyle =
    stats.tier_used === "fallback"
      ? { background: "var(--warn-soft)", color: "var(--warn)" }
      : stats.tier_used === "embedding_only"
        ? { background: "var(--accent-soft)", color: "var(--accent-ink)" }
        : { background: "var(--surface-2)", color: "var(--ink-2)" };

  const formatMs = (ms: number) =>
    ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;

  return (
    <section
      className="rounded-2xl p-4"
      style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
    >
      <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
        章节规划
      </h3>
      <div className="mt-3 space-y-3">
        <div className="flex items-center justify-between gap-4">
          <span className="text-sm" style={{ color: "var(--ink-3)" }}>
            分桶策略
          </span>
          <span
            className="rounded-full px-2 py-0.5 text-xs font-medium"
            style={tierStyle}
          >
            {tierLabel[stats.tier_used] ?? stats.tier_used}
          </span>
        </div>
        {stats.short_circuit ? (
          <p className="text-xs" style={{ color: "var(--ink-3)" }}>
            内容较短，整源归为一个 bucket。
          </p>
        ) : null}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div className="flex items-center justify-between">
            <dt style={{ color: "var(--ink-3)" }}>桶数</dt>
            <dd className="font-medium" style={{ color: "var(--ink)" }}>
              {stats.bucket_count}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt style={{ color: "var(--ink-3)" }}>每桶平均 chunk</dt>
            <dd className="font-medium" style={{ color: "var(--ink)" }}>
              {stats.avg_chunks_per_bucket}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt style={{ color: "var(--ink-3)" }}>最小 / 最大</dt>
            <dd className="font-medium" style={{ color: "var(--ink)" }}>
              {stats.min_chunks_per_bucket} / {stats.max_chunks_per_bucket}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt style={{ color: "var(--ink-3)" }}>命名唯一度</dt>
            <dd
              className="font-medium"
              style={{
                color: stats.topic_uniqueness < 0.7 ? "var(--warn)" : "var(--ink)",
              }}
              title={
                stats.topic_uniqueness < 0.7
                  ? "topic_uniqueness < 0.7 — planner 给出了大量重复名字，可能分桶失效"
                  : undefined
              }
            >
              {(stats.topic_uniqueness * 100).toFixed(0)}%
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt style={{ color: "var(--ink-3)" }}>耗时</dt>
            <dd className="font-medium" style={{ color: "var(--ink)" }}>
              {formatMs(stats.planning_duration_ms)}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt style={{ color: "var(--ink-3)" }}>Token in / out</dt>
            <dd className="font-medium mono text-xs" style={{ color: "var(--ink)" }}>
              {stats.llm_input_tokens} / {stats.llm_output_tokens}
            </dd>
          </div>
        </dl>
        <div
          className="flex items-center justify-between text-[11px] mono"
          style={{ color: "var(--ink-4)" }}
        >
          <span>planner: {stats.planner_version}</span>
          {stats.error ? (
            <span
              className="truncate"
              style={{ color: "var(--warn)" }}
              title={stats.error}
            >
              error: {stats.error}
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
}
