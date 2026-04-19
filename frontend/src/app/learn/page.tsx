"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  MessageCircle,
  BookOpen,
  FlaskConical,
  Network,
  ChevronUp,
  ChevronDown,
  Languages,
  Loader2,
  Play,
} from "lucide-react";
import { clsx } from "clsx";
import {
  getCourse,
  getSectionLab,
  estimateTranslation,
  translateSection,
  recordProgress,
  getKnowledgeGraph,
  type CourseDetailResponse,
  type SectionResponse,
  type LabResponse,
  type KnowledgeGraphNode,
  type KnowledgeGraphEdge,
} from "@/lib/api";
import { useChatStore } from "@/lib/stores";
import LessonRenderer from "@/components/lesson/lesson-renderer";
import TutorDrawer from "@/components/tutor-drawer";
import LabEditor from "@/components/lab/lab-editor";

const ForceGraph = dynamic(
  () => import("@/components/knowledge-graph/force-graph"),
  { ssr: false }
);

// ─── Types ──────────────────────────────────────────

interface LessonSection {
  heading: string;
  content: string;
  timestamp: number;
  code_snippets: { language: string; code: string; context: string }[];
  key_concepts: string[];
  diagrams: { type: string; title: string; content: string }[];
  interactive_steps: { title: string; steps: { label: string; detail: string; code?: string | null }[] } | null;
}

interface LessonContent {
  title: string;
  summary: string;
  sections: LessonSection[];
}

type TabId = "learn" | "lab" | "graph";

const TAB_ITEMS: { id: TabId; label: string; icon: typeof BookOpen }[] = [
  { id: "learn", label: "学习", icon: BookOpen },
  { id: "lab", label: "Lab", icon: FlaskConical },
  { id: "graph", label: "图谱", icon: Network },
];

// ─── Video embed helper ─────────────────────────────

