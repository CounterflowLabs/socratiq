"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Brain, Plus, ChevronRight, BookOpen, Loader, RefreshCw, AlertCircle, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { listCourses, getReviewStats, getSetupStatus, getTaskStatus, listActiveSources, type CourseResponse } from "@/lib/api";
import { useCoursesStore, useTasksStore, type PendingTask } from "@/lib/stores";

function formatRemainingTime(seconds: number | undefined): string | null {
  if (!seconds || seconds <= 0) return null;
  if (seconds < 60) return `预计剩余 ${seconds} 秒`;
  const minutes = Math.ceil(seconds / 60);
  return `预计剩余 ${minutes} 分钟`;
}

function taskStateLabel(state: string): string {
  const labels: Record<string, string> = {
    PENDING: "排队中...",
    extracting: "提取字幕...",
    analyzing: "分析内容...",
    generating_lessons: "生成课文...",
    generating_labs: "生成 Lab...",
    storing: "存储数据...",
    embedding: "计算向量...",
    waiting_donor: "复用已有资源中...",
    cloning: "复制内容中...",
    assembling_course: "组装课程...",
    SUCCESS: "处理完成",
    FAILURE: "处理失败",
  };
  return labels[state] || state;
}

export default function DashboardPage() {
  const router = useRouter();
  const { courses, setCourses, loading, setLoading } = useCoursesStore();
  const { tasks, addTask, updateTask, removeTask } = useTasksStore();
  const [reviewStats, setReviewStats] = useState<{ due_today: number; completed_today: number } | null>(null);

  useEffect(() => {
    // Check setup status first; redirect to /setup if no models configured
    getSetupStatus()
      .then((status) => {
        if (!status.has_models) {
          router.replace("/setup");
          return;
        }
        setLoading(true);
        listCourses()
          .then((res) => setCourses(res.items))
          .catch(console.error)
          .finally(() => setLoading(false));
        getReviewStats()
          .then(setReviewStats)
          .catch(() => {}); // silently ignore if review API not available
      })
      .catch(() => {
        // If setup status check fails (e.g. backend not running), load courses anyway
        setLoading(true);
        listCourses()
          .then((res) => setCourses(res.items))
          .catch(console.error)
          .finally(() => setLoading(false));
        getReviewStats()
          .then(setReviewStats)
          .catch(() => {});
      });
  }, [router, setCourses, setLoading]);

  // Restore active tasks from backend on mount (survives page refresh)
  useEffect(() => {
    listActiveSources()
      .then((sources) => {
        const currentTaskIds = new Set(useTasksStore.getState().tasks.map((t) => t.taskId));
        for (const s of sources) {
          if (s.task_id && !currentTaskIds.has(s.task_id)) {
            addTask({
              taskId: s.task_id,
              sourceId: s.id,
              title: s.title || s.url || "处理中...",
              sourceType: s.type,
              state: "PENDING",
            });
          }
        }
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run once on mount only

  // Poll active tasks
  useEffect(() => {
    const activeTasks = tasks.filter((t) => t.state !== "SUCCESS" && t.state !== "FAILURE" && !t.courseId);
    if (activeTasks.length === 0) return;

    const interval = setInterval(async () => {
      for (const task of activeTasks) {
        try {
          const status = await getTaskStatus(task.taskId);
          updateTask(task.taskId, {
            state: status.state,
            error: status.error,
            estimatedRemainingSeconds: status.estimated_remaining_seconds,
          });

          if (status.state === "SUCCESS" && !task.courseId) {
            // Chain completed — result includes course_id from generate_course_task
            const courseId = status.result?.course_id;
            if (courseId) {
              updateTask(task.taskId, { courseId, state: "SUCCESS" });
            } else {
              updateTask(task.taskId, { state: "SUCCESS" });
            }
            listCourses().then((res) => setCourses(res.items)).catch(() => {});
          }
        } catch {
          // Silently retry on next interval
        }
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [tasks, updateTask, setCourses]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-14 md:pt-6 pb-6">
        {/* Greeting */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-gray-900">Socratiq</h1>
          <p className="text-sm text-gray-500 mt-1">AI 驱动的个性化学习平台</p>
        </div>

        {/* Review card */}
        {reviewStats && (reviewStats.due_today > 0 || reviewStats.completed_today > 0) && (
          <Card className="p-4 mb-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center">
                  <RefreshCw className="w-5 h-5 text-violet-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">今日复习</h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    待复习: {reviewStats.due_today} 题 · 已完成: {reviewStats.completed_today} 题
                  </p>
                </div>
              </div>
              {reviewStats.due_today > 0 && (
                <Link href="/learn">
                  <Button size="sm" variant="accent">开始复习</Button>
                </Link>
              )}
            </div>
          </Card>
        )}

        {/* Active tasks */}
        {tasks.length > 0 && (
          <div className="space-y-3 mb-6">
            <h2 className="text-sm font-semibold text-gray-900">处理中的任务</h2>
            {tasks.map((task) => (
              <Card key={task.taskId} className="p-4">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                    style={{ backgroundColor: task.state === "FAILURE" ? "#fef2f2" : task.courseId ? "#f0fdf4" : "#eff6ff" }}>
                    {task.state === "FAILURE" ? (
                      <AlertCircle className="w-5 h-5 text-red-500" />
                    ) : task.courseId ? (
                      <CheckCircle className="w-5 h-5 text-green-500" />
                    ) : (
                      <Loader className="w-5 h-5 text-blue-500 animate-spin" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 truncate">{task.title}</h3>
                    {task.state === "FAILURE" && task.error ? (
                      <div className="mt-1 p-2 rounded-md bg-red-50 border border-red-100">
                        <p className="text-xs text-red-600">{task.error}</p>
                        <p className="text-xs text-gray-400 mt-1">可前往导入历史查看详情或重试</p>
                      </div>
                    ) : (
                      <p className="text-xs text-gray-500 mt-0.5">
                        {taskStateLabel(task.state)}
                        {task.state !== "SUCCESS" && formatRemainingTime(task.estimatedRemainingSeconds) && (
                          <span className="text-gray-400 ml-2">
                            {formatRemainingTime(task.estimatedRemainingSeconds)}
                          </span>
                        )}
                      </p>
                    )}
                  </div>
                  {task.courseId && (
                    <button
                      onClick={() => { router.push(`/path?courseId=${task.courseId}`); removeTask(task.taskId); }}
                      className="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex-shrink-0"
                    >
                      进入课程
                    </button>
                  )}
                  {task.state === "FAILURE" && (
                    <div className="flex gap-2 flex-shrink-0">
                      <button
                        onClick={() => router.push("/sources")}
                        className="px-3 py-1.5 text-xs font-medium text-blue-600 hover:text-blue-700"
                      >
                        导入历史
                      </button>
                      <button
                        onClick={() => removeTask(task.taskId)}
                        className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700"
                      >
                        关闭
                      </button>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}

        {/* Active courses header */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">我的课程</h2>
          <Link href="/import">
            <Button variant="ghost" size="sm"><Plus className="w-3.5 h-3.5" /> 导入新资料</Button>
          </Link>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader className="w-5 h-5 animate-spin mr-2" />
            <span className="text-sm">加载中...</span>
          </div>
        ) : courses.length === 0 ? (
          /* Empty state */
          <Card className="p-10 text-center">
            <div className="w-14 h-14 rounded-2xl bg-blue-50 flex items-center justify-center mx-auto mb-4">
              <Brain className="w-7 h-7 text-blue-600" />
            </div>
            <h3 className="text-base font-semibold text-gray-900 mb-2">还没有课程</h3>
            <p className="text-sm text-gray-500 mb-6 max-w-sm mx-auto">
              导入一个 B站视频或 PDF 文档，Socratiq 会自动分析内容并为你生成个性化学习路径。
            </p>
            <Link href="/import">
              <Button>
                <Plus className="w-4 h-4" /> 导入第一份资料
              </Button>
            </Link>
          </Card>
        ) : (
          /* Course list */
          <div className="space-y-3">
            {courses.map((course: CourseResponse) => (
              <button
                key={course.id}
                onClick={() => router.push(`/path?courseId=${course.id}`)}
                className="w-full text-left bg-transparent border-none p-0 cursor-pointer"
              >
                <Card className="p-4" hover>
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center flex-shrink-0">
                      <BookOpen className="w-5 h-5 text-blue-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-semibold text-gray-900">{course.title}</h3>
                      {course.description && (
                        <p className="text-xs text-gray-500 mt-0.5 truncate">{course.description}</p>
                      )}
                      <p className="text-xs text-gray-400 mt-1">
                        创建于 {new Date(course.created_at).toLocaleDateString("zh-CN")}
                      </p>
                    </div>
                    <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  </div>
                </Card>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
