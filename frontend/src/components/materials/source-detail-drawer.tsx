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
  getSourceProgress,
  listSourceChunks,
  listSourceCitations,
  retrySource,
  type SourceCitationCourse,
  type SourceChunkBrief,
  type SourceProgressResponse,
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
  processing: "处理中",
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

  return TASK_STATUS_LABELS[task.status] ?? task.status;
}

function getTaskStatusLabel(status?: string | null): string | null {
  if (!status) {
    return null;
  }

  return TASK_STATUS_LABELS[status] ?? status;
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
            {getTaskStatusLabel(task.status)}
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
  const sourceOrigin = getSourceOrigin(source);

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
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
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
        className="relative flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl shadow-2xl"
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

          <div className="flex-1 min-h-0 space-y-6 overflow-y-auto p-5">
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
                  <dt className="text-sm text-gray-500">资料来源</dt>
                  <dd className="min-w-0 text-right text-sm font-medium text-gray-900">
                    {sourceOrigin.href ? (
                      <a
                        href={sourceOrigin.href}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-block max-w-[360px] truncate text-blue-600 hover:underline"
                        title={sourceOrigin.label}
                      >
                        {sourceOrigin.label}
                      </a>
                    ) : (
                      <span
                        className="inline-block max-w-[360px] truncate"
                        title={sourceOrigin.label}
                      >
                        {sourceOrigin.label}
                      </span>
                    )}
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

            <SectionPlannerSection metadata={source.metadata_} />

            {/* PRD §11 Phase E — lazy-loaded chunks / citations / history. */}
            {open && source.id ? <ChunksSection sourceId={source.id} /> : null}
            {open && source.id ? <CitationsSection sourceId={source.id} /> : null}
            {open && source.id ? <HistorySection sourceId={source.id} /> : null}
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
  const [loading, setLoading] = useState(false);
  const [skip, setSkip] = useState(0);
  const PAGE = 5;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
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
      <h3 className="text-sm font-semibold text-gray-900">
        切片预览
        {data ? <span className="ml-2 text-xs text-gray-400">{data.total}</span> : null}
      </h3>
      <div className="mt-3 space-y-2">
        {data?.items.length === 0 && !loading ? (
          <p className="text-xs text-gray-500">暂无切片</p>
        ) : null}
        {data?.items.map((c, idx) => (
          <div
            key={c.id}
            className="rounded-xl border border-gray-200 bg-white p-3 text-xs"
          >
            <div className="mb-1 flex items-center justify-between text-[10px] text-gray-400">
              <span className="mono">#{idx + 1}</span>
              <span className="mono">{c.length} chars</span>
            </div>
            <p className="line-clamp-3 text-gray-700">{c.text}</p>
          </div>
        ))}
        {data && skip < data.total ? (
          <button
            type="button"
            className="text-xs text-blue-600 hover:underline disabled:opacity-50"
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
  if (!data) return null;
  if (data.items.length === 0) return null;
  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-900">
        该资料生成的课程
        <span className="ml-2 text-xs text-gray-400">{data.total}</span>
      </h3>
      <ul className="mt-3 space-y-2">
        {data.items.map((course) => (
          <li
            key={course.course_id}
            className="rounded-xl border border-gray-200 bg-white p-3"
            style={
              course.is_latest
                ? { borderColor: "var(--accent)", background: "var(--accent-soft)" }
                : undefined
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
                  ★ latest
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
                  className="text-sm font-medium text-blue-600 hover:underline"
                  style={{
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
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium hover:bg-white/60"
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
  if (!data || data.tasks.length === 0) return null;
  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-900">
        历史 <span className="ml-2 text-xs text-gray-400">{data.tasks.length}</span>
      </h3>
      <ul className="mt-3 space-y-2">
        {data.tasks.map((t) => (
          <li
            key={`${t.task_type}-${t.celery_task_id ?? t.created_at}`}
            className="rounded-xl border border-gray-200 bg-white p-3 text-xs"
          >
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-medium text-gray-700">{t.task_type}</span>
              <span
                className={
                  t.status === "success"
                    ? "text-emerald-600"
                    : t.status === "failure"
                      ? "text-red-600"
                      : "text-gray-500"
                }
              >
                {getTaskStatusLabel(t.status)}
              </span>
            </div>
            {t.stage ? (
              <p className="mt-1 text-[11px] text-gray-500 mono">
                {getStageLabel(t.stage) ?? t.stage}
              </p>
            ) : null}
            {t.error_summary ? (
              <p className="mt-1 text-[11px] text-red-500">{t.error_summary}</p>
            ) : null}
            <p className="mt-1 text-[10px] text-gray-400 mono">
              {new Date(t.created_at).toLocaleString("zh-CN")}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* SectionPlanner stats — surfaces the per-source metadata that
   ``app.services.section_planner.SectionPlanner`` writes during ingestion.
   Source.metadata_["section_planner_stats"] is optional; pre-Phase-1 sources
   simply don't render this block. */
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
    skeleton: "整段（Layer 1）",
    windowed: "分窗（Layer 2）",
    embedding_only: "向量兜底（Layer 3）",
    fallback: "逐 chunk 兜底（Layer 4）",
  };
  const tierBadgeClass =
    stats.tier_used === "fallback"
      ? "bg-amber-100 text-amber-800"
      : stats.tier_used === "embedding_only"
        ? "bg-purple-100 text-purple-800"
        : "bg-blue-100 text-blue-800";

  const formatMs = (ms: number) =>
    ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;

  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-900">章节规划</h3>
      <div className="mt-3 rounded-2xl border border-gray-200 bg-white p-4 space-y-3">
        <div className="flex items-center justify-between gap-4">
          <span className="text-sm text-gray-500">分桶策略</span>
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${tierBadgeClass}`}
          >
            {tierLabel[stats.tier_used] ?? stats.tier_used}
          </span>
        </div>
        {stats.short_circuit ? (
          <p className="text-xs text-gray-500">
            内容较短，整源归为一个 bucket，跳过 LLM 分析。
          </p>
        ) : null}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div className="flex items-center justify-between">
            <dt className="text-gray-500">桶数</dt>
            <dd className="font-medium text-gray-900">{stats.bucket_count}</dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-gray-500">每桶平均 chunk</dt>
            <dd className="font-medium text-gray-900">
              {stats.avg_chunks_per_bucket}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-gray-500">最小 / 最大</dt>
            <dd className="font-medium text-gray-900">
              {stats.min_chunks_per_bucket} / {stats.max_chunks_per_bucket}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-gray-500">命名唯一度</dt>
            <dd
              className={`font-medium ${
                stats.topic_uniqueness < 0.7
                  ? "text-amber-600"
                  : "text-gray-900"
              }`}
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
            <dt className="text-gray-500">耗时</dt>
            <dd className="font-medium text-gray-900">
              {formatMs(stats.planning_duration_ms)}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-gray-500">Token in / out</dt>
            <dd className="font-medium text-gray-900 mono text-xs">
              {stats.llm_input_tokens} / {stats.llm_output_tokens}
            </dd>
          </div>
        </dl>
        <div className="flex items-center justify-between text-[11px] text-gray-400 mono">
          <span>planner: {stats.planner_version}</span>
          {stats.error ? (
            <span
              className="truncate text-amber-600"
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
