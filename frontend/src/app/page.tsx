"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Brain, Plus, ChevronRight, BookOpen, Loader } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { listCourses, type CourseResponse } from "@/lib/api";
import { useCoursesStore } from "@/lib/stores";

export default function DashboardPage() {
  const router = useRouter();
  const { courses, setCourses, loading, setLoading } = useCoursesStore();

  useEffect(() => {
    setLoading(true);
    listCourses()
      .then((res) => setCourses(res.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [setCourses, setLoading]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-6 py-6">
        {/* Greeting */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-gray-900">LearnMentor</h1>
          <p className="text-sm text-gray-500 mt-1">AI 驱动的个性化学习平台</p>
        </div>

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
