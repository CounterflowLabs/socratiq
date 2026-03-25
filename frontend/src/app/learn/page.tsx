"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import {
  ChevronLeft,
  ChevronDown,
  Clock,
  Play,
  CheckCircle,
  MessageCircle,
  FileText,
  BookOpen,
  Brain,
  Send,
  Languages,
  Loader2,
  Video,
  FlaskConical,
  Menu,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clsx } from "clsx";
import {
  streamChat,
  getCourse,
  getSectionLab,
  estimateTranslation,
  translateSection,
  type CourseDetailResponse,
  type SectionResponse,
  type LabResponse,
} from "@/lib/api";
import { useChatStore } from "@/lib/stores";
import LessonRenderer from "@/components/lesson/lesson-renderer";
import LabViewer from "@/components/lab/lab-viewer";

const QUICK_PROMPTS = [
  "这个概念能再解释一下吗？",
  "给我举个例子",
  "这和前面学的有什么关系？",
];

type TabId = "lesson" | "video" | "lab" | "tutor";

const TAB_ITEMS: { id: TabId; label: string; icon: typeof FileText }[] = [
  { id: "lesson", label: "课文", icon: BookOpen },
  { id: "video", label: "视频", icon: Video },
  { id: "lab", label: "Lab", icon: FlaskConical },
  { id: "tutor", label: "导师", icon: MessageCircle },
];

// ─── LessonContent type matching LessonRenderer ───────
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

function isLessonContent(obj: unknown): obj is LessonContent {
  if (!obj || typeof obj !== "object") return false;
  const o = obj as Record<string, unknown>;
  return (
    typeof o.title === "string" &&
    typeof o.summary === "string" &&
    Array.isArray(o.sections)
  );
}

