"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { BookOpen, ChevronLeft, ChevronRight, Languages, Loader2 } from "lucide-react";
import { clsx } from "clsx";

import CourseOutline, { type LessonWaypoint } from "@/components/learn/course-outline";
import LearnShell from "@/components/learn/learn-shell";
import StudyAside, { type AsidePanelId } from "@/components/learn/study-aside";
import LessonRenderer from "@/components/lesson/lesson-renderer";
import TutorDrawer from "@/components/tutor-drawer";
import {
  clearCourseRegeneration,
  estimateTranslation,
  getCourse,
  getRegenerationStatus,
  recordProgress,
  translateSection,
  type CourseDetailResponse,
  type GraphCard,
  type LabMode,
  type LessonContent,
  type RegenerationStatus,
  type SectionResponse,
  type SourceSummary,
} from "@/lib/api";

function getOrderedSources(course: CourseDetailResponse) {
  const sourceFirstSectionOrder = new Map<string, number>();

  [...course.sections]
    .sort((left, right) => {
      const leftIndex = left.order_index ?? Number.MAX_SAFE_INTEGER;
      const rightIndex = right.order_index ?? Number.MAX_SAFE_INTEGER;
      return leftIndex - rightIndex;
    })
    .forEach((section, index) => {
      if (!section.source_id || sourceFirstSectionOrder.has(section.source_id)) return;
      sourceFirstSectionOrder.set(section.source_id, index);
    });

  return [...course.sources].sort((left, right) => {
    const leftRank = sourceFirstSectionOrder.get(left.id) ?? Number.MAX_SAFE_INTEGER;
    const rightRank = sourceFirstSectionOrder.get(right.id) ?? Number.MAX_SAFE_INTEGER;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return left.id.localeCompare(right.id);
  });
}

function getCurrentSource(section: SectionResponse, course: CourseDetailResponse) {
  const orderedSources = getOrderedSources(course);
  return orderedSources.find((item) => item.id === section.source_id) ?? orderedSources[0] ?? null;
}

function getVideoSource(section: SectionResponse, course: CourseDetailResponse) {
  const currentSource = getCurrentSource(section, course);
  const orderedSources = getOrderedSources(course);
  return (
    (currentSource && isVideoSource(currentSource) ? currentSource : null) ??
    orderedSources.find((item) => isVideoSource(item)) ??
    null
  );
}

function getSourceSections(course: CourseDetailResponse, sourceId: string) {
  return [...course.sections]
    .filter((item) => item.source_id === sourceId)
    .sort((left, right) => {
      const leftIndex = left.order_index ?? Number.MAX_SAFE_INTEGER;
      const rightIndex = right.order_index ?? Number.MAX_SAFE_INTEGER;
      return leftIndex - rightIndex;
    });
}

function readPageIndex(content: unknown): number | null {
  if (!isRecord(content)) return null;

  if (typeof content.page_index === "number" && Number.isInteger(content.page_index) && content.page_index >= 0) {
    return content.page_index;
  }

  if (
    isRecord(content.graph_card) &&
    typeof content.graph_card.section_anchor === "number" &&
    Number.isInteger(content.graph_card.section_anchor) &&
    content.graph_card.section_anchor >= 0
  ) {
    return content.graph_card.section_anchor;
  }

  return null;
}

function getBilibiliPage(
  section: SectionResponse,
  course: CourseDetailResponse,
  source: SourceSummary
) {
  if (section.source_id !== source.id) return 1;

  const sourceSections = getSourceSections(course, source.id);
  const pageIndices = sourceSections
    .map((item) => readPageIndex(item.content))
    .filter((value): value is number => value !== null);
  const explicitPageIndex = readPageIndex(section.content);

  if (explicitPageIndex === null || new Set(pageIndices).size <= 1) return 1;
  return explicitPageIndex + 1;
}

