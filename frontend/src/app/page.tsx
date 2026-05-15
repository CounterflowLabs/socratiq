"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import {
  IcAlert,
  IcArrowRight,
  IcCheck,
  IcClose,
  IcFilter,
  IcLoader,
  IcPlus,
  SourceIcon,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageHeader } from "@/components/ui/page-header";
import { SectionTitle } from "@/components/ui/section-title";
import { Progress } from "@/components/ui/progress-bar";
import {
  listCourses,
  listTasks,
  getSetupStatus,
  getSourceProgress,
  getDueReviews,
  completeReview,
  getCourseProgress,
  cancelSource,
  retrySource,
  deleteSource,
  type CourseResponse,
  type ReviewItemDetail,
  type SourceProgressResponse,
  type TaskListItem,
  type TaskTypeUi,
} from "@/lib/api";
import { useCoursesStore, useTasksStore } from "@/lib/stores";
import { useT } from "@/lib/i18n";
import { stageToPercent } from "@/app/tasks/page";
import ReviewCard from "@/components/review-card";
import SourcePipelineView from "@/components/materials/source-pipeline-view";

interface DerivedTaskState {
  state: string;
  courseId?: string;
  nextTaskId?: string;
  error?: string;
}

function deriveStateFromProgress(
  progress: SourceProgressResponse,
  currentTaskId: string,
): DerivedTaskState {
  const byType: Record<string, SourceProgressResponse["tasks"][number]> = {};
  for (const task of progress.tasks) byType[task.task_type] = task;
  const proc = byType.source_processing;
  const gen = byType.course_generation;

  if (gen?.status === "success" && (gen.course_id || progress.course_id)) {
    return {
      state: "SUCCESS",
      courseId: gen.course_id ?? progress.course_id ?? undefined,
    };
  }

  if (proc?.status === "failure" || gen?.status === "failure") {
    return {
      state: "FAILURE",
      error:
        gen?.error_summary ||
        proc?.error_summary ||
        progress.error ||
        "导入失败，但后端没有返回更具体的原因。",
    };
  }

  if (proc?.status === "success" && gen) {
    if (gen.celery_task_id && gen.celery_task_id !== currentTaskId) {
      return { state: "assembling_course", nextTaskId: gen.celery_task_id };
    }
    return { state: gen.stage ?? "generating_course" };
  }

  return { state: proc?.stage ?? progress.source_status ?? "PENDING" };
}

interface CourseProgress {
  completed: number;
  total: number;
}

function taskStateLabel(state: string, lang: "zh" | "en"): string {
  const labelsZh: Record<string, string> = {
    PENDING: "排队中…",
    cloning: "复用已有字幕与转写…",
    extracting: "提取字幕…",
    analyzing: "分析内容…",
    generating_lessons: "生成课文…",
    generating_labs: "生成 Lab…",
    storing: "存储数据…",
    embedding: "计算向量…",
    assembling_course: "组装课程…",
    generating_course: "生成课程…",
    SUCCESS: "处理完成",
    FAILURE: "处理失败",
  };
  const labelsEn: Record<string, string> = {
    PENDING: "Queued…",
    cloning: "Reusing existing subtitles…",
    extracting: "Fetching transcript…",
    analyzing: "Analyzing content…",
    generating_lessons: "Generating lessons…",
    generating_labs: "Generating labs…",
    storing: "Persisting…",
    embedding: "Computing embeddings…",
    assembling_course: "Assembling course…",
    generating_course: "Generating course…",
    SUCCESS: "Done",
    FAILURE: "Failed",
  };
  const map = lang === "en" ? labelsEn : labelsZh;
  return map[state] || state;
}

