"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Brain, Plus, ChevronRight, BookOpen, Loader, RefreshCw, AlertCircle, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { listCourses, getReviewStats, getSetupStatus, getTaskStatus, generateCourse, type CourseResponse } from "@/lib/api";
import { useCoursesStore, useTasksStore, type PendingTask } from "@/lib/stores";

function taskStateLabel(state: string): string {
  const labels: Record<string, string> = {
    PENDING: "排队中...",
    extracting: "提取字幕...",
    analyzing: "分析内容...",
    generating_lessons: "生成课文...",
    generating_labs: "生成 Lab...",
    storing: "存储数据...",
    embedding: "计算向量...",
    SUCCESS: "处理完成",
    FAILURE: "处理失败",
  };
  return labels[state] || state;
}

export default function DashboardPage() {
  const router = useRouter();
  const { courses, setCourses, loading, setLoading } = useCoursesStore();
  const { tasks, updateTask, removeTask } = useTasksStore();
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

  // Poll active tasks
  useEffect(() => {
    const activeTasks = tasks.filter((t) => t.state !== "SUCCESS" && t.state !== "FAILURE" && !t.courseId);
    if (activeTasks.length === 0) return;

    const interval = setInterval(async () => {
      for (const task of activeTasks) {
        try {
          const status = await getTaskStatus(task.taskId);
          updateTask(task.taskId, { state: status.state, error: status.error });

          if (status.state === "SUCCESS" && !task.courseId) {
            // Auto-generate course
            try {
              const course = await generateCourse([task.sourceId]);
              updateTask(task.taskId, { courseId: course.id, state: "SUCCESS" });
              // Refresh course list
              listCourses().then((res) => setCourses(res.items)).catch(() => {});
            } catch {
              updateTask(task.taskId, { state: "FAILURE", error: "课程生成失败" });
            }
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
          <h1 className="text-xl font-bold text-gray-900">LearnMentor</h1>
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
                    <p className="text-xs text-gray-500 mt-0.5">
                      {task.error || taskStateLabel(task.state)}
                    </p>
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
                    <button
                      onClick={() => removeTask(task.taskId)}
                      className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 flex-shrink-0"
                    >
                      关闭
                    </button>
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
              导入一个 B站视频或 PDF 文档，LearnMentor 会自动分析内容并为你生成个性化学习路径。
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
