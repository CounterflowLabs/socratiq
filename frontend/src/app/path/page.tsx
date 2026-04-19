"use client";

import { Suspense } from "react";
import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, BookOpen, FlaskConical, BarChart3 } from "lucide-react";
import { getCourse, getCourseProgress, type CourseDetailResponse, type SectionResponse } from "@/lib/api";

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
          className={`inline-block w-2 h-2 rounded-full ${
            i < filled ? "bg-gray-600" : "bg-gray-200"
          }`}
        />
      ))}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "completed") {
    return (
      <span className="badge" style={{ background: "#d1fae5", color: "#065f46", fontSize: 12 }}>
        ✅ 已完成
      </span>
    );
  }
  if (status === "in_progress") {
    return (
      <span className="badge" style={{ background: "#dbeafe", color: "#1e40af", fontSize: 12 }}>
        🔵 进行中
      </span>
    );
  }
  return (
    <span className="badge" style={{ background: "#f3f4f6", color: "#9ca3af", fontSize: 12 }}>
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
              <span className="font-medium" style={{ color: "#10b981" }}>
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
                <span className="font-medium" style={{ color: "#10b981" }}>
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
              <span className="font-medium" style={{ color: "#10b981" }}>
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

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <header
        className="px-6 py-4 border-b"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="max-w-2xl mx-auto">
          <Link
            href="/"
            className="flex items-center gap-1 text-xs mb-3 no-underline"
            style={{ color: "var(--text-secondary)" }}
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            返回
          </Link>
          <h1 className="text-lg font-bold" style={{ color: "var(--text)" }}>
            {course.title}
          </h1>
          {course.description && (
            <p className="text-sm mt-1 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {course.description}
            </p>
          )}
        </div>
      </header>

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
