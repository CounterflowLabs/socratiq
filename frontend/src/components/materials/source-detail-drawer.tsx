"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  IcArrowRight as ArrowRight,
  IcDoc as FileText,
  IcRegen,
  IcSpark,
  IcTrash,
  IcVideo as Play,
  IcClose as X,
} from "@/components/icons";
import {
  deleteSource,
  generateCourseForSource,
  retrySource,
  type SourceResponse,
  type SourceTaskSummary,
} from "@/lib/api";
import { deriveMaterialPresentation } from "@/lib/materials-state";

interface SourceDetailDrawerProps {
  open: boolean;
  source: SourceResponse | null;
  onClose: () => void;
  onDeleted?: (sourceId: string) => void;
  onChanged?: () => void;
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
  if (ct?.status === "pending" || ct?.status === "running") return false;
  return true;
}

const STAGE_LABELS: Record<string, string> = {
  pending: "排队中",
  extracting: "提取中",
  analyzing: "分析中",
  storing: "存储中",
  embedding: "向量化",
  waiting_donor: "复用中",
  generating_lessons: "生成课文",
  generating_labs: "生成 Lab",
  assembling_course: "组装课程",
  ready: "已完成",
  error: "失败",
};

const TASK_TYPE_LABELS: Record<string, string> = {
  source_processing: "资料处理",
  course_generation: "课程生成",
};

function TypeIcon({ type }: { type: string }) {
  if (type === "youtube" || type === "bilibili") {
    return <Play className="w-4 h-4 text-blue-600" />;
  }

  return <FileText className="w-4 h-4 text-gray-500" />;
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

  if (task.status === "success") {
    return "已完成";
  }

  if (task.status === "failure") {
    return "失败";
  }

  if (task.status === "running") {
    return "进行中";
  }

  if (task.status === "pending") {
    return "排队中";
  }

  return task.status;
}

function TaskRow({ task }: { task?: SourceTaskSummary | null }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-gray-900">{getTaskLabel(task)}</p>
          <p className="mt-1 text-sm text-gray-500">{getTaskSummary(task)}</p>
        </div>
        {task?.status && (
          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
            {task.status}
          </span>
        )}
      </div>
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
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setConfirmingDelete(false);
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

  if (!source) {
    return null;
  }

  const presentation = deriveMaterialPresentation(source);

  return (
    <>
      {open && (
        <button
          aria-label="关闭资料详情"
          className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
          onClick={onClose}
          type="button"
        />
      )}

      <aside
        aria-hidden={!open}
        className={`fixed right-0 top-0 z-50 h-full w-full max-w-md border-l shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        style={{
          maxWidth: "min(28rem, calc(100vw - 1rem))",
          background: "var(--surface-alt)",
          borderColor: "var(--border)",
        }}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-start justify-between border-b border-gray-200 bg-white px-5 py-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <TypeIcon type={source.type} />
                <span>{source.type}</span>
              </div>
              <h2 className="mt-2 text-lg font-semibold text-gray-900">
                {source.title || source.url || "未命名资料"}
              </h2>
            </div>
            <button
              aria-label="关闭"
              className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
              onClick={onClose}
              type="button"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 space-y-6 overflow-y-auto p-5">
            <section>
              <h3 className="text-sm font-semibold text-gray-900">当前状态</h3>
              <div className="mt-3 rounded-2xl border border-blue-100 bg-blue-50 p-4">
                <p className="text-sm font-medium text-blue-900">{presentation.badge}</p>
                <p className="mt-1 text-sm text-blue-700">{presentation.supportingText}</p>
              </div>
            </section>

            <section>
              <h3 className="text-sm font-semibold text-gray-900">关键任务</h3>
              <div className="mt-3 space-y-3">
                <TaskRow task={source.latest_processing_task} />
                <TaskRow task={source.latest_course_task} />
              </div>
            </section>

            <section>
              <h3 className="text-sm font-semibold text-gray-900">资料信息</h3>
              <dl className="mt-3 space-y-3 rounded-2xl border border-gray-200 bg-white p-4">
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-sm text-gray-500">资料状态</dt>
                  <dd className="text-sm font-medium text-gray-900">
                    {getStageLabel(source.status) ?? source.status}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-sm text-gray-500">课程数量</dt>
                  <dd className="text-sm font-medium text-gray-900">{source.course_count}</dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-sm text-gray-500">更新时间</dt>
                  <dd className="text-sm font-medium text-gray-900">
                    {new Date(source.updated_at).toLocaleString("zh-CN")}
                  </dd>
                </div>
              </dl>
            </section>
          </div>

          <div className="border-t border-gray-200 bg-white p-5 space-y-3">
            {actionError ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {actionError}
              </p>
            ) : null}
            {presentation.primaryAction === "enter-course" && source.latest_course_id ? (
              <Link
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-700"
                href={`/path?courseId=${source.latest_course_id}`}
              >
                进入课程
                <ArrowRight className="w-4 h-4" />
              </Link>
            ) : canGenerateCourseFor(source) ? (
              <button
                type="button"
                disabled={generating}
                onClick={async () => {
                  if (!source) return;
                  setGenerating(true);
                  setActionError(null);
                  try {
                    await generateCourseForSource(source.id);
                    onChanged?.();
                    onClose();
                  } catch (err) {
                    setActionError(
                      err instanceof Error ? err.message : "课程生成失败，请稍后重试",
                    );
                  } finally {
                    setGenerating(false);
                  }
                }}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-60"
              >
                <IcSpark className="w-4 h-4" />
                {generating ? "正在派发…" : "生成课程"}
              </button>
            ) : canRetryFor(source) ? (
              <button
                type="button"
                disabled={retrying}
                onClick={async () => {
                  if (!source) return;
                  setRetrying(true);
                  setActionError(null);
                  try {
                    await retrySource(source.id);
                    onChanged?.();
                    onClose();
                  } catch (err) {
                    setActionError(
                      err instanceof Error ? err.message : "重试失败，请稍后再试",
                    );
                  } finally {
                    setRetrying(false);
                  }
                }}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-blue-200 bg-white px-4 py-2.5 text-sm font-medium text-blue-700 transition hover:bg-blue-50 disabled:opacity-60"
              >
                <IcRegen className="w-4 h-4" />
                {retrying ? "正在重试…" : "重试处理"}
              </button>
            ) : (
              <p className="text-sm text-gray-500">
                {presentation.category === "error"
                  ? "当前没有可进入的课程，请先查看失败原因。"
                  : "课程生成完成后，就可以从这里直接进入课程。"}
              </p>
            )}
            {confirmingDelete ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm">
                <p className="text-red-700">
                  确认删除？资料会从列表中移除，
                  {presentation.isActive ? "进行中的后台任务会被停止。" : "已生成的内容仍会保留在数据库。"}
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmingDelete(false)}
                    disabled={deleting}
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
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
                    className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-red-700 disabled:opacity-50"
                  >
                    {deleting ? "删除中…" : "确认删除"}
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50"
              >
                <IcTrash className="w-4 h-4" />
                删除资料
              </button>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
