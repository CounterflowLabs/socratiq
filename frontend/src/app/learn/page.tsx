"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, BookOpen, ChevronLeft, ChevronRight, Languages, Loader2, Play } from "lucide-react";
import { clsx } from "clsx";

import CourseOutline from "@/components/learn/course-outline";
import LearnShell from "@/components/learn/learn-shell";
import StudyAside from "@/components/learn/study-aside";
import LessonRenderer from "@/components/lesson/lesson-renderer";
import TutorDrawer from "@/components/tutor-drawer";
import {
  estimateTranslation,
  getCourse,
  recordProgress,
  translateSection,
  type CourseDetailResponse,
  type SectionResponse,
} from "@/lib/api";

interface LessonSection {
  heading: string;
  content: string;
  timestamp: number;
  code_snippets: { language: string; code: string; context: string }[];
  key_concepts: string[];
  diagrams: { type: string; title: string; content: string }[];
  interactive_steps: {
    title: string;
    steps: { label: string; detail: string; code?: string | null }[];
  } | null;
}

interface LessonContent {
  title: string;
  summary: string;
  sections: LessonSection[];
}

function getVideoEmbed(section: SectionResponse, course: CourseDetailResponse) {
  const source = course.sources.find((item) => item.id === section.source_id) ?? course.sources[0];
  if (!source?.url) return null;

  const bvMatch = source.url.match(/BV[\w]+/);
  if (bvMatch && source.type === "bilibili") {
    const bvid = bvMatch[0];
    const page = (section.order_index ?? 0) + 1;
    return {
      type: "bilibili" as const,
      src: `//player.bilibili.com/player.html?bvid=${bvid}&p=${page}&high_quality=1`,
    };
  }

  const ytMatch = source.url.match(/(?:v=|\/embed\/|youtu\.be\/)([^&?#]+)/);
  if (ytMatch) {
    return {
      type: "youtube" as const,
      src: `https://www.youtube.com/embed/${ytMatch[1]}`,
    };
  }

  return null;
}

function LearnPageInner() {
  const searchParams = useSearchParams();
  const sectionId = searchParams.get("sectionId");
  const courseId = searchParams.get("courseId");
  const router = useRouter();

  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [section, setSection] = useState<SectionResponse | null>(null);
  const [tutorOpen, setTutorOpen] = useState(false);
  const [asideOpen, setAsideOpen] = useState(false);

  const [showTranslation, setShowTranslation] = useState(false);
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationEstimate, setTranslationEstimate] = useState<{
    chunks_total: number;
    chunks_cached: number;
    chunks_to_translate: number;
    estimated_tokens: number;
    estimated_cost_usd: number;
  } | null>(null);
  const [translations, setTranslations] = useState<
    { chunk_id: string; translated_text: string | null }[]
  >([]);
  const [translationError, setTranslationError] = useState<string | null>(null);

  const progressRecorded = useRef(false);
  const lessonScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!courseId) return;

    getCourse(courseId)
      .then((data) => {
        setCourse(data);

        if (sectionId) {
          const matchedSection = data.sections.find((item) => item.id === sectionId);
          if (matchedSection) {
            setSection(matchedSection);
            return;
          }
        }

        setSection(data.sections[0] ?? null);
      })
      .catch(console.error);
  }, [courseId, sectionId]);

  useEffect(() => {
    setShowTranslation(false);
    setTranslations([]);
    setTranslationEstimate(null);
    setTranslationError(null);
    progressRecorded.current = false;
  }, [section?.id]);

  useEffect(() => {
    if (!section?.id) return;

    const timer = setTimeout(() => {
      if (!progressRecorded.current) {
        progressRecorded.current = true;
        recordProgress(section.id, "lesson_read").catch(() => {});
      }
    }, 30_000);

    return () => clearTimeout(timer);
  }, [section?.id]);

  const handleLessonScroll = useCallback(() => {
    if (!lessonScrollRef.current || !section?.id || progressRecorded.current) return;

    const element = lessonScrollRef.current;
    if (element.scrollTop + element.clientHeight >= element.scrollHeight - 50) {
      progressRecorded.current = true;
      recordProgress(section.id, "lesson_read").catch(() => {});
    }
  }, [section?.id]);

  async function handleTranslationToggle() {
    if (showTranslation) {
      setShowTranslation(false);
      return;
    }

    if (!section) return;

    if (translations.length > 0) {
      setShowTranslation(true);
      return;
    }

    setTranslationLoading(true);
    setTranslationError(null);

    try {
      const estimate = await estimateTranslation(section.id);
      setTranslationEstimate(estimate);

      if (estimate.chunks_to_translate === 0 || estimate.estimated_cost_usd < 0.01) {
        const result = await translateSection(section.id);
        setTranslations(result.translations);
        setShowTranslation(true);
        setTranslationEstimate(null);
      }
    } catch (error) {
      setTranslationError(error instanceof Error ? error.message : "翻译失败");
    } finally {
      setTranslationLoading(false);
    }
  }

  async function confirmTranslation() {
    if (!section) return;

    setTranslationLoading(true);
    setTranslationError(null);

    try {
      const result = await translateSection(section.id);
      setTranslations(result.translations);
      setShowTranslation(true);
      setTranslationEstimate(null);
    } catch (error) {
      setTranslationError(error instanceof Error ? error.message : "翻译失败");
    } finally {
      setTranslationLoading(false);
    }
  }

  const sections = course?.sections ?? [];
  const currentIdx = sections.findIndex((item) => item.id === section?.id);
  const prevSection = currentIdx > 0 ? sections[currentIdx - 1] : null;
  const nextSection = currentIdx >= 0 && currentIdx < sections.length - 1 ? sections[currentIdx + 1] : null;

  function navigateToSection(nextSectionItem: SectionResponse) {
    setSection(nextSectionItem);
    router.replace(`/learn?courseId=${courseId}&sectionId=${nextSectionItem.id}`);
  }

  const lessonData = (section?.content?.lesson as LessonContent | undefined) ?? undefined;
  const hasLesson = !!(lessonData && lessonData.title && lessonData.sections);
  const videoEmbed = section && course ? getVideoEmbed(section, course) : null;
  const completedCount = currentIdx >= 0 ? currentIdx + 1 : 0;
  const totalCount = sections.length;
  const progressLabel = totalCount > 0 ? `进度 ${completedCount}/${totalCount}` : "准备中";
  const rawSectionContent = section?.content as unknown;

  const lessonStage = (
    <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href={courseId ? `/path?courseId=${courseId}` : "/path"}
            className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
          >
            <ArrowLeft className="h-4 w-4" />
            返回路径
          </Link>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">
              当前章节
            </p>
            <h2 className="truncate text-xl font-semibold text-slate-900">
              {section?.title ?? "加载章节中..."}
            </h2>
          </div>
          <button
            type="button"
            onClick={handleTranslationToggle}
            disabled={translationLoading || !section}
            className={clsx(
              "inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition",
              showTranslation
                ? "bg-blue-50 text-blue-700"
                : "border border-slate-200 text-slate-600 hover:bg-slate-50"
            )}
          >
            {translationLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Languages className="h-4 w-4" />
            )}
            翻译
          </button>
        </div>
      </div>

      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <div className="overflow-hidden rounded-3xl bg-slate-950">
          <div className="relative w-full pb-[56.25%]">
            {videoEmbed ? (
              <iframe
                src={videoEmbed.src}
                className="absolute inset-0 h-full w-full"
                allowFullScreen
                sandbox="allow-scripts allow-same-origin allow-popups"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center text-white">
                  <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-white/15">
                    <Play className="ml-1 h-8 w-8" />
                  </div>
                  <p className="text-sm text-white/70">{course?.title ?? "暂无视频"}</p>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="min-w-0 overflow-hidden rounded-3xl border border-slate-200 bg-slate-50">
          {translationEstimate && !showTranslation ? (
            <div className="border-b border-blue-100 bg-blue-50 px-4 py-3">
              <p className="text-sm text-blue-700">
                需要翻译 {translationEstimate.chunks_to_translate} 个片段，预计{" "}
                {translationEstimate.estimated_tokens.toLocaleString()} tokens（$
                {translationEstimate.estimated_cost_usd.toFixed(4)}）
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={confirmTranslation}
                  disabled={translationLoading}
                  className="rounded-full bg-blue-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-60"
                >
                  确认翻译
                </button>
                <button
                  type="button"
                  onClick={() => setTranslationEstimate(null)}
                  className="rounded-full border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-white"
                >
                  取消
                </button>
              </div>
            </div>
          ) : null}

          {showTranslation && translations.length > 0 ? (
            <div className="border-b border-amber-100 bg-amber-50/80 px-4 py-3">
              <h3 className="text-sm font-semibold text-amber-700">中文翻译</h3>
              <div className="mt-2 space-y-2">
                {translations.map((translation) => (
                  <p
                    key={translation.chunk_id}
                    className="text-sm leading-6 text-slate-700"
                  >
                    {translation.translated_text ?? "（翻译不可用）"}
                  </p>
                ))}
              </div>
            </div>
          ) : null}

          {translationError ? (
            <div className="border-b border-red-100 bg-red-50 px-4 py-2 text-sm text-red-600">
              {translationError}
            </div>
          ) : null}

          <div
            ref={lessonScrollRef}
            onScroll={handleLessonScroll}
            className="max-h-[70vh] overflow-y-auto px-4 py-4"
          >
            {hasLesson ? (
              <LessonRenderer lesson={lessonData} onTimestampClick={() => {}} />
            ) : rawSectionContent ? (
              <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
                {typeof rawSectionContent === "string"
                  ? rawSectionContent
                  : JSON.stringify(rawSectionContent, null, 2)}
              </div>
            ) : (
              <div className="flex min-h-72 items-center justify-center">
                <div className="text-center">
                  <BookOpen className="mx-auto h-8 w-8 text-slate-300" />
                  <p className="mt-2 text-sm text-slate-400">此章节暂无课文内容</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-slate-200 px-5 py-4">
        <button
          type="button"
          onClick={() => prevSection && navigateToSection(prevSection)}
          disabled={!prevSection}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronLeft className="h-4 w-4" />
          上一节
        </button>
        <span className="truncate px-4 text-sm text-slate-500">{section?.title ?? ""}</span>
        <button
          type="button"
          onClick={() => nextSection && navigateToSection(nextSection)}
          disabled={!nextSection}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          下一节
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </section>
  );

  return (
    <>
      <LearnShell
        courseTitle={course?.title ?? "加载中..."}
        progressLabel={progressLabel}
        asideOpen={asideOpen}
        onOpenAside={() => setAsideOpen(true)}
        outline={
          <CourseOutline
            sections={sections}
            currentSectionId={section?.id ?? null}
            onSelectSection={navigateToSection}
          />
        }
        lessonStage={lessonStage}
        aside={
          <StudyAside
            courseTitle={course?.title ?? "课程加载中"}
            currentSectionTitle={section?.title ?? "等待章节"}
            progressLabel={progressLabel}
            onOpenTutor={() => setTutorOpen(true)}
            onClose={() => setAsideOpen(false)}
          />
        }
      />

      <TutorDrawer
        open={tutorOpen}
        onClose={() => setTutorOpen(false)}
        courseId={courseId}
        sectionId={section?.id ?? null}
      />
    </>
  );
}

export default function LearnPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-slate-50">
          <div className="text-sm text-slate-500">加载中...</div>
        </div>
      }
    >
      <LearnPageInner />
    </Suspense>
  );
}
