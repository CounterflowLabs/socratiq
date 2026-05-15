"use client";

import { useMemo, useState } from "react";

import {
  IcAlert as AlertCircle,
  IcClose as Ban,
  IcCheck as Check,
  IcTrash as Trash2,
  IcLoader as CircleDashed,
  IcLoader as Loader2,
  IcRegen as RefreshCcw,
  IcClose as X,
} from "@/components/icons";
import type { SourceProgressResponse, SourceTaskProgress } from "@/lib/api";

const STAGE_ORDER: Record<string, string[]> = {
  source_processing: ["extracting", "analyzing", "storing", "embedding", "planning"],
  course_generation: ["assembling_course"],
  course_regeneration: ["generating"],
};

const STAGE_LABELS: Record<string, string> = {
  extracting: "提取内容",
  analyzing: "结构分析",
  storing: "写入数据库",
  embedding: "生成向量",
  planning: "划分章节",
  assembling_course: "装配课程",
  generating: "重新生成",
  ready: "已完成",
  error: "失败",
  cancelled: "已取消",
};

const TASK_TYPE_LABELS: Record<string, string> = {
  source_processing: "① 内容摄入",
  course_generation: "② 装配课程",
  course_regeneration: "重新生成课程",
};

type StageState = "pending" | "running" | "done" | "error" | "cancelled";

interface PipelineSegment {
  taskType: string;
  task: SourceTaskProgress | null;
  stages: { name: string; label: string; state: StageState }[];
  segmentState: StageState;
  errorSummary: string | null;
}

function deriveSegment(
  taskType: string,
  task: SourceTaskProgress | null
): PipelineSegment {
  const stageNames = STAGE_ORDER[taskType] ?? [];

  if (!task) {
    return {
      taskType,
      task: null,
      stages: stageNames.map((s) => ({
        name: s,
        label: STAGE_LABELS[s] ?? s,
        state: "pending",
      })),
      segmentState: "pending",
      errorSummary: null,
    };
  }

  const currentStage = task.stage ?? "";
  const currentIdx = stageNames.indexOf(currentStage);

  let segmentState: StageState = "pending";
  if (task.status === "success") segmentState = "done";
  else if (task.status === "failure") segmentState = "error";
  else if (task.status === "cancelled") segmentState = "cancelled";
  else if (task.status === "running") segmentState = "running";

  const stages = stageNames.map((name, idx) => {
    let state: StageState = "pending";
    if (segmentState === "done") {
      state = "done";
    } else if (segmentState === "error") {
      if (idx < currentIdx) state = "done";
      else if (idx === currentIdx || (currentIdx < 0 && idx === 0)) state = "error";
    } else if (segmentState === "cancelled") {
      if (idx < currentIdx) state = "done";
      else if (idx === currentIdx) state = "cancelled";
    } else if (segmentState === "running") {
      if (idx < currentIdx) state = "done";
      else if (idx === currentIdx) state = "running";
    }
    return { name, label: STAGE_LABELS[name] ?? name, state };
  });

  return {
    taskType,
    task,
    stages,
    segmentState,
    errorSummary: task.error_summary ?? null,
  };
}

function StageIcon({ state }: { state: StageState }) {
  switch (state) {
    case "done":
      return <Check className="h-4 w-4 text-emerald-600" />;
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-blue-600" />;
    case "error":
      return <AlertCircle className="h-4 w-4 text-red-600" />;
    case "cancelled":
      return <Ban className="h-4 w-4 text-gray-500" />;
    default:
      return <CircleDashed className="h-4 w-4 text-gray-300" />;
  }
}

function isActive(progress: SourceProgressResponse): boolean {
  return progress.tasks.some(
    (t) => t.status === "pending" || t.status === "running"
  );
}

function isRunning(progress: SourceProgressResponse): boolean {
  return progress.tasks.some((t) => t.status === "running");
}