function getVideoEmbed(
  section: SectionResponse,
  course: CourseDetailResponse,
  source: SourceSummary | null
) {
  if (!source?.url) return null;

  const bvMatch = source.url.match(/BV[\w]+/);
  if (bvMatch && source.type === "bilibili") {
    const bvid = bvMatch[0];
    const page = getBilibiliPage(section, course, source);
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

function isPdfSource(source: SourceSummary): boolean {
  return source.type === "pdf" || source.url?.toLowerCase().endsWith(".pdf") === true;
}

function isVideoSource(source: SourceSummary): boolean {
  if (source.type === "youtube" || source.type === "bilibili") return true;
  return /(?:youtube\.com|youtu\.be|bilibili\.com)/i.test(source.url ?? "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readLabMode(content: unknown): LabMode | null {
  if (!isRecord(content)) return null;
  const value = content.lab_mode;
  return value === "inline" || value === "none" ? value : null;
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function readGraphCard(content: unknown): GraphCard | null {
  if (!isRecord(content) || !isRecord(content.graph_card)) return null;

  return {
    current: readStringArray(content.graph_card.current),
    prerequisites: readStringArray(content.graph_card.prerequisites),
    unlocks: readStringArray(content.graph_card.unlocks),
    section_anchor:
      typeof content.graph_card.section_anchor === "string" || typeof content.graph_card.section_anchor === "number"
        ? content.graph_card.section_anchor
        : null,
  };
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
  const [outlineOpen, setOutlineOpenState] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    const stored = window.localStorage.getItem("learn:outlineOpen");
    return stored === null ? true : stored === "1";
  });
  const setOutlineOpen = useCallback((next: boolean) => {
    setOutlineOpenState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("learn:outlineOpen", next ? "1" : "0");
    }
  }, []);
  const [regenTaskId, setRegenTaskId] = useState<string | null>(null);
  const [regenStatus, setRegenStatus] = useState<RegenerationStatus | null>(null);
  const [activeAsidePanel, setActiveAsidePanel] = useState<AsidePanelId>("tutor");
  const [courseError, setCourseError] = useState<string | null>(null);
  const asidePanelPreference = useRef<AsidePanelId | null>(null);

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

  useEffect(() => {
    if (!courseId) return;

    getCourse(courseId)
      .then((data) => {
        setCourse(data);
        setCourseError(null);

        if (sectionId) {
          const matchedSection = data.sections.find((item) => item.id === sectionId);
          if (matchedSection) {
            setSection(matchedSection);
            return;
          }
        }

        setSection(data.sections[0] ?? null);
      })
      .catch((err) => setCourseError(err instanceof Error ? err.message : "课程加载失败"));
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
  const lessonLabMode = readLabMode(section?.content);
  const lessonGraphCard = readGraphCard(section?.content);
  const hasLesson = !!(lessonData && lessonData.title && lessonData.sections);
  const lessonWaypoints = useMemo<LessonWaypoint[]>(
    () =>
      lessonData?.sections.map((item, index) => ({
        id: `lesson-waypoint-${index}`,
        title: item.heading,
        timestamp: item.timestamp > 0 ? item.timestamp : null,
        concepts: item.key_concepts,
      })) ?? [],
    [lessonData]
  );
  const completedCount = currentIdx >= 0 ? currentIdx + 1 : 0;
  const totalCount = sections.length;
  const progressLabel = totalCount > 0 ? `进度 ${completedCount}/${totalCount}` : "准备中";
  const rawSectionContent = section?.content as unknown;
  const orderedSources = useMemo(() => (course ? getOrderedSources(course) : []), [course]);
  const currentSource = section && course ? getCurrentSource(section, course) : null;
  const videoSource = section && course ? getVideoSource(section, course) : null;
  const videoEmbed = section && course ? getVideoEmbed(section, course, videoSource) : null;
  const pdfSource =
    (currentSource && isPdfSource(currentSource) ? currentSource : null) ??
    orderedSources.find((item) => isPdfSource(item)) ??
    null;
  const referenceSources = useMemo(
    () =>
      orderedSources.filter(
        (item) => item.id !== videoSource?.id && item.id !== pdfSource?.id
      ),
    [orderedSources, pdfSource?.id, videoSource?.id]
  );
  const availableAsidePanels = useMemo(() => {
    const panels: AsidePanelId[] = [];

    if (videoEmbed) panels.push("video");
    if (pdfSource) panels.push("pdf");
    if (referenceSources.length > 0) panels.push("references");
    panels.push("tutor");

    return panels;
  }, [pdfSource, referenceSources, videoEmbed]);
  const defaultAsidePanel = availableAsidePanels[0] ?? "tutor";
  const handleTimestampClick = useCallback(() => {
    if (!videoEmbed) return;
    setAsideOpen(true);
    setActiveAsidePanel("video");
  }, [videoEmbed]);
  const handleSelectWaypoint = useCallback((waypointId: string) => {
    const target = lessonScrollRef.current?.querySelector(
      `[data-lesson-waypoint="${waypointId}"]`
    );
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  useEffect(() => {
    // Preserve user's panel preference across section changes
    const preferred = asidePanelPreference.current;
    if (preferred && availableAsidePanels.includes(preferred)) {
      setActiveAsidePanel(preferred);
    } else {
      setActiveAsidePanel(defaultAsidePanel);
    }
  }, [defaultAsidePanel, section?.id, availableAsidePanels]);

  useEffect(() => {
    if (availableAsidePanels.includes(activeAsidePanel)) return;
    setActiveAsidePanel(defaultAsidePanel);
  }, [activeAsidePanel, availableAsidePanels, defaultAsidePanel]);

  const lessonStage = (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_16px_48px_rgba(15,23,42,0.08)]">
      <div className="border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase text-slate-400">
              当前章节
            </p>
            <h2 className="truncate text-xl font-semibold text-slate-900">
              {section?.title ?? "加载章节中..."}
            </h2>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="rounded-md border border-teal-200 bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-800">
                {lessonWaypoints.length} 个知识片段
              </span>
              <span className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800">
                {videoEmbed ? "视频素材" : "无视频"}
              </span>
              <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600">
                {availableAsidePanels.length} 个辅助面板
              </span>
            </div>
          </div>
          {/* TODO: 翻译功能暂时隐藏，后续修复后恢复 */}
        </div>
      </div>

      <div className="bg-slate-50">
        {/* TODO: 翻译相关 UI 暂时隐藏 */}

        <div
          ref={lessonScrollRef}
          onScroll={handleLessonScroll}
          className="max-h-[75vh] overflow-y-auto"
        >
          {hasLesson ? (
            <LessonRenderer
              lesson={lessonData}
              onTimestampClick={videoEmbed ? handleTimestampClick : undefined}
              sectionId={section?.id ?? null}
              labMode={lessonLabMode}
              graphCard={lessonGraphCard}
            />
          ) : rawSectionContent ? (
            <div className="px-5 py-5 whitespace-pre-wrap text-sm leading-7 text-slate-700">
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

      <div className="flex items-center justify-between border-t border-slate-200 px-5 py-4">
        <button
          type="button"
          onClick={() => prevSection && navigateToSection(prevSection)}
          disabled={!prevSection}
          className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronLeft className="h-4 w-4" />
          上一节
        </button>
        <span className="truncate px-4 text-sm text-slate-500">{section?.title ?? ""}</span>
        <button
          type="button"
          onClick={() => nextSection && navigateToSection(nextSection)}
          disabled={!nextSection}
          className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          下一节
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </section>
  );

  if (courseError) {
    return (
      <div className="flex min-h-screen items-center justify-center" style={{ background: "var(--bg)" }}>
        <div className="card max-w-md w-full text-center p-8">
          <BookOpen className="mx-auto h-10 w-10 mb-3" style={{ color: "var(--error)" }} />
          <h2 className="text-lg font-bold mb-2" style={{ color: "var(--text)" }}>课程加载失败</h2>
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>{courseError}</p>
          <button
            className="btn-primary"
            onClick={() => { setCourseError(null); if (courseId) getCourse(courseId).then((data) => { setCourse(data); setCourseError(null); setSection(data.sections[0] ?? null); }).catch((err) => setCourseError(err instanceof Error ? err.message : "课程加载失败")); }}
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <LearnShell
        courseTitle={course?.title ?? "加载中..."}
        progressLabel={progressLabel}
        asideOpen={asideOpen}
        onOpenAside={() => setAsideOpen(true)}
        onCloseAside={() => setAsideOpen(false)}
        backHref={courseId ? `/path?courseId=${courseId}` : "/path"}
        versionIndex={course?.version_index ?? 1}
        parentCourseHref={
          course?.parent_id ? `/path?courseId=${course.parent_id}` : null
        }
        regenerationBanner={
          regenStatus
            ? {
                state:
                  regenStatus.status === "success"
                    ? "ready"
                    : regenStatus.status === "failure"
                    ? "failed"
                    : "running",
                stage: regenStatus.stage ?? null,
                current: regenStatus.current ?? null,
                total: regenStatus.total ?? null,
                newCourseId: regenStatus.course_id,
                message: regenStatus.error,
                onOpenNewCourse: regenStatus.course_id
                  ? () => {
                      const newCourseId = regenStatus.course_id;
                      if (courseId) {
                        void clearCourseRegeneration(courseId).catch(() => {});
                      }
                      setRegenStatus(null);
                      setRegenTaskId(null);
                      setCourse((prev) =>
                        prev ? { ...prev, active_regeneration_task_id: null } : prev
                      );
                      router.push(`/learn?courseId=${newCourseId}`);
                    }
                  : undefined,
                onDismiss: () => {
                  if (courseId) {
                    void clearCourseRegeneration(courseId).catch(() => {});
                  }
                  setRegenStatus(null);
                  setRegenTaskId(null);
                  setCourse((prev) =>
                    prev ? { ...prev, active_regeneration_task_id: null } : prev
                  );
                },
              }
            : null
        }
        outlineOpen={outlineOpen}
        onOpenOutline={() => setOutlineOpen(true)}
        outline={
          <CourseOutline
            sections={sections}
            currentSectionId={section?.id ?? null}
            onSelectSection={navigateToSection}
            lessonWaypoints={lessonWaypoints}
            onSelectWaypoint={handleSelectWaypoint}
            onCollapse={() => setOutlineOpen(false)}
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
            videoEmbed={videoEmbed}
            pdfSource={pdfSource}
            referenceSources={referenceSources}
            activePanel={activeAsidePanel}
            onPanelChange={(panel) => { asidePanelPreference.current = panel; setActiveAsidePanel(panel); }}
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