function LearnPageInner() {
  const searchParams = useSearchParams();
  const sectionId = searchParams.get("sectionId");
  const courseId = searchParams.get("courseId");
  const router = useRouter();

  const {
    messages,
    addMessage,
    appendToLast,
    isStreaming,
    setStreaming,
    conversationId,
    setConversationId,
  } = useChatStore();

  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [section, setSection] = useState<SectionResponse | null>(null);
  const [input, setInput] = useState("");
  const [activeTab, setActiveTab] = useState<TabId>("lesson");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Lab state
  const [lab, setLab] = useState<LabResponse | null>(null);
  const [labLoading, setLabLoading] = useState(false);

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

  // Video timestamp for seeking
  const [videoTimestamp, setVideoTimestamp] = useState<number | null>(null);

  // Load course and section data
  useEffect(() => {
    if (courseId) {
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
    }
  }, [courseId, sectionId]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Detect mobile
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768);
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // Reset translation + lab when section changes
  useEffect(() => {
    setShowTranslation(false);
    setTranslations([]);
    setTranslationEstimate(null);
    setTranslationError(null);
    setLab(null);
  }, [section?.id]);

  // Load lab when lab tab is selected
  useEffect(() => {
    if (activeTab === "lab" && section?.id && !lab && !labLoading) {
      setLabLoading(true);
      getSectionLab(section.id)
        .then((data) => setLab(data))
        .catch(() => setLab(null))
        .finally(() => setLabLoading(false));
    }
  }, [activeTab, section?.id, lab, labLoading]);

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

  async function sendMessage() {
    if (!input.trim() || isStreaming) return;
    const text = input.trim();
    setInput("");

    addMessage({ id: crypto.randomUUID(), role: "user", content: text });
    addMessage({ id: crypto.randomUUID(), role: "assistant", content: "" });
    setStreaming(true);

    try {
      for await (const event of streamChat(
        text,
        conversationId || undefined,
        courseId || undefined
      )) {
        if (event.event === "text_delta" && event.text) {
          appendToLast(event.text);
        } else if (event.event === "message_end" && event.conversation_id) {
          setConversationId(event.conversation_id);
        } else if (event.event === "error") {
          appendToLast(`\n\n_Error: ${event.message}_`);
        }
      }
    } catch (e) {
      appendToLast(
        `\n\n_连接错误: ${e instanceof Error ? e.message : "未知错误"}_`
      );
    } finally {
      setStreaming(false);
    }
  }

  // Extract bvid from source URL
  function extractBvid(): string | null {
    const sourceUrl =
      section?.source_start ?? (course?.source_ids?.[0] as string | undefined);
    if (!sourceUrl || typeof sourceUrl !== "string") return null;
    const match = sourceUrl.match(/BV[\w]+/);
    return match ? match[0] : null;
  }

  // Get the page index for current section (for multi-part bilibili videos)
  function getSectionPage(): number {
    if (!section || section.order_index == null) return 1;
    return section.order_index + 1;
  }

  const bvid = extractBvid();

  // Compute completion count
  const completedCount = 0; // placeholder — future: track completed sections
  const totalCount = course?.sections.length ?? 0;

  // Handle timestamp click from lesson → switch to video tab and seek
  const handleTimestampClick = useCallback((seconds: number) => {
    setVideoTimestamp(seconds);
    setActiveTab("video");
  }, []);

  // Parse section content as LessonContent
  const lessonContent: LessonContent | null = section?.content
    ? isLessonContent(section.content)
      ? (section.content as LessonContent)
      : null
    : null;

  // Navigate to a different section
  function navigateToSection(sec: SectionResponse) {
    setSection(sec);
    setSidebarOpen(false);
    router.push(`/learn?courseId=${courseId}&sectionId=${sec.id}`);
  }

  // ─── Sidebar (course outline) ──────────────────────────

  const sidebarContent = (
    <div className="flex-1 overflow-y-auto p-3">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 px-2">
        大纲导航
      </h3>
      <div className="space-y-0.5">
        {course?.sections.map((sec) => {
          const isActive = sec.id === section?.id;
          return (
            <button
              key={sec.id}
              onClick={() => navigateToSection(sec)}
              className={clsx(
                "flex items-center gap-2 px-3 py-2.5 min-h-[40px] rounded-lg text-sm cursor-pointer transition-colors w-full text-left bg-transparent",
                isActive
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : "text-gray-600 hover:bg-gray-50"
              )}
            >
              <span className="flex-shrink-0 text-xs">
                {isActive ? "●" : "○"}
              </span>
              <span className="flex-1 truncate">{sec.title}</span>
            </button>
          );
        })}
        {!course && (
          <p className="text-sm text-gray-400 px-3 py-2">加载中...</p>
        )}
      </div>
    </div>
  );

  // ─── Tab: 课文 (Lesson) ────────────────────────────────

  const lessonTab = (
    <div className="flex-1 overflow-y-auto">
      {lessonContent ? (
        <LessonRenderer
          lesson={lessonContent}
          onTimestampClick={handleTimestampClick}
        />
      ) : section?.content ? (
        <div className="max-w-3xl mx-auto px-4 py-6">
          <h2 className="text-lg font-bold text-gray-900 mb-3">
            {section.title}
          </h2>
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

      {/* Translation controls below lesson */}
      {activeTab === "lesson" && (
        <>
          <div className="px-4 pb-3 flex items-center gap-2 border-t border-gray-100 pt-3">
            <Button
              variant={showTranslation ? "accent" : "secondary"}
              size="sm"
              onClick={handleTranslationToggle}
              disabled={translationLoading || !section}
            >
              {translationLoading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Languages className="w-3.5 h-3.5" />
              )}
              {showTranslation ? "隐藏翻译" : "翻译为中文"}
            </Button>
            {translationError && (
              <span className="text-xs text-red-500">{translationError}</span>
            )}
          </div>

          {translationEstimate && !showTranslation && (
            <div className="px-4 py-3 bg-blue-50 border-t border-blue-100">
              <p className="text-xs text-blue-700 mb-2">
                需要翻译 {translationEstimate.chunks_to_translate} 个片段
                （已缓存 {translationEstimate.chunks_cached} 个），
                预计消耗 ~{translationEstimate.estimated_tokens.toLocaleString()} tokens
                （${translationEstimate.estimated_cost_usd.toFixed(4)}）
              </p>
              <div className="flex gap-2">
                <Button size="sm" onClick={confirmTranslation} disabled={translationLoading}>
                  确认翻译
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setTranslationEstimate(null)}
                >
                  取消
                </Button>
              </div>
            </div>
          )}

          {showTranslation && translations.length > 0 && (
            <div className="px-4 py-3 bg-amber-50/50 border-t border-amber-100 max-h-48 overflow-y-auto">
              <h4 className="text-xs font-semibold text-amber-700 mb-2">中文翻译</h4>
              <div className="space-y-2">
                {translations.map((t) => (
                  <p key={t.chunk_id} className="text-sm text-gray-700 leading-relaxed">
                    {t.translated_text ?? "（翻译不可用）"}
                  </p>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );

  // ─── Tab: 视频 (Video) ─────────────────────────────────

  const videoTab = (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="bg-gray-900 aspect-video relative flex-shrink-0">
        {bvid ? (
          <iframe
            key={`${bvid}-${getSectionPage()}-${videoTimestamp ?? ""}`}
            src={`//player.bilibili.com/player.html?bvid=${bvid}&p=${getSectionPage()}&autoplay=0${videoTimestamp != null ? `&t=${videoTimestamp}` : ""}`}
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
              <p className="text-white/60 text-xs">
                {course?.title ?? "选择课程后播放视频"}
              </p>
            </div>
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-1">
          {section?.title ?? ""}
        </h3>
        {section && (
          <p className="text-xs text-gray-400">
            第 {(section.order_index ?? 0) + 1} 章 · {course?.title}
          </p>
        )}
      </div>
    </div>
  );

  // ─── Tab: Lab ──────────────────────────────────────────

  const labTab = (
    <div className="flex-1 overflow-y-auto">
      {labLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 text-gray-300 animate-spin" />
        </div>
      ) : lab ? (
        <LabViewer lab={lab} />
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

  // ─── Tab: 导师 (Tutor chat) ────────────────────────────

  const tutorTab = (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <Brain className="w-8 h-8 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">
              向导师提问，开始学习对话
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={clsx(
              "flex gap-2",
              msg.role === "user" ? "flex-row-reverse" : ""
            )}
          >
            {msg.role === "assistant" && (
              <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                <Brain className="w-3.5 h-3.5 text-blue-600" />
              </div>
            )}
            <div
              className={clsx(
                "max-w-[85%] px-3 py-2 rounded-xl text-sm leading-relaxed",
                msg.role === "user"
                  ? "bg-blue-600 text-white rounded-br-sm"
                  : "bg-gray-100 text-gray-800 rounded-bl-sm"
              )}
            >
              {msg.role === "assistant" ? (
                <div className="prose prose-sm max-w-none">
                  <ReactMarkdown>
                    {msg.content || "..."}
                  </ReactMarkdown>
                </div>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}
        {isStreaming &&
          messages.length > 0 &&
          !messages[messages.length - 1]?.content && (
            <div className="flex gap-2">
              <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                <Brain className="w-3.5 h-3.5 text-blue-600" />
              </div>
              <div className="bg-gray-100 rounded-xl rounded-bl-sm px-3 py-2">
                <div className="flex gap-1">
                  <div
                    className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce"
                    style={{ animationDelay: "0ms" }}
                  />
                  <div
                    className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce"
                    style={{ animationDelay: "150ms" }}
                  />
                  <div
                    className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce"
                    style={{ animationDelay: "300ms" }}
                  />
                </div>
              </div>
            </div>
          )}
        <div ref={chatEndRef} />
      </div>

      {/* Quick prompts */}
      <div className="px-4 pb-2 flex gap-2 flex-wrap flex-shrink-0">
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => setInput(prompt)}
            className="px-2.5 py-1 rounded-full border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors bg-transparent"
          >
            {prompt}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="p-4 border-t border-gray-100 flex-shrink-0">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="向导师提问..."
            className="flex-1 px-3 py-2.5 min-h-[44px] rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <Button
            size="md"
            onClick={sendMessage}
            disabled={!input.trim() || isStreaming}
            className="min-w-[44px] min-h-[44px]"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  );

  // ─── Tab content dispatcher ────────────────────────────

  function renderTabContent() {
    switch (activeTab) {
      case "lesson":
        return lessonTab;
      case "video":
        return videoTab;
      case "lab":
        return labTab;
      case "tutor":
        return tutorTab;
    }
  }

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* Top bar */}
      <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-2 md:gap-4 flex-shrink-0">
        <Link href="/path" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-gray-900 truncate">
            {course?.title ?? "加载中..."}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Clock className="w-3.5 h-3.5" />
          <span>
            进度 {completedCount}/{totalCount}
          </span>
        </div>
        <Link href="/exercise">
          <Button variant="accent" size="sm" className="min-h-[44px] md:min-h-0">
            <CheckCircle className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">开始练习</span>
            <span className="sm:hidden">练习</span>
          </Button>
        </Link>
      </header>

      {/* Mobile: section dropdown toggle */}
      <div className="md:hidden border-b border-gray-200 flex-shrink-0">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="flex items-center gap-2 px-4 py-2.5 w-full text-left text-sm font-medium text-gray-700 bg-transparent hover:bg-gray-50 transition-colors"
        >
          <Menu className="w-4 h-4 text-gray-400" />
          <span className="flex-1 truncate">
            {section?.title ?? "选择章节"}
          </span>
          <ChevronDown
            className={clsx(
              "w-4 h-4 text-gray-400 transition-transform",
              sidebarOpen && "rotate-180"
            )}
          />
        </button>
        {sidebarOpen && (
          <div className="max-h-60 overflow-y-auto border-t border-gray-100 bg-gray-50">
            {sidebarContent}
          </div>
        )}
      </div>

      {/* Main content area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Desktop sidebar */}
        <aside className="hidden md:flex md:w-56 lg:w-64 flex-col border-r border-gray-200 bg-gray-50/50 flex-shrink-0">
          {sidebarContent}
        </aside>

        {/* Content pane */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          {/* Tab bar */}
          <div className="flex border-b border-gray-200 px-4 flex-shrink-0 bg-white">
            {TAB_ITEMS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={clsx(
                  "flex items-center gap-1.5 px-3 py-3 text-xs font-medium border-b-2 transition-colors bg-transparent",
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
        </div>
      </div>
    </div>
  );
}

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