function isRetryable(progress: SourceProgressResponse): boolean {
  // Anything not actively running can be retried: explicit failures and
  // cancellations obviously, but also pending tasks that never picked up
  // (worker crashed before ack, or the queue went away).
  if (isRunning(progress)) return false;
  if (progress.source_status === "error" || progress.source_status === "cancelled") {
    return true;
  }
  return progress.tasks.some(
    (t) => t.status === "failure" || t.status === "cancelled" || t.status === "pending"
  );
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  destructive,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        aria-label="关闭确认"
        className="absolute inset-0 bg-black/30 backdrop-blur-sm"
        onClick={onCancel}
        type="button"
      />
      <div className="relative z-10 w-full max-w-sm rounded-2xl border border-gray-200 bg-white p-5 shadow-xl">
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        <p className="mt-2 text-sm text-gray-600">{description}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={
              "rounded-lg px-3 py-1.5 text-sm font-medium text-white shadow-sm " +
              (destructive
                ? "bg-red-600 hover:bg-red-700"
                : "bg-blue-600 hover:bg-blue-700")
            }
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

interface SourcePipelineViewProps {
  progress: SourceProgressResponse | null;
  title?: string;
  onCancel?: () => Promise<void> | void;
  onRetry?: () => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
}

export default function SourcePipelineView({
  progress,
  title,
  onCancel,
  onRetry,
  onDelete,
}: SourcePipelineViewProps) {
  const [confirm, setConfirm] = useState<"cancel" | "retry" | "delete" | null>(null);
  const [busy, setBusy] = useState(false);

  const segments = useMemo(() => {
    if (!progress) return [];
    const byType = new Map<string, SourceTaskProgress>();
    for (const t of progress.tasks) byType.set(t.task_type, t);
    const order = ["source_processing", "course_generation", "course_regeneration"];
    return order
      .filter((t) => byType.has(t) || t === "source_processing")
      .map((t) => deriveSegment(t, byType.get(t) ?? null));
  }, [progress]);

  if (!progress) {
    return null;
  }

  const showCancel = Boolean(onCancel) && isRunning(progress);
  const showRetry = Boolean(onRetry) && isRetryable(progress);
  const showDelete = Boolean(onDelete);
  const deleteWhileActive = isActive(progress);

  async function handleConfirmed(action: "cancel" | "retry" | "delete") {
    setBusy(true);
    try {
      if (action === "cancel" && onCancel) await onCancel();
      if (action === "retry" && onRetry) await onRetry();
      if (action === "delete" && onDelete) await onDelete();
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-gray-900">
            {title || "学习资料"}
          </h3>
          <p className="mt-0.5 text-xs text-gray-500">
            {progress.source_status === "ready" && progress.course_id
              ? "课程已就绪"
              : progress.source_status === "error"
                ? "处理失败"
                : progress.source_status === "cancelled"
                  ? "已取消"
                  : "处理中…"}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {showRetry && (
            <button
              type="button"
              onClick={() => setConfirm("retry")}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCcw className="h-3.5 w-3.5" />
              重试
            </button>
          )}
          {showCancel && (
            <button
              type="button"
              onClick={() => setConfirm("cancel")}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              <X className="h-3.5 w-3.5" />
              取消
            </button>
          )}
          {showDelete && (
            <button
              type="button"
              onClick={() => setConfirm("delete")}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              aria-label="删除资料"
            >
              <Trash2 className="h-3.5 w-3.5" />
              删除
            </button>
          )}
        </div>
      </div>

      <div className="space-y-3 px-4 py-3">
        {segments.map((segment) => (
          <div key={segment.taskType}>
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-gray-700">
                {TASK_TYPE_LABELS[segment.taskType] ?? segment.taskType}
              </p>
              {segment.errorSummary && (
                <p
                  className="ml-3 truncate text-xs text-red-600"
                  title={segment.errorSummary}
                >
                  {segment.errorSummary}
                </p>
              )}
            </div>
            <ul className="mt-1.5 space-y-1">
              {segment.stages.map((stage) => (
                <li
                  key={stage.name}
                  className="flex items-center gap-2 text-xs"
                >
                  <StageIcon state={stage.state} />
                  <span
                    className={
                      stage.state === "running"
                        ? "font-medium text-gray-900"
                        : stage.state === "done"
                          ? "text-gray-600"
                          : stage.state === "error"
                            ? "text-red-600"
                            : stage.state === "cancelled"
                              ? "text-gray-500"
                              : "text-gray-400"
                    }
                  >
                    {stage.label}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <ConfirmDialog
        open={confirm === "cancel"}
        title="取消处理"
        description="正在进行的任务会停止，已写入的内容会保留。下次可以从中断处继续。"
        confirmLabel={busy ? "取消中…" : "确认取消"}
        destructive
        onConfirm={() => handleConfirmed("cancel")}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "retry"}
        title="重新尝试"
        description="将从中断的阶段继续运行，已完成的步骤会跳过。"
        confirmLabel={busy ? "正在重试…" : "确认重试"}
        onConfirm={() => handleConfirmed("retry")}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        title="删除资料"
        description={
          deleteWhileActive
            ? "资料正在处理中。删除会停止后台任务并从列表中移除，已生成的内容仍会保留在数据库。"
            : "资料会从列表中移除，已生成的内容仍会保留在数据库。"
        }
        confirmLabel={busy ? "删除中…" : "确认删除"}
        destructive
        onConfirm={() => handleConfirmed("delete")}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}