export default function DashboardPage() {
  const router = useRouter();
  const { t, lang } = useT();
  const { courses, setCourses, loading, setLoading } = useCoursesStore();
  const { tasks, updateTask, removeTask } = useTasksStore();

  const [dueReviews, setDueReviews] = useState<ReviewItemDetail[]>([]);
  const [ratingIds, setRatingIds] = useState<Set<string>>(new Set());
  const [allReviewsDone, setAllReviewsDone] = useState(false);
  const [courseProgressMap, setCourseProgressMap] = useState<Record<string, CourseProgress>>({});
  const [progressMap, setProgressMap] = useState<Record<string, SourceProgressResponse>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refreshCourses = () =>
      listCourses()
        .then((res) => {
          if (cancelled) return;
          setCourses(res.items);
          setLoadError(null);
        })
        .catch((err) => {
          if (cancelled) return;
          setLoadError(err instanceof Error ? err.message : t("dashboard.loadFailed"));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });

    getSetupStatus()
      .then((status) => {
        if (cancelled) return;
        if (!status.has_models) {
          router.replace("/setup");
          return;
        }
        setLoading(true);
        void refreshCourses();
        getDueReviews()
          .then((res) => !cancelled && setDueReviews(res.items))
          .catch(() => {});
      })
      .catch(() => {
        // Setup endpoint may be unavailable in dev; don't block the dashboard.
        setLoading(true);
        void refreshCourses();
        getDueReviews()
          .then((res) => !cancelled && setDueReviews(res.items))
          .catch(() => {});
      });

    return () => {
      cancelled = true;
    };
  }, [router, setCourses, setLoading, t]);

  useEffect(() => {
    if (courses.length === 0) return;
    courses.forEach((course) => {
      getCourseProgress(course.id)
        .then((items) => {
          const total = items.length;
          const completed = items.filter(
            (item) => item.lesson_read || item.exercise_best_score !== null || item.lab_completed,
          ).length;
          setCourseProgressMap((prev) => ({
            ...prev,
            [course.id]: { completed, total },
          }));
        })
        .catch(() => {});
    });
  }, [courses]);

  const handleRate = useCallback(async (reviewId: string, quality: number) => {
    setRatingIds((prev) => new Set(prev).add(reviewId));
    try {
      await completeReview(reviewId, quality);
    } catch {
      // silently swallow — the user can re-rate later.
    }
    setDueReviews((prev) => {
      const next = prev.filter((r) => r.id !== reviewId);
      if (next.length === 0) setAllReviewsDone(true);
      return next;
    });
    setRatingIds((prev) => {
      const next = new Set(prev);
      next.delete(reviewId);
      return next;
    });
  }, []);

  // Poll active tasks via /sources/{id}/progress (DB-authoritative).
  useEffect(() => {
    const activeTasks = tasks.filter(
      (task) => task.state !== "SUCCESS" && task.state !== "FAILURE" && !task.courseId,
    );
    if (activeTasks.length === 0) return;

    const interval = setInterval(async () => {
      for (const task of activeTasks) {
        try {
          const progress = await getSourceProgress(task.sourceId).catch(() => null);
          if (!progress) continue;
          setProgressMap((prev) => ({ ...prev, [task.sourceId]: progress }));

          const derived = deriveStateFromProgress(progress, task.taskId);

          if (derived.nextTaskId && derived.nextTaskId !== task.taskId) {
            updateTask(task.taskId, {
              taskId: derived.nextTaskId,
              state: derived.state,
              error: derived.error,
              courseId: derived.courseId,
            });
            continue;
          }

          updateTask(task.taskId, {
            state: derived.state,
            error: derived.error,
            courseId: derived.courseId,
          });

          if (derived.courseId) {
            listCourses()
              .then((res) => setCourses(res.items))
              .catch(() => {});
            setTimeout(() => removeTask(task.taskId), 8000);
          }
        } catch {
          // retry on next interval
        }
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [tasks, updateTask, removeTask, setCourses]);

  const dueCount = dueReviews.length;
  const showReviewSection = dueCount > 0 || allReviewsDone;

  // Hero = the most recently touched course. The backend already orders
  // /courses by updated_at desc, so first item is right.
  const heroCourse = courses[0] ?? null;
  const heroProgress = heroCourse ? courseProgressMap[heroCourse.id] : null;
  const heroPct =
    heroProgress && heroProgress.total > 0
      ? Math.round((heroProgress.completed / heroProgress.total) * 100)
      : 0;
  const todayLabel = new Date().toLocaleDateString(
    lang === "zh" ? "zh-CN" : "en-US",
    { weekday: "long", month: "long", day: "numeric" },
  );

  function relativeTime(iso: string): string {
    const now = Date.now();
    const then = new Date(iso).getTime();
    const diffMs = now - then;
    const minutes = Math.round(diffMs / 60_000);
    if (minutes < 1) return lang === "zh" ? "刚刚" : "just now";
    if (minutes < 60) return lang === "zh" ? `${minutes} 分钟前` : `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return lang === "zh" ? `${hours} 小时前` : `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days === 1) return t("common.yesterday");
    if (days < 7) return lang === "zh" ? `${days} 天前` : `${days}d ago`;
    if (days < 30) return lang === "zh" ? `${Math.round(days / 7)} 周前` : `${Math.round(days / 7)}w ago`;
    return new Date(iso).toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US", {
      month: "short",
      day: "numeric",
    });
  }

  return (
    <div className="page-shell" style={{ padding: "32px 40px 80px", maxWidth: 1100, margin: "0 auto", width: "100%" }}>
      <PageHeader
        eyebrow={todayLabel}
        title={t("dashboard.title")}
        subtitle={t("dashboard.subtitle")}
        action={
          <Link href="/import" className="btn btn-outline">
            <IcPlus size={14} />
            <span>{t("common.new")}</span>
          </Link>
        }
      />

      {/* Pickup hero — rendered even when courses are still loading, so the
          shell doesn't pop in. */}
      {heroCourse ? (
        <div
          // The hero is conceptually a card-link but it contains nested
          // buttons (Continue, Mentor), so it has to be a div + role=link
          // rather than a native <button> — buttons can't nest buttons.
          role="link"
          tabIndex={0}
          onClick={(e) => {
            if (e.target instanceof HTMLElement && e.target.closest("button, a")) return;
            router.push(`/learn?courseId=${heroCourse.id}`);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              router.push(`/learn?courseId=${heroCourse.id}`);
            }
          }}
          className="card"
          style={{
            marginBottom: "var(--gap-xl)",
            padding: 0,
            overflow: "hidden",
            display: "grid",
            gridTemplateColumns: "1.4fr 1fr",
            cursor: "pointer",
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--ink)",
            textAlign: "left",
            fontFamily: "inherit",
            width: "100%",
          }}
        >
          <div style={{ padding: 28 }}>
            <Eyebrow>{t("dashboard.pickup")}</Eyebrow>
            <h2
              className="display"
              style={{ fontSize: 28, margin: "8px 0 6px", fontWeight: 400 }}
            >
              {heroCourse.title}
            </h2>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                color: "var(--ink-3)",
                fontSize: 12,
                marginBottom: 20,
                lineHeight: 1.5,
              }}
            >
              <SourceIcon size={14} />
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 280,
                }}
              >
                {heroCourse.description || (lang === "zh" ? "学习路径" : "Learning path")}
              </span>
              <span>·</span>
              <span>{relativeTime(heroCourse.updated_at)}</span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span
                className="mono num"
                style={{ fontSize: 12, color: "var(--ink-2)" }}
              >
                {String(heroProgress?.completed ?? 0).padStart(2, "0")} /{" "}
                {String(heroProgress?.total ?? 0).padStart(2, "0")}
              </span>
              <span className="eyebrow" style={{ flex: 1 }}>
                {t("common.progress")}
              </span>
              <span
                className="mono num"
                style={{ fontSize: 12, color: "var(--accent)", fontWeight: 500 }}
              >
                {heroPct}%
              </span>
            </div>
            <Progress value={heroPct} color="var(--accent)" height={3} />

            <div style={{ marginTop: 24, display: "flex", gap: 8 }}>
              <span className="btn btn-primary">
                <IcArrowRight size={14} />
                <span>{t("common.continue")}</span>
              </span>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={(e) => {
                  e.stopPropagation();
                  router.push(`/learn?courseId=${heroCourse.id}&panel=tutor`);
                }}
              >
                {t("common.mentor")}
              </button>
            </div>
          </div>

          <div
            className="hatched"
            style={{
              position: "relative",
              minHeight: 200,
              borderLeft: "1px solid var(--border)",
            }}
          >
            <svg
              viewBox="0 0 200 200"
              style={{ width: "100%", height: "100%", display: "block" }}
            >
              <line x1="100" y1="100" x2="60" y2="50" stroke="var(--ink-4)" strokeWidth="1" />
              <line x1="100" y1="100" x2="150" y2="60" stroke="var(--ink-4)" strokeWidth="1" />
              <line x1="100" y1="100" x2="55" y2="150" stroke="var(--ink-4)" strokeWidth="1" />
              <line x1="100" y1="100" x2="155" y2="145" stroke="var(--ink-4)" strokeWidth="1" />
              <circle cx="60" cy="50" r="5" fill="var(--sage)" />
              <circle cx="150" cy="60" r="5" fill="var(--sage)" />
              <circle cx="55" cy="150" r="5" fill="var(--ink-3)" />
              <circle cx="155" cy="145" r="5" fill="var(--accent)" />
              <circle cx="100" cy="100" r="11" fill="var(--surface)" stroke="var(--ink)" strokeWidth="1.5" />
              <circle cx="100" cy="100" r="4" fill="var(--accent)" />
            </svg>
            <div
              style={{
                position: "absolute",
                bottom: 16,
                left: 16,
                right: 16,
                fontSize: 11,
                color: "var(--ink-3)",
                display: "flex",
                justifyContent: "space-between",
              }}
            >
              <span className="eyebrow">{t("dashboard.conceptNeighborhood")}</span>
            </div>
          </div>
        </div>
      ) : null}

      {/* Review */}
      {showReviewSection ? (
        <section style={{ marginBottom: "var(--gap-xl)" }}>
          <SectionTitle
            count={dueCount}
            action={
              <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
                SM-2
              </span>
            }
          >
            {t("common.review")}
          </SectionTitle>

          {allReviewsDone ? (
            <div
              className="card-quiet"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                padding: "32px 16px",
                color: "var(--sage)",
                fontWeight: 500,
              }}
            >
              <IcCheck size={16} />
              <span>{t("common.allDone")}</span>
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: "var(--gap-md)",
              }}
            >
              {dueReviews.map((item) => (
                <ReviewCard
                  key={item.id}
                  conceptName={item.concept_name}
                  question={item.review_question}
                  answer={item.review_answer}
                  onRate={(quality) => handleRate(item.id, quality)}
                  disabled={ratingIds.has(item.id)}
                />
              ))}
            </div>
          )}
        </section>
      ) : null}

      {/* PRD §5.1 — two parallel rails (embed vs generate). Renders only
          when at least one rail has live tasks. */}
      <ProcessingRails />

      {/* Active processing tasks — inline, no card-with-loader */}
      {tasks.length > 0 ? (
        <section style={{ marginBottom: "var(--gap-xl)" }}>
          <SectionTitle>{t("common.processing")}</SectionTitle>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {tasks.map((task) => {
              const progress = progressMap[task.sourceId] ?? null;
              return (
                <div key={task.taskId} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div
                    className="card"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 16,
                      padding: 16,
                    }}
                  >
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: 8,
                        background:
                          task.state === "FAILURE"
                            ? "var(--error-soft)"
                            : task.courseId
                              ? "var(--sage-soft)"
                              : "var(--accent-soft)",
                        color:
                          task.state === "FAILURE"
                            ? "var(--error)"
                            : task.courseId
                              ? "var(--sage)"
                              : "var(--accent)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                      }}
                    >
                      {task.state === "FAILURE" ? (
                        <IcAlert size={16} />
                      ) : task.courseId ? (
                        <IcCheck size={16} />
                      ) : (
                        <IcLoader size={16} className="spin" />
                      )}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>{task.title}</div>
                      <div
                        style={{
                          fontSize: 11,
                          color: "var(--ink-3)",
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        <span className="mono">{task.error || taskStateLabel(task.state, lang)}</span>
                      </div>
                    </div>
                    {task.courseId ? (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => {
                          router.push(`/path?courseId=${task.courseId}`);
                          removeTask(task.taskId);
                        }}
                      >
                        <span>{t("common.enterCourse")}</span>
                      </button>
                    ) : null}
                    {task.state === "FAILURE" ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon"
                        onClick={() => removeTask(task.taskId)}
                        aria-label={t("common.close")}
                      >
                        <IcClose size={12} />
                      </button>
                    ) : null}
                  </div>
                  {progress && !task.courseId ? (
                    <SourcePipelineView
                      progress={progress}
                      title={task.title}
                      onCancel={async () => {
                        await cancelSource(task.sourceId);
                        const fresh = await getSourceProgress(task.sourceId).catch(() => null);
                        if (fresh) {
                          setProgressMap((prev) => ({ ...prev, [task.sourceId]: fresh }));
                        }
                      }}
                      onRetry={async () => {
                        const res = await retrySource(task.sourceId);
                        updateTask(task.taskId, {
                          taskId: res.task_id,
                          state: "PENDING",
                          error: undefined,
                        });
                        const fresh = await getSourceProgress(task.sourceId).catch(() => null);
                        if (fresh) {
                          setProgressMap((prev) => ({ ...prev, [task.sourceId]: fresh }));
                        }
                      }}
                      onDelete={async () => {
                        await deleteSource(task.sourceId);
                        removeTask(task.taskId);
                        setProgressMap((prev) => {
                          const next = { ...prev };
                          delete next[task.sourceId];
                          return next;
                        });
                      }}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {/* Course grid */}
      <section>
        <SectionTitle
          count={courses.length}
          action={
            <button type="button" className="btn btn-ghost btn-sm">
              <IcFilter size={12} />
              <span>{t("common.filter")}</span>
            </button>
          }
        >
          {t("common.myCourses")}
        </SectionTitle>

        {loadError ? (
          <div className="card" style={{ textAlign: "center", padding: 32 }}>
            <IcAlert size={28} style={{ color: "var(--error)", margin: "0 auto 12px" }} />
            <h3 className="serif" style={{ fontSize: 17, margin: "0 0 6px" }}>
              {t("dashboard.loadFailed")}
            </h3>
            <p style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 18 }}>{loadError}</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setLoadError(null);
                setLoading(true);
                listCourses()
                  .then((res) => {
                    setCourses(res.items);
                    setLoadError(null);
                  })
                  .catch((err) =>
                    setLoadError(err instanceof Error ? err.message : t("dashboard.loadFailed")),
                  )
                  .finally(() => setLoading(false));
              }}
            >
              {t("common.retry")}
            </button>
          </div>
        ) : loading ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "64px 0",
              color: "var(--ink-3)",
              gap: 8,
              fontSize: 13,
            }}
          >
            <IcLoader size={16} className="spin" />
            <span>{t("common.loading")}</span>
          </div>
        ) : courses.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: 40 }}>
            <h3 className="serif" style={{ fontSize: 18, margin: "0 0 8px" }}>
              {t("dashboard.empty")}
            </h3>
            <p
              style={{
                fontSize: 13,
                color: "var(--ink-2)",
                marginBottom: 24,
                maxWidth: 440,
                marginInline: "auto",
                lineHeight: 1.6,
              }}
            >
              {t("dashboard.emptyHint")}
            </p>
            <Link href="/import" className="btn btn-accent">
              <IcPlus size={14} />
              <span>{t("dashboard.importFirst")}</span>
            </Link>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
              gap: "var(--gap-md)",
            }}
          >
            {courses.map((course, idx) => {
              const progress = courseProgressMap[course.id];
              return (
                <CourseCard
                  key={course.id}
                  course={course}
                  index={idx}
                  progress={progress}
                  onOpen={() => router.push(`/path?courseId=${course.id}`)}
                  lessonsLabel={t("common.lessons")}
                  lastTouched={relativeTime(course.updated_at)}
                />
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function CourseCard({
  course,
  index,
  progress,
  onOpen,
  lessonsLabel,
  lastTouched,
}: {
  course: CourseResponse;
  index: number;
  progress: { completed: number; total: number } | undefined;
  onOpen: () => void;
  lessonsLabel: string;
  lastTouched: string;
}) {
  const accentColor =
    index % 3 === 0 ? "var(--accent)" : index % 3 === 1 ? "var(--sage)" : "var(--ink)";
  const pct =
    progress && progress.total > 0
      ? Math.round((progress.completed / progress.total) * 100)
      : 0;
  const isDone = progress && progress.completed >= progress.total && progress.total > 0;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="card"
      style={{
        textAlign: "left",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        gap: 16,
        padding: 18,
        position: "relative",
        overflow: "hidden",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        color: "var(--ink)",
        transition: "border-color var(--duration-fast) ease",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 3,
          height: 24,
          background: accentColor,
        }}
      />
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 6,
            background: "var(--surface-2)",
            color: "var(--ink-2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            border: "1px solid var(--border)",
          }}
        >
          <SourceIcon size={16} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3
            className="serif"
            style={{
              fontSize: 17,
              fontWeight: 500,
              margin: 0,
              lineHeight: 1.3,
              color: "var(--ink)",
            }}
          >
            {course.title}
          </h3>
          {course.description ? (
            <div
              style={{
                fontSize: 11,
                color: "var(--ink-3)",
                marginTop: 4,
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              {course.description}
            </div>
          ) : null}
        </div>
        {isDone ? <IcCheck size={14} style={{ color: "var(--sage)", flexShrink: 0 }} /> : null}
      </div>

      <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--ink-3)" }}>
        <span>
          <span className="mono num" style={{ color: "var(--ink-2)" }}>
            {progress ? progress.total : "—"}
          </span>{" "}
          {lessonsLabel}
        </span>
        <span style={{ marginLeft: "auto" }}>{lastTouched}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Progress value={pct} color={accentColor} height={2} />
        <span
          className="mono num"
          style={{
            fontSize: 11,
            color: "var(--ink-2)",
            minWidth: 32,
            textAlign: "right",
          }}
        >
          {pct}%
        </span>
      </div>
    </button>
  );
}

/* ─── ProcessingRails — PRD §5.1 ───────────────────────
   Two parallel cards showing live ingestion and generation tasks.
   Single source of data: GET /api/v1/tasks?status=running. */
function ProcessingRails() {
  const { t } = useT();
  const [tasks, setTasks] = useState<TaskListItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function fetchOnce() {
      try {
        const [running, queued] = await Promise.all([
          listTasks({ status: "running", limit: 20 }),
          listTasks({ status: "queued", limit: 20 }),
        ]);
        if (cancelled) return;
        setTasks([...running.items, ...queued.items]);
      } catch {
        if (!cancelled) setTasks([]);
      }
    }
    void fetchOnce();
    const id = setInterval(fetchOnce, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const byType: Record<TaskTypeUi, TaskListItem[]> = { embed: [], generate: [] };
  for (const tk of tasks) byType[tk.type].push(tk);

  if (tasks.length === 0) return null;

  return (
    <section style={{ marginBottom: "var(--gap-xl)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <SectionTitle>{t("common.processing")}</SectionTitle>
        <Link href="/tasks" className="btn btn-ghost btn-sm">
          {t("newPopover.viewTasks")} →
        </Link>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        <Rail
          type="embed"
          label={t("tasks.typeEmbed")}
          chipClass="chip-accent"
          tasks={byType.embed}
        />
        <Rail
          type="generate"
          label={t("tasks.typeGenerate")}
          chipClass="chip-sage"
          tasks={byType.generate}
        />
      </div>
    </section>
  );
}

function Rail({
  type,
  label,
  chipClass,
  tasks,
}: {
  type: TaskTypeUi;
  label: string;
  chipClass: string;
  tasks: TaskListItem[];
}) {
  const { t } = useT();
  return (
    <div
      className="card"
      style={{
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 110,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className={`chip ${chipClass}`}>{label}</span>
        <span
          className="mono num"
          style={{ fontSize: 12, color: "var(--ink-3)" }}
        >
          {tasks.length}
        </span>
      </div>
      {tasks.length === 0 ? (
        <Link
          href={type === "embed" ? "/import" : "/generate"}
          className="btn btn-ghost btn-sm"
          style={{ marginTop: "auto", color: "var(--ink-3)" }}
        >
          + {type === "embed" ? t("newPopover.addSourceTitle") : t("newPopover.generateTitle")}
        </Link>
      ) : (
        tasks.slice(0, 2).map((tk) => (
          <div key={tk.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: tk.status === "running" ? "var(--accent)" : "var(--ink-4)",
                boxShadow:
                  tk.status === "running"
                    ? "0 0 0 3px var(--accent-soft)"
                    : undefined,
                flexShrink: 0,
              }}
            />
            <div style={{ flex: 1, minWidth: 0, fontSize: 12 }}>
              <div
                className="serif"
                style={{
                  fontSize: 13,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {tk.course_title ?? tk.source_title ?? tk.id.slice(0, 8)}
              </div>
              <span className="mono" style={{ color: "var(--ink-3)" }}>
                {tk.stage ?? tk.status}
              </span>
              {tk.status === "running" ? (
                <div
                  aria-hidden
                  style={{
                    marginTop: 4,
                    height: 3,
                    borderRadius: 999,
                    background: "var(--surface-2)",
                    overflow: "hidden",
                  }}
                >
                  <span
                    style={{
                      display: "block",
                      width: `${stageToPercent(tk.type, tk.stage)}%`,
                      height: "100%",
                      background:
                        tk.type === "embed" ? "var(--accent)" : "var(--sage)",
                      transition: "width 240ms ease",
                    }}
                  />
                </div>
              ) : null}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