function getVideoEmbed(section: SectionResponse, course: CourseDetailResponse) {
  const source = course.sources.find((s) => s.id === section.source_id) ?? course.sources[0];
  if (!source?.url) return null;

  // Bilibili
  const bvMatch = source.url.match(/BV[\w]+/);
  if (bvMatch && source.type === "bilibili") {
    const bvid = bvMatch[0];
    const page = (section.order_index ?? 0) + 1;
    return { type: "bilibili" as const, src: `//player.bilibili.com/player.html?bvid=${bvid}&p=${page}&high_quality=1` };
  }

  // YouTube
  const ytMatch = source.url.match(/(?:v=|\/embed\/|youtu\.be\/)([^&?#]+)/);
  if (ytMatch) {
    return { type: "youtube" as const, src: `https://www.youtube.com/embed/${ytMatch[1]}` };
  }

  return null;
}

// ─── Inner page component ───────────────────────────

function LearnPageInner() {
  const searchParams = useSearchParams();
  const sectionId = searchParams.get("sectionId");
  const courseId = searchParams.get("courseId");
  const router = useRouter();

  // Data state
  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [section, setSection] = useState<SectionResponse | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState<TabId>("learn");
  const [lessonCollapsed, setLessonCollapsed] = useState(false);
  const [tutorOpen, setTutorOpen] = useState(false);

  // Lab state
  const [lab, setLab] = useState<LabResponse | null>(null);
  const [labLoading, setLabLoading] = useState(false);

  // Graph state
  const [graphData, setGraphData] = useState<{ nodes: KnowledgeGraphNode[]; edges: KnowledgeGraphEdge[] } | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);

  // Translation state
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

  // Progress tracking
  const progressRecorded = useRef(false);
  const lessonScrollRef = useRef<HTMLDivElement>(null);

  // Chat store (reserved for future use)
  useChatStore();

  // ─── Load course & section ──────────────────────────

  useEffect(() => {
    if (!courseId) return;
    getCourse(courseId)
      .then((c) => {
        setCourse(c);
        if (sectionId) {
          const found = c.sections.find((s) => s.id === sectionId);
          if (found) setSection(found);
        } else if (c.sections.length > 0) {
          setSection(c.sections[0]);
        }
      })
      .catch(console.error);
  }, [courseId, sectionId]);

  // Reset state when section changes
  useEffect(() => {
    setShowTranslation(false);
    setTranslations([]);
    setTranslationEstimate(null);
    setTranslationError(null);
    setLab(null);
    setGraphData(null);
    progressRecorded.current = false;
  }, [section?.id]);

  // ─── Lazy-load lab ────────────────────────────────

  useEffect(() => {
    if (activeTab === "lab" && section?.id && !lab && !labLoading) {
      setLabLoading(true);
      getSectionLab(section.id)
        .then((data) => setLab(data))
        .catch(() => setLab(null))
        .finally(() => setLabLoading(false));
    }
  }, [activeTab, section?.id, lab, labLoading]);

  // ─── Lazy-load graph ──────────────────────────────

  useEffect(() => {
    if (activeTab === "graph" && courseId && !graphData && !graphLoading) {
      setGraphLoading(true);
      getKnowledgeGraph(courseId)
        .then((data) => setGraphData(data))
        .catch(() => setGraphData(null))
        .finally(() => setGraphLoading(false));
    }
  }, [activeTab, courseId, graphData, graphLoading]);

  // ─── Progress recording (30s timer) ───────────────

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

  // Scroll-to-bottom progress trigger
  const handleLessonScroll = useCallback(() => {
    if (!lessonScrollRef.current || !section?.id || progressRecorded.current) return;
    const el = lessonScrollRef.current;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 50) {
      progressRecorded.current = true;
      recordProgress(section.id, "lesson_read").catch(() => {});
    }
  }, [section?.id]);

  // ─── Translation ──────────────────────────────────

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
    } catch (e) {
      setTranslationError(e instanceof Error ? e.message : "翻译失败");
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
    } catch (e) {
      setTranslationError(e instanceof Error ? e.message : "翻译失败");
    } finally {
      setTranslationLoading(false);
    }
  }

  // ─── Section navigation ───────────────────────────

  const sections = course?.sections ?? [];
  const currentIdx = sections.findIndex((s) => s.id === section?.id);
  const prevSection = currentIdx > 0 ? sections[currentIdx - 1] : null;
  const nextSection = currentIdx < sections.length - 1 ? sections[currentIdx + 1] : null;

  function navigateToSection(sec: SectionResponse) {
    setSection(sec);
    router.replace(`/learn?courseId=${courseId}&sectionId=${sec.id}`);
  }

  // ─── Video embed ──────────────────────────────────

  const videoEmbed = section && course ? getVideoEmbed(section, course) : null;

  // ─── Lesson content parsing ───────────────────────

  const lessonData = section?.content?.lesson as LessonContent | undefined;
  const hasLesson = !!(lessonData && lessonData.title && lessonData.sections);

  // Handle timestamp click in lesson -> seek video
  const handleTimestampClick = useCallback(() => {
    // Switch to learn tab if not already there (video is always visible in learn tab)
    setActiveTab("learn");
  }, []);

  // ─── Progress display ─────────────────────────────

  const totalCount = sections.length;
  const completedCount = currentIdx + 1;

  // ─── Render: Learn tab ────────────────────────────

  const learnTabContent = (
    <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
      {/* Video side */}
      <div
        className={clsx(
          "flex-shrink-0 bg-gray-900",
          lessonCollapsed ? "w-full" : "lg:w-[55%] w-full"
        )}
      >
        <div className="relative w-full" style={{ paddingBottom: lessonCollapsed ? "56.25%" : "56.25%" }}>
          {videoEmbed ? (
            <iframe
              src={videoEmbed.src}
              className="absolute inset-0 w-full h-full"
              allowFullScreen
              sandbox="allow-scripts allow-same-origin allow-popups"
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <div className="w-16 h-16 rounded-full bg-white/20 flex items-center justify-center mb-2 mx-auto backdrop-blur-sm">
                  <Play className="w-8 h-8 text-white ml-1" />
                </div>
                <p className="text-white/60 text-xs">{course?.title ?? "暂无视频"}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Lesson side */}
      {!lessonCollapsed && (
        <div className="flex-1 flex flex-col overflow-hidden border-l border-gray-200 min-w-0">
          {/* Lesson header with translation toggle */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-200 flex-shrink-0 bg-white">
            <h3 className="text-sm font-semibold text-gray-900 truncate">
              {lessonData?.title ?? section?.title ?? ""}
            </h3>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={handleTranslationToggle}
                disabled={translationLoading || !section}
                className={clsx(
                  "flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors bg-transparent",
                  showTranslation
                    ? "text-blue-600 bg-blue-50"
                    : "text-gray-500 hover:bg-gray-100"
                )}
              >
                {translationLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Languages className="w-3.5 h-3.5" />
                )}
                翻译
              </button>
            </div>
          </div>

          {/* Translation estimate bar */}
          {translationEstimate && !showTranslation && (
            <div className="px-4 py-2 bg-blue-50 border-b border-blue-100 flex-shrink-0">
              <p className="text-xs text-blue-700 mb-1.5">
                需要翻译 {translationEstimate.chunks_to_translate} 个片段
                （已缓存 {translationEstimate.chunks_cached} 个），
                预计 ~{translationEstimate.estimated_tokens.toLocaleString()} tokens
                （${translationEstimate.estimated_cost_usd.toFixed(4)}）
              </p>
              <div className="flex gap-2">
                <button onClick={confirmTranslation} disabled={translationLoading}
                  className="px-2 py-1 rounded text-xs bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
                  确认翻译
                </button>
                <button onClick={() => setTranslationEstimate(null)}
                  className="px-2 py-1 rounded text-xs text-gray-500 hover:bg-gray-100 bg-transparent transition-colors">
                  取消
                </button>
              </div>
            </div>
          )}

          {/* Translation results */}
          {showTranslation && translations.length > 0 && (
            <div className="px-4 py-2 bg-amber-50/50 border-b border-amber-100 max-h-40 overflow-y-auto flex-shrink-0">
              <h4 className="text-xs font-semibold text-amber-700 mb-1">中文翻译</h4>
              <div className="space-y-1">
                {translations.map((t) => (
                  <p key={t.chunk_id} className="text-xs text-gray-700 leading-relaxed">
                    {t.translated_text ?? "（翻译不可用）"}
                  </p>
                ))}
              </div>
            </div>
          )}

          {translationError && (
            <div className="px-4 py-1.5 bg-red-50 border-b border-red-100 flex-shrink-0">
              <span className="text-xs text-red-600">{translationError}</span>
            </div>
          )}

          {/* Lesson content scrollable area */}
          <div
            ref={lessonScrollRef}
            onScroll={handleLessonScroll}
            className="flex-1 overflow-y-auto"
          >
            {hasLesson ? (
              <LessonRenderer lesson={lessonData!} onTimestampClick={handleTimestampClick} />
            ) : section?.content ? (
              <div className="px-4 py-4">
                <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                  {typeof section.content === "string"
                    ? section.content
                    : JSON.stringify(section.content, null, 2)}
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center py-16">
                <div className="text-center">
                  <BookOpen className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                  <p className="text-sm text-gray-400">此章节暂无课文内容</p>
                </div>
              </div>
            )}
          </div>

          {/* Collapse button */}
          <button
            onClick={() => setLessonCollapsed(true)}
            className="flex items-center justify-center gap-1 px-3 py-2 border-t border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-colors bg-white flex-shrink-0"
          >
            收起课文 <ChevronDown className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Floating expand pill when collapsed */}
      {lessonCollapsed && (
        <button
          onClick={() => setLessonCollapsed(false)}
          className="fixed bottom-20 right-6 z-30 flex items-center gap-1 px-4 py-2 rounded-full bg-white border border-gray-200 shadow-lg text-xs text-gray-700 hover:bg-gray-50 transition-colors"
        >
          展开课文 <ChevronUp className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );

  // ─── Render: Lab tab ──────────────────────────────

  const labTabContent = (
    <div className="flex-1 overflow-hidden">
      {labLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 text-gray-300 animate-spin" />
        </div>
      ) : lab ? (
        <LabEditor lab={lab} />
      ) : (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <FlaskConical className="w-8 h-8 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">此章节无 Lab 练习</p>
          </div>
        </div>
      )}
    </div>
  );

  // ─── Render: Graph tab ────────────────────────────

  const graphTabContent = (
    <div className="flex-1 overflow-hidden">
      {graphLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 text-gray-300 animate-spin" />
        </div>
      ) : graphData && graphData.nodes.length > 0 ? (
        <ForceGraph nodes={graphData.nodes} edges={graphData.edges} />
      ) : (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Network className="w-8 h-8 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">暂无知识图谱数据</p>
          </div>
        </div>
      )}
    </div>
  );

  // ─── Tab content dispatcher ───────────────────────

  function renderTabContent() {
    switch (activeTab) {
      case "learn":
        return learnTabContent;
      case "lab":
        return labTabContent;
      case "graph":
        return graphTabContent;
    }
  }

  // ─── Main render ──────────────────────────────────

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* Header */}
      <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-3 flex-shrink-0">
        <Link href="/path" className="text-gray-400 hover:text-gray-600 transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-gray-900 truncate block">
            {course?.title ?? "加载中..."}
          </span>
        </div>
        <span className="text-xs text-gray-400 hidden sm:inline">
          进度 {completedCount}/{totalCount}
        </span>
        <button
          onClick={() => setTutorOpen(true)}
          className={clsx(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
            "bg-blue-600 text-white hover:bg-blue-700"
          )}
        >
          <MessageCircle className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">AI 导师</span>
        </button>
      </header>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 px-4 flex-shrink-0 bg-white">
        {TAB_ITEMS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={clsx(
              "flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors bg-transparent",
              activeTab === tab.id
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-400 hover:text-gray-600"
            )}
          >
            <tab.icon className="w-3.5 h-3.5" /> {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {renderTabContent()}
      </div>

      {/* Footer navigation */}
      <div className="h-12 bg-white border-t border-gray-200 flex items-center px-4 flex-shrink-0">
        <button
          onClick={() => prevSection && navigateToSection(prevSection)}
          disabled={!prevSection}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors bg-transparent"
        >
          <ChevronLeft className="w-4 h-4" />
          <span className="hidden sm:inline">上一节</span>
        </button>
        <div className="flex-1 text-center min-w-0">
          <span className="text-xs text-gray-500 truncate block">
            {section?.title ?? ""}
          </span>
        </div>
        <button
          onClick={() => nextSection && navigateToSection(nextSection)}
          disabled={!nextSection}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors bg-transparent"
        >
          <span className="hidden sm:inline">下一节</span>
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Tutor drawer */}
      <TutorDrawer
        open={tutorOpen}
        onClose={() => setTutorOpen(false)}
        courseId={courseId}
        sectionId={section?.id ?? null}
      />
    </div>
  );
}

// ─── Page export with Suspense ─────────────────────

export default function LearnPage() {
  return (
    <Suspense
      fallback={
        <div className="h-screen flex items-center justify-center">
          <div className="text-sm text-gray-500">加载中...</div>
        </div>
      }
    >
      <LearnPageInner />
    </Suspense>
  );
}
