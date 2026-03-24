"use client";

import { Suspense } from "react";
import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, Clock, BookOpen, Target, ArrowRight, CheckCircle, Brain } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { clsx } from "clsx";
import { getCourse, type CourseDetailResponse, type SectionResponse } from "@/lib/api";

function difficultyLabel(difficulty: number): string {
  if (difficulty <= 1) return "入门";
  if (difficulty <= 2) return "进阶";
  return "高级";
}

function difficultyColor(difficulty: number): string {
  if (difficulty <= 1) return "green";
  if (difficulty <= 2) return "orange";
  return "red";
}

/** Extract concept names from the section content object. */
function extractConcepts(content: Record<string, unknown>): string[] {
  if (Array.isArray(content.concepts)) {
    return content.concepts.map((c: unknown) =>
      typeof c === "string" ? c : typeof c === "object" && c !== null && "name" in c ? String((c as Record<string, unknown>).name) : ""
    ).filter(Boolean);
  }
  if (Array.isArray(content.keywords)) {
    return content.keywords.filter((k: unknown) => typeof k === "string") as string[];
  }
  return [];
}

function PathContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const courseId = searchParams.get("courseId");
  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!courseId) {
      setError("未提供课程 ID");
      setLoading(false);
      return;
    }
    getCourse(courseId)
      .then(setCourse)
      .catch((e) => setError(e instanceof Error ? e.message : "加载课程失败"))
      .finally(() => setLoading(false));
  }, [courseId]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500">
        加载中...
      </div>
    );
  }

  if (error || !course) {
    return (
      <div className="min-h-screen flex items-center justify-center text-red-500">
        {error || "课程未找到"}
      </div>
    );
  }

  const sections = [...(course.sections ?? [])].sort(
    (a, b) => (a.order_index ?? 0) - (b.order_index ?? 0)
  );
  const totalConcepts = sections.reduce((sum, s) => sum + extractConcepts(s.content).length, 0);
  const sectionCount = sections.length;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <Link href="/" className="text-xs text-gray-400 hover:text-gray-600 mb-2 flex items-center gap-1 no-underline">
            <ChevronLeft className="w-3 h-3" /> 返回
          </Link>
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-lg font-bold text-gray-900">{course.title}</h1>
              {course.description && (
                <p className="text-sm text-gray-500 mt-0.5">{course.description}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-6 mt-4 text-xs text-gray-500">
            <span className="flex items-center gap-1"><BookOpen className="w-3.5 h-3.5" /> {sectionCount} 个章节</span>
            {totalConcepts > 0 && (
              <span className="flex items-center gap-1"><Target className="w-3.5 h-3.5" /> {totalConcepts} 个核心概念</span>
            )}
          </div>
        </div>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-6">
        {/* Mentor suggestion */}
        <Card className="p-4 mb-6 border-blue-200 bg-blue-50">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <div>
              <p className="text-sm text-blue-900 font-medium">导师建议</p>
              <p className="text-sm text-blue-800 mt-1 leading-relaxed">
                学习路径已生成，共 {sectionCount} 个章节。建议从第一个章节开始，循序渐进地学习。每完成一个章节我会用练习来检验你的理解。
              </p>
            </div>
          </div>
        </Card>

        {/* Path sections */}
        <div className="space-y-3">
          {sections.map((section: SectionResponse, idx: number) => {
            const isFirst = idx === 0;
            const concepts = extractConcepts(section.content);
            const label = difficultyLabel(section.difficulty);
            const color = difficultyColor(section.difficulty);

            return (
              <button
                key={section.id}
                onClick={() =>
                  router.push(`/learn?sectionId=${section.id}&courseId=${courseId}`)
                }
                className="w-full text-left bg-transparent border-none p-0 cursor-pointer"
              >
                <Card
                  hover
                  className={clsx("p-4", isFirst && "border-blue-300 ring-1 ring-blue-100")}
                >
                  <div className="flex items-center gap-4">
                    <div
                      className={clsx(
                        "w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold flex-shrink-0",
                        isFirst ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-400"
                      )}
                    >
                      {idx + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <h3 className="text-sm font-semibold text-gray-900">
                          {section.title}
                        </h3>
                        <Badge color={color}>{label}</Badge>
                      </div>
                      {concepts.length > 0 && (
                        <div className="flex items-center gap-2 flex-wrap mt-1">
                          {concepts.map((c) => (
                            <span
                              key={c}
                              className="px-1.5 py-0.5 rounded text-xs bg-gray-100 text-gray-500"
                            >
                              {c}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      {isFirst && <ArrowRight className="w-4 h-4 text-blue-600" />}
                    </div>
                  </div>
                </Card>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function PathPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center text-gray-500">
          加载中...
        </div>
      }
    >
      <PathContent />
    </Suspense>
  );
}
