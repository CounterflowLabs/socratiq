"use client";

import { Suspense } from "react";
import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  BookOpen,
  FlaskConical,
  BarChart3,
  CheckCircle2,
  Loader2,
  Sparkles,
} from "lucide-react";
import { clsx } from "clsx";

import RegenerateDrawer from "@/components/learn/regenerate-drawer";
import {
  clearCourseRegeneration,
  getCourse,
  getCourseProgress,
  getRegenerationStatus,
  regenerateCourse,
  type CourseDetailResponse,
  type RegenerationStatus,
  type SectionResponse,
} from "@/lib/api";

const STAGE_LABELS_ZH: Record<string, string> = {
  analyzing: "分析内容",
  planning: "规划教学资产",
  generating_lessons: "生成课文",
  generating_labs: "生成 Lab",
  assembling: "组装课程",
  source_done: "资料处理完成",
};

const STAGE_PERCENT_RANGES: Record<string, [number, number]> = {
  pending: [0, 5],
  analyzing: [5, 25],
  generating_lessons: [25, 70],
  generating_labs: [70, 90],
  assembling: [90, 100],
};

function computeRegenPercent(status: RegenerationStatus): number {
  if (status.status === "success") return 100;
  if (status.status === "failure") return 0;
  const stage = status.stage ?? "pending";
  const [base, ceiling] = STAGE_PERCENT_RANGES[stage] ?? [0, 100];
  const c = status.current;
  const t = status.total;
  if (typeof c === "number" && typeof t === "number" && t > 0) {
    return Math.round(base + (c / t) * (ceiling - base));
  }
  return base;
}

type SectionProgress = {
  section_id: string;
  lesson_read: boolean;
  lab_completed: boolean;
  exercise_best_score: number | null;
  status: string;
};

/** Extract concept names from section content. */
function extractConcepts(content: Record<string, unknown>): string[] {
  if (Array.isArray(content.key_terms)) {
    return (content.key_terms as unknown[])
      .map((c) =>
        typeof c === "string"
          ? c
          : typeof c === "object" && c !== null && "name" in c
          ? String((c as Record<string, unknown>).name)
          : ""
      )
      .filter(Boolean)
      .slice(0, 5);
  }
  if (Array.isArray(content.concepts)) {
    return (content.concepts as unknown[])
      .map((c) =>
        typeof c === "string"
          ? c
          : typeof c === "object" && c !== null && "name" in c
          ? String((c as Record<string, unknown>).name)
          : ""
      )
      .filter(Boolean)
      .slice(0, 5);
  }
  return [];
}

/** Render filled/empty difficulty dots on a 1–5 scale. */
function DifficultyDots({ difficulty }: { difficulty: number }) {
  const filled = Math.min(5, Math.max(1, Math.round(difficulty)));
  return (
    <span className="flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className="inline-block w-2 h-2 rounded-full"
          style={{ background: i < filled ? "var(--text-secondary)" : "var(--border-medium)" }}
        />
      ))}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "completed") {
    return (
      <span className="badge" style={{ background: "var(--success-light)", color: "var(--success)", fontSize: 12 }}>
        ✅ 已完成
      </span>
    );
  }
  if (status === "in_progress") {
    return (
      <span className="badge" style={{ background: "var(--primary-light)", color: "var(--primary)", fontSize: 12 }}>
        🔵 进行中
      </span>
    );
  }
  return (
    <span className="badge" style={{ background: "var(--surface-alt)", color: "var(--text-tertiary)", fontSize: 12 }}>
      ○ 未开始
    </span>
  );
}

