"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Brain, Plus, ChevronRight, BookOpen, Loader, AlertCircle, CheckCircle } from "lucide-react";
import {
  listCourses,
  getSetupStatus,
  getSourceProgress,
  getDueReviews,
  completeReview,
  getCourseProgress,
  type CourseResponse,
  type ReviewItemDetail,
  type SourceProgressResponse,
} from "@/lib/api";
import { useCoursesStore, useTasksStore } from "@/lib/stores";
import ReviewCard from "@/components/review-card";

function taskStateLabel(state: string): string {
  const labels: Record<string, string> = {
    PENDING: "排队中...",
    cloning: "复用已有字幕与转写...",
    extracting: "提取字幕...",
    analyzing: "分析内容...",
    generating_lessons: "生成课文...",
    generating_labs: "生成 Lab...",
    storing: "存储数据...",
    embedding: "计算向量...",
    assembling_course: "组装课程...",
    generating_course: "生成课程...",
    SUCCESS: "处理完成",
    FAILURE: "处理失败",
  };
  return labels[state] || state;
}

interface DerivedTaskState {
  state: string;
  courseId?: string;
  nextTaskId?: string;
  error?: string;
}

function deriveStateFromProgress(
  progress: SourceProgressResponse,
  currentTaskId: string
): DerivedTaskState {
  const byType: Record<string, SourceProgressResponse["tasks"][number]> = {};
  for (const t of progress.tasks) byType[t.task_type] = t;
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

export default function DashboardPage() {
  const router = useRouter();
  const { courses, setCourses, loading, setLoading } = useCoursesStore();
  const { tasks, updateTask, removeTask } = useTasksStore();

  const [dueReviews, setDueReviews] = useState<ReviewItemDetail[]>([]);
  const [ratingIds, setRatingIds] = useState<Set<string>>(new Set());
  const [allReviewsDone, setAllReviewsDone] = useState(false);
  const [courseProgressMap, setCourseProgressMap] = useState<Record<string, CourseProgress>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    getSetupStatus()
      .then((status) => {
        if (!status.has_models) {
          router.replace("/setup");
          return;
        }
        setLoading(true);
        listCourses()
          .then((res) => { setCourses(res.items); setLoadError(null); })
          .catch((err) => setLoadError(err instanceof Error ? err.message : "课程加载失败"))
          .finally(() => setLoading(false));
        getDueReviews()
          .then((res) => setDueReviews(res.items))
          .catch(() => {});
      })
      .catch(() => {
        setLoading(true);
        listCourses()
          .then((res) => { setCourses(res.items); setLoadError(null); })
          .catch((err) => setLoadError(err instanceof Error ? err.message : "课程加载失败"))
          .finally(() => setLoading(false));
        getDueReviews()
          .then((res) => setDueReviews(res.items))
          .catch(() => {});
      });
  }, [router, setCourses, setLoading]);

  // Fetch progress for each course once courses are loaded
  useEffect(() => {
    if (courses.length === 0) return;
    courses.forEach((course) => {
      getCourseProgress(course.id)
        .then((items) => {
          const total = items.length;
          const completed = items.filter(
            (item) => item.lesson_read || item.exercise_best_score !== null || item.lab_completed
          ).length;
          setCourseProgressMap((prev) => ({ ...prev, [course.id]: { completed, total } }));
        })
        .catch(() => {});
    });
  }, [courses]);

  const handleRate = useCallback(
    async (reviewId: string, quality: number) => {
      setRatingIds((prev) => new Set(prev).add(reviewId));
      try {
        await completeReview(reviewId, quality);
      } catch {
        // silently ignore
      }
      setDueReviews((prev) => {
        const next = prev.filter((r) => r.id !== reviewId);
        if (next.length === 0) setAllReviewsDone(true);
        return next;
      });
      setRatingIds((prev) => {
        const s = new Set(prev);
        s.delete(reviewId);
        return s;
      });
    },
    []
  );

  // Poll active tasks (DB-authoritative via /sources/{id}/progress)
  useEffect(() => {
    const activeTasks = tasks.filter((t) => t.state !== "SUCCESS" && t.state !== "FAILURE" && !t.courseId);
    if (activeTasks.length === 0) return;

    const interval = setInterval(async () => {
      for (const task of activeTasks) {
        try {
          const progress = await getSourceProgress(task.sourceId).catch(() => null);
          if (!progress) continue;

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
            listCourses().then((res) => setCourses(res.items)).catch(() => {});
            setTimeout(() => removeTask(task.taskId), 8000);
            continue;
          }
        } catch {
          // silently retry on next interval
        }
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [tasks, updateTask, removeTask, setCourses]);

  const showReviewSection = dueReviews.length > 0 || allReviewsDone;

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-14 md:pt-8 pb-10">

        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>Socratiq</h1>
            <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>AI 驱动的个性化学习平台</p>
          </div>
          <Link href="/import">
            <button className="btn-primary flex items-center gap-2 text-sm">
              <Plus className="w-4 h-4" />
              导入新资料
            </button>
          </Link>
        </div>

        {/* Review section */}
        {showReviewSection && (
          <section className="mb-8">
            <div className="flex items-center gap-3 mb-4">
              <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>今日复习</h2>
              {dueReviews.length > 0 && (
                <span className="badge text-white text-xs" style={{ background: "var(--primary)" }}>
                  {dueReviews.length}
                </span>
              )}
            </div>

            {allReviewsDone ? (
              <div
                className="card-flat flex items-center justify-center gap-2 py-8"
                style={{ color: "var(--success)" }}
              >
                <CheckCircle className="w-5 h-5" />
                <span className="font-medium">今日复习完成 ✓</span>
              </div>
            ) : (
              <div
                className="flex gap-4 overflow-x-auto pb-2"
                style={{ scrollbarWidth: "thin" }}
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
        )}

        {/* Active tasks */}
        {tasks.length > 0 && (
          <section className="mb-8">
            <h2 className="text-base font-semibold mb-4" style={{ color: "var(--text)" }}>处理中的任务</h2>
            <div className="space-y-3">
              {tasks.map((task) => (
                <div key={task.taskId} className="card">
                  <div className="flex items-center gap-4">
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                      style={{
                        background: task.state === "FAILURE"
                          ? "var(--error-light)"
                          : task.courseId
                          ? "var(--success-light)"
                          : "var(--primary-light)",
                      }}
                    >
                      {task.state === "FAILURE" ? (
                        <AlertCircle className="w-5 h-5" style={{ color: "var(--error)" }} />
                      ) : task.courseId ? (
                        <CheckCircle className="w-5 h-5" style={{ color: "var(--success)" }} />
                      ) : (
                        <Loader className="w-5 h-5 animate-spin" style={{ color: "var(--primary)" }} />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>{task.title}</h3>
                      <p className="text-xs mt-0.5 whitespace-pre-wrap break-words" style={{ color: "var(--text-secondary)" }}>
                        {task.error || taskStateLabel(task.state)}
                      </p>
                    </div>
                    {task.courseId && (
                      <button
                        onClick={() => { router.push(`/path?courseId=${task.courseId}`); removeTask(task.taskId); }}
                        className="btn-primary text-xs px-3 py-1.5 flex-shrink-0"
                      >
                        进入课程
                      </button>
                    )}
                    {task.state === "FAILURE" && (
                      <button
                        onClick={() => removeTask(task.taskId)}
                        className="btn-ghost text-xs flex-shrink-0"
                      >
                        关闭
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Course grid */}
        <section>
          <h2 className="text-base font-semibold mb-4" style={{ color: "var(--text)" }}>我的课程</h2>

          {loadError ? (
            <div className="card text-center py-10">
              <AlertCircle className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--error)" }} />
              <h3 className="text-base font-semibold mb-2" style={{ color: "var(--text)" }}>加载失败</h3>
              <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>{loadError}</p>
              <button className="btn-primary" onClick={() => { setLoadError(null); setLoading(true); listCourses().then((res) => { setCourses(res.items); setLoadError(null); }).catch((err) => setLoadError(err instanceof Error ? err.message : "课程加载失败")).finally(() => setLoading(false)); }}>
                重试
              </button>
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center py-16" style={{ color: "var(--text-tertiary)" }}>
              <Loader className="w-5 h-5 animate-spin mr-2" />
              <span className="text-sm">加载中...</span>
            </div>
          ) : courses.length === 0 ? (
            <div className="card text-center py-10">
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4"
                style={{ background: "var(--primary-light)" }}
              >
                <Brain className="w-7 h-7" style={{ color: "var(--primary)" }} />
              </div>
              <h3 className="text-base font-semibold mb-2" style={{ color: "var(--text)" }}>还没有课程</h3>
              <p className="text-sm mb-6 max-w-sm mx-auto" style={{ color: "var(--text-secondary)" }}>
                导入一个 B站视频或 PDF 文档，Socratiq 会自动分析内容并为你生成个性化学习路径。
              </p>
              <Link href="/import">
                <button className="btn-primary flex items-center gap-2 mx-auto">
                  <Plus className="w-4 h-4" />
                  导入第一份资料
                </button>
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {courses.map((course: CourseResponse) => {
                const progress = courseProgressMap[course.id];
                const pct = progress && progress.total > 0
                  ? Math.round((progress.completed / progress.total) * 100)
                  : 0;

                return (
                  <button
                    key={course.id}
                    onClick={() => router.push(`/path?courseId=${course.id}`)}
                    className="text-left w-full"
                  >
                    <div className="card h-full">
                      <div className="flex items-start gap-3 mb-4">
                        <div
                          className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                          style={{ background: "var(--primary-light)" }}
                        >
                          <BookOpen className="w-5 h-5" style={{ color: "var(--primary)" }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h3 className="text-sm font-semibold leading-snug" style={{ color: "var(--text)" }}>
                            {course.title}
                          </h3>
                          {course.description && (
                            <p className="text-xs mt-1 line-clamp-2" style={{ color: "var(--text-secondary)" }}>
                              {course.description}
                            </p>
                          )}
                        </div>
                        <ChevronRight className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--text-tertiary)" }} />
                      </div>

                      {/* Progress bar */}
                      <div>
                        <div className="flex justify-between items-center mb-1.5">
                          <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                            {progress ? `${progress.completed} / ${progress.total} 节` : "加载中..."}
                          </span>
                          <span className="text-xs font-medium" style={{ color: "var(--primary)" }}>
                            {progress ? `${pct}%` : ""}
                          </span>
                        </div>
                        <div
                          className="w-full h-1.5 rounded-full overflow-hidden"
                          style={{ background: "var(--surface-alt)" }}
                        >
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{
                              width: `${pct}%`,
                              background: "var(--primary)",
                            }}
                          />
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