function SectionCard({
  section,
  index,
  progress,
  courseId,
}: {
  section: SectionResponse;
  index: number;
  progress: SectionProgress | undefined;
  courseId: string;
}) {
  const router = useRouter();
  const concepts = extractConcepts(section.content);
  const hasCode = Boolean(section.content.has_code);
  const status = progress?.status ?? "not_started";
  const lessonRead = progress?.lesson_read ?? false;
  const labCompleted = progress?.lab_completed ?? false;
  const score = progress?.exercise_best_score ?? null;

  return (
    <button
      onClick={() => router.push(`/learn?sectionId=${section.id}&courseId=${courseId}`)}
      className="w-full text-left bg-transparent border-none p-0 cursor-pointer"
    >
      <div className="card-flat hover:border-gray-300 transition-colors">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
              {index + 1}.
            </span>
            <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              {section.title}
            </h3>
          </div>
          <StatusBadge status={status} />
        </div>

        {/* Difficulty + concepts row */}
        <div className="flex items-center gap-3 flex-wrap mb-3">
          <div className="flex items-center gap-1.5">
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              难度:
            </span>
            <DifficultyDots difficulty={section.difficulty} />
          </div>
          {concepts.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              {concepts.map((c) => (
                <span
                  key={c}
                  className="px-1.5 py-0.5 rounded text-xs"
                  style={{ background: "var(--surface-alt)", color: "var(--text-secondary)" }}
                >
                  {c}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Progress indicators row */}
        <div className="flex items-center gap-5 text-xs" style={{ color: "var(--text-tertiary)" }}>
          {/* Lesson */}
          <span className="flex items-center gap-1">
            <BookOpen className="w-3.5 h-3.5" />
            <span>课文</span>
            {lessonRead ? (
              <span className="font-medium" style={{ color: "var(--success)" }}>
                已读
              </span>
            ) : (
              <span style={{ color: "var(--text-tertiary)" }}>--</span>
            )}
          </span>

          {/* Lab — only show if section has code content */}
          {hasCode && (
            <span className="flex items-center gap-1">
              <FlaskConical className="w-3.5 h-3.5" />
              <span>Lab</span>
              {labCompleted ? (
                <span className="font-medium" style={{ color: "var(--success)" }}>
                  完成
                </span>
              ) : (
                <span style={{ color: "var(--text-tertiary)" }}>--</span>
              )}
            </span>
          )}

          {/* Exercise score */}
          <span className="flex items-center gap-1">
            <BarChart3 className="w-3.5 h-3.5" />
            <span>练习</span>
            {score !== null ? (
              <span className="font-medium" style={{ color: "var(--success)" }}>
                {Math.round(score)}%
              </span>
            ) : (
              <span style={{ color: "var(--text-tertiary)" }}>--</span>
            )}
          </span>
        </div>
      </div>
    </button>
  );
}

function PathContent() {
  const searchParams = useSearchParams();
  const courseId = searchParams.get("courseId");
  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [progressMap, setProgressMap] = useState<Map<string, SectionProgress>>(new Map());
  const [loading, setLoading] = useState(!!courseId);
  const [error, setError] = useState<string | null>(courseId ? null : "未提供课程 ID");
  const router = useRouter();

  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [regenerateBusy, setRegenerateBusy] = useState(false);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);
  const [regenTaskId, setRegenTaskId] = useState<string | null>(null);
  const [regenStatus, setRegenStatus] = useState<RegenerationStatus | null>(null);

  useEffect(() => {
    if (!courseId) return;

    Promise.all([getCourse(courseId), getCourseProgress(courseId)])
      .then(([courseData, progressData]) => {
        setCourse(courseData);
        const map = new Map<string, SectionProgress>();
        for (const p of progressData) {
          map.set(p.section_id, p);
        }
        setProgressMap(map);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载课程失败"))
      .finally(() => setLoading(false));
  }, [courseId]);

  useEffect(() => {
    const persisted = course?.active_regeneration_task_id;
    if (persisted && persisted !== regenTaskId) {
      setRegenTaskId(persisted);
      setRegenStatus({ status: "pending" });
    }
  }, [course?.active_regeneration_task_id, regenTaskId]);

  useEffect(() => {
    if (!regenTaskId) return;
    if (regenStatus?.status === "success" || regenStatus?.status === "failure") return;

    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const update = await getRegenerationStatus(regenTaskId);
        if (cancelled) return;
        setRegenStatus(update);
        if (update.status !== "success" && update.status !== "failure") {
          setTimeout(tick, 3000);
        }
      } catch (err) {
        if (cancelled) return;
        setRegenStatus({
          status: "failure",
          error: err instanceof Error ? err.message : "Polling failed",
        });
      }
    };
    void tick();

    return () => {
      cancelled = true;
    };
  }, [regenTaskId, regenStatus?.status]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ color: "var(--text-tertiary)" }}>
        加载中…
      </div>
    );
  }

  if (error || !course) {
    return (
      <div className="min-h-screen flex items-center justify-center text-red-500">
        {error ?? "课程未找到"}
      </div>
    );
  }

  const sections = [...(course.sections ?? [])].sort(
    (a, b) => (a.order_index ?? 0) - (b.order_index ?? 0)
  );

  const versionIndex = course.version_index ?? 1;
  const parentHref = course.parent_id ? `/path?courseId=${course.parent_id}` : null;
  const banner = regenStatus
    ? {
        state:
          regenStatus.status === "success"
            ? ("ready" as const)
            : regenStatus.status === "failure"
            ? ("failed" as const)
            : ("running" as const),
        stage: regenStatus.stage ?? null,
        current: regenStatus.current ?? null,
        total: regenStatus.total ?? null,
        newCourseId: regenStatus.course_id,
        message: regenStatus.error,
      }
    : null;

  const dismissBanner = () => {
    if (courseId) {
      void clearCourseRegeneration(courseId).catch(() => {});
    }
    setRegenStatus(null);
    setRegenTaskId(null);
    setCourse((prev) =>
      prev ? { ...prev, active_regeneration_task_id: null } : prev
    );
  };

  const openNewVersion = () => {
    const newCourseId = regenStatus?.course_id;
    if (!newCourseId) return;
    if (courseId) {
      void clearCourseRegeneration(courseId).catch(() => {});
    }
    setRegenStatus(null);
    setRegenTaskId(null);
    setCourse((prev) =>
      prev ? { ...prev, active_regeneration_task_id: null } : prev
    );
    router.push(`/path?courseId=${newCourseId}`);
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <header
        className="px-6 py-4 border-b"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="max-w-2xl mx-auto">
          <div className="flex items-start justify-between gap-3 mb-3">
            <Link
              href="/"
              className="flex items-center gap-1 text-xs no-underline"
              style={{ color: "var(--text-secondary)" }}
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              返回
            </Link>
            <button
              type="button"
              onClick={() => setRegenerateOpen(true)}
              disabled={banner?.state === "running"}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition hover:bg-violet-50 disabled:opacity-60"
              style={{ borderColor: "var(--border-medium)", color: "var(--text-secondary)" }}
            >
              <Sparkles className="h-3.5 w-3.5 text-violet-500" />
              重新生成
            </button>
          </div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-lg font-bold" style={{ color: "var(--text)" }}>
              {course.title}
            </h1>
            {versionIndex > 1 ? (
              <span
                className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700"
                title="该课程是从先前版本重新生成的"
              >
                第 {versionIndex} 版
                {parentHref ? (
                  <>
                    {" · "}
                    <Link href={parentHref} className="underline-offset-2 hover:underline">
                      上一版
                    </Link>
                  </>
                ) : null}
              </span>
            ) : null}
          </div>
          {course.description && (
            <p className="text-sm mt-1 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {course.description}
            </p>
          )}
        </div>
      </header>

      {banner ? (
        <div
          className={clsx(
            "border-b px-6 py-3 text-sm",
            banner.state === "running" && "bg-violet-50 text-violet-800 border-violet-200",
            banner.state === "ready" && "bg-emerald-50 text-emerald-800 border-emerald-200",
            banner.state === "failed" && "bg-red-50 text-red-800 border-red-200"
          )}
        >
          <div className="max-w-2xl mx-auto flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                {banner.state === "running" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : banner.state === "ready" ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : null}
                <span>
                  {banner.state === "running" ? (
                    <>
                      重新生成中 ·{" "}
                      {STAGE_LABELS_ZH[banner.stage ?? ""] ?? banner.stage ?? "进行中"}
                      {typeof banner.current === "number" &&
                      typeof banner.total === "number" &&
                      banner.total > 1
                        ? ` (${banner.current}/${banner.total})`
                        : ""}
                      {" · "}
                      {regenStatus ? computeRegenPercent(regenStatus) : 0}%
                    </>
                  ) : banner.state === "ready" ? (
                    "新版本已生成完毕。"
                  ) : (
                    banner.message ?? "重新生成失败。"
                  )}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {banner.state === "ready" && banner.newCourseId ? (
                  <button
                    type="button"
                    onClick={openNewVersion}
                    className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700"
                  >
                    打开新版本
                  </button>
                ) : null}
                {banner.state !== "running" ? (
                  <button
                    type="button"
                    onClick={dismissBanner}
                    className="rounded-md px-2 py-1 text-xs font-medium opacity-70 transition hover:opacity-100"
                  >
                    关闭
                  </button>
                ) : null}
              </div>
            </div>
            {banner.state === "running" && regenStatus ? (
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-violet-100">
                <div
                  className="h-full rounded-full bg-violet-500 transition-all duration-500 ease-out"
                  style={{ width: `${computeRegenPercent(regenStatus)}%` }}
                />
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* Section list */}
      <div className="max-w-2xl mx-auto px-6 py-8">
        <div className="space-y-3">
          {sections.map((section: SectionResponse, idx: number) => (
            <SectionCard
              key={section.id}
              section={section}
              index={idx}
              progress={progressMap.get(section.id)}
              courseId={courseId!}
            />
          ))}
        </div>
      </div>

      <RegenerateDrawer
        open={regenerateOpen}
        initialDirective={course.regeneration_directive ?? ""}
        pending={regenerateBusy}
        errorMessage={regenerateError}
        onClose={() => {
          if (!regenerateBusy) {
            setRegenerateOpen(false);
            setRegenerateError(null);
          }
        }}
        onSubmit={async (directive) => {
          if (!courseId) return;
          setRegenerateBusy(true);
          setRegenerateError(null);
          try {
            const res = await regenerateCourse(courseId, directive || undefined);
            setRegenTaskId(res.task_id);
            setRegenStatus({ status: "pending" });
            setRegenerateOpen(false);
          } catch (err) {
            setRegenerateError(
              err instanceof Error ? err.message : "无法启动重新生成"
            );
          } finally {
            setRegenerateBusy(false);
          }
        }}
      />
    </div>
  );
}

export default function PathPage() {
  return (
    <Suspense
      fallback={
        <div
          className="min-h-screen flex items-center justify-center"
          style={{ color: "var(--text-tertiary)" }}
        >
          加载中…
        </div>
      }
    >
      <PathContent />
    </Suspense>
  );
}
