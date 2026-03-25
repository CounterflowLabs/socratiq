"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import {
  ChevronLeft,
  Clock,
  Play,
  Volume2,
  CheckCircle,
  MessageCircle,
  FileText,
  BookOpen,
  Brain,
  Send,
  Plus,
  Languages,
  Loader2,
  Video,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clsx } from "clsx";
import {
  streamChat,
  getCourse,
  estimateTranslation,
  translateSection,
  getKnowledgeGraph,
  type CourseDetailResponse,
  type SectionResponse,
  type KnowledgeGraphNode,
  type KnowledgeGraphEdge,
} from "@/lib/api";
import { useChatStore } from "@/lib/stores";

const ForceGraph = dynamic(
  () => import("@/components/knowledge-graph/force-graph"),
  { ssr: false }
);

const QUICK_PROMPTS = [
  "这个概念能再解释一下吗？",
  "给我举个例子",
  "这和前面学的有什么关系？",
];

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
  const [activeTab, setActiveTab] = useState("chat");
  const [mobileTab, setMobileTab] = useState<"video" | "chat" | "notes">("video");
  const chatEndRef = useRef<HTMLDivElement>(null);

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

  // Knowledge graph state
  const [graphNodes, setGraphNodes] = useState<KnowledgeGraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<KnowledgeGraphEdge[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphLoaded, setGraphLoaded] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

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

  // Auto-scroll
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

  // Reset translation when section changes
  useEffect(() => {
    setShowTranslation(false);
    setTranslations([]);
    setTranslationEstimate(null);
    setTranslationError(null);
  }, [section?.id]);

  // Load knowledge graph when concepts tab is selected
  useEffect(() => {
    if (activeTab === "concepts" && courseId && !graphLoaded) {
      setGraphLoading(true);
      getKnowledgeGraph(courseId)
        .then((data) => {
          setGraphNodes(data.nodes);
          setGraphEdges(data.edges);
          setGraphLoaded(true);
        })
        .catch(() => {
          setGraphNodes([]);
          setGraphEdges([]);
          setGraphLoaded(true);
        })
        .finally(() => setGraphLoading(false));
    }
  }, [activeTab, courseId, graphLoaded]);

  async function handleTranslationToggle() {
    if (showTranslation) {
      setShowTranslation(false);
      return;
    }
    if (!section) return;

    // If we already have translations, just toggle on
    if (translations.length > 0) {
      setShowTranslation(true);
      return;
    }

    // First, get estimate
    setTranslationLoading(true);
    setTranslationError(null);
    try {
      const estimate = await estimateTranslation(section.id);
      setTranslationEstimate(estimate);

      // If all cached or low cost, auto-translate
      if (estimate.chunks_to_translate === 0 || estimate.estimated_cost_usd < 0.01) {
        const result = await translateSection(section.id);
        setTranslations(result.translations);
        setShowTranslation(true);
        setTranslationEstimate(null);
      }
      // Otherwise estimate is shown, user confirms via confirmTranslation
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

  const handleNodeClick = useCallback(
    (node: KnowledgeGraphNode) => {
      if (node.section_id && courseId) {
        router.push(`/learn?courseId=${courseId}&sectionId=${node.section_id}`);
      }
    },
    [courseId, router]
  );

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

  // Extract bvid from a Bilibili URL if available
  function extractBvid(): string | null {
    const sourceUrl =
      section?.source_start ?? (course?.source_ids?.[0] as string | undefined);
    if (!sourceUrl || typeof sourceUrl !== "string") return null;
    const match = sourceUrl.match(/BV[\w]+/);
    return match ? match[0] : null;
  }

  const bvid = extractBvid();

  // --- Shared sub-components for reuse in both mobile and desktop ---

  const videoPlayer = (
    <div className="bg-gray-900 aspect-video relative flex-shrink-0">
      {bvid ? (
        <iframe
          src={`//player.bilibili.com/player.html?bvid=${bvid}&autoplay=0`}
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
  );

  const translationControls = (
    <>
      <div className="px-4 pt-3 pb-1 flex items-center gap-2 flex-shrink-0 border-b border-gray-100">
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
        <div className="px-4 py-3 bg-blue-50 border-b border-blue-100 flex-shrink-0">
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
        <div className="px-4 py-3 bg-amber-50/50 border-b border-amber-100 max-h-48 overflow-y-auto flex-shrink-0">
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
  );

  const chatPanel = (
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

  const notesPanel = (
    <div className="flex-1 p-4 overflow-y-auto">
      <div className="text-center py-8">
        <FileText className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">
          学习过程中的笔记会自动保存在这里
        </p>
        <Button variant="secondary" size="sm" className="mt-3">
          <Plus className="w-3.5 h-3.5" /> 添加笔记
        </Button>
      </div>
    </div>
  );

  const conceptsPanel = (
    <div className="flex-1 p-4 overflow-hidden flex flex-col">
      {graphLoading && (
        <div className="text-center py-8">
          <Loader2 className="w-8 h-8 text-gray-300 mx-auto mb-2 animate-spin" />
          <p className="text-sm text-gray-400">加载概念图谱...</p>
        </div>
      )}
      {!graphLoading && graphNodes.length === 0 && (
        <div className="text-center py-8">
          <BookOpen className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-400">暂无概念数据</p>
        </div>
      )}
      {!graphLoading && graphNodes.length > 0 && !isMobile && (
        <div className="flex-1 min-h-0">
          <ForceGraph
            nodes={graphNodes}
            edges={graphEdges}
            onNodeClick={handleNodeClick}
          />
        </div>
      )}
      {!graphLoading && graphNodes.length > 0 && isMobile && (
        <div className="flex-1 overflow-y-auto space-y-2">
          {graphNodes.map((node) => (
            <button
              key={node.id}
              onClick={() => handleNodeClick(node)}
              className="w-full flex items-center gap-3 px-3 py-2.5 min-h-[44px] rounded-lg hover:bg-gray-50 transition-colors text-left bg-transparent"
            >
              <span className="text-sm font-medium text-gray-800 flex-1">
                {node.label}
              </span>
              <div className="w-20 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.round(node.mastery * 100)}%`,
                    backgroundColor:
                      node.mastery >= 0.7
                        ? "#22c55e"
                        : node.mastery >= 0.3
                          ? "#eab308"
                          : "#ef4444",
                  }}
                />
              </div>
              <span className="text-xs text-gray-400 w-8 text-right">
                {Math.round(node.mastery * 100)}%
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const chapterNav = (
    <div className="flex-1 overflow-y-auto p-4">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
        章节导航
      </h3>
      <div className="space-y-1">
        {course?.sections.map((ch) => {
          const isActive = ch.id === section?.id;
          return (
            <button
              key={ch.id}
              onClick={() => {
                setSection(ch);
                router.push(
                  `/learn?courseId=${courseId}&sectionId=${ch.id}`
                );
              }}
              className={clsx(
                "flex items-center gap-3 px-3 py-2.5 min-h-[44px] rounded-lg text-sm cursor-pointer transition-colors w-full text-left bg-transparent",
                isActive
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : "text-gray-500 hover:bg-gray-50"
              )}
            >
              <Play className="w-4 h-4 flex-shrink-0" />
              <span className="text-xs text-gray-400 w-10 flex-shrink-0">
                {ch.order_index != null ? `#${ch.order_index + 1}` : ""}
              </span>
              <span className="flex-1">{ch.title}</span>
            </button>
          );
        })}
        {!course && (
          <p className="text-sm text-gray-400 px-3 py-2">
            加载课程章节中...
          </p>
        )}
      </div>
    </div>
  );

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* Top bar */}
      <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-2 md:gap-4 flex-shrink-0">
        <Link href="/path" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-900 truncate">
              {section?.title ?? course?.title ?? "加载中..."}
            </span>
            {section && (
              <Badge
                color={
                  section.difficulty <= 2
                    ? "green"
                    : section.difficulty <= 4
                      ? "yellow"
                      : "red"
                }
              >
                {section.difficulty <= 2
                  ? "入门"
                  : section.difficulty <= 4
                    ? "进阶"
                    : "高级"}
              </Badge>
            )}
          </div>
        </div>
        <div className="hidden sm:flex items-center gap-2 text-xs text-gray-400">
          <Clock className="w-3.5 h-3.5" />
          <span>{course?.sections.length ?? 0} 个章节</span>
        </div>
        <Link href="/exercise">
          <Button variant="accent" size="sm" className="min-h-[44px] md:min-h-0">
            <CheckCircle className="w-3.5 h-3.5" /> <span className="hidden sm:inline">开始练习</span><span className="sm:hidden">练习</span>
          </Button>
        </Link>
      </header>

      {/* Mobile tab navigation */}
      <div className="flex md:hidden border-b border-gray-200 flex-shrink-0">
        {[
          { id: "video" as const, label: "视频", icon: Video },
          { id: "chat" as const, label: "聊天", icon: MessageCircle },
          { id: "notes" as const, label: "笔记/概念", icon: FileText },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setMobileTab(tab.id)}
            className={clsx(
              "flex-1 flex items-center justify-center gap-1.5 px-3 py-3 min-h-[44px] text-xs font-medium border-b-2 transition-colors bg-transparent",
              mobileTab === tab.id
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-400 hover:text-gray-600"
            )}
          >
            <tab.icon className="w-3.5 h-3.5" /> {tab.label}
          </button>
        ))}
      </div>

      {/* Mobile content */}
      <div className="flex-1 flex flex-col overflow-hidden md:hidden">
        {mobileTab === "video" && (
          <div className="flex-1 flex flex-col overflow-hidden">
            {videoPlayer}
            {translationControls}
            {chapterNav}
          </div>
        )}
        {mobileTab === "chat" && (
          <div className="flex-1 flex flex-col overflow-hidden">
            {chatPanel}
          </div>
        )}
        {mobileTab === "notes" && (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Sub-tabs for notes vs concepts on mobile */}
            <div className="flex border-b border-gray-200 px-4 flex-shrink-0">
              {[
                { id: "chat", label: "导师问答", icon: MessageCircle },
                { id: "notes", label: "笔记", icon: FileText },
                { id: "concepts", label: "概念", icon: BookOpen },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={clsx(
                    "flex items-center gap-1.5 px-3 py-3 min-h-[44px] text-xs font-medium border-b-2 transition-colors bg-transparent",
                    activeTab === tab.id
                      ? "border-blue-600 text-blue-600"
                      : "border-transparent text-gray-400 hover:text-gray-600"
                  )}
                >
                  <tab.icon className="w-3.5 h-3.5" /> {tab.label}
                </button>
              ))}
            </div>
            {activeTab === "chat" && chatPanel}
            {activeTab === "notes" && notesPanel}
            {activeTab === "concepts" && conceptsPanel}
          </div>
        )}
      </div>

      {/* Desktop content — split view */}
      <div className="flex-1 hidden md:flex overflow-hidden">
        {/* Left: Video (60%) */}
        <div className="w-3/5 flex flex-col border-r border-gray-200">
          {videoPlayer}
          {translationControls}
          {chapterNav}
        </div>

        {/* Right: Chat/Notes/Concepts (40%) */}
        <div className="w-2/5 flex flex-col">
          {/* Tabs */}
          <div className="flex border-b border-gray-200 px-4 flex-shrink-0">
            {[
              { id: "chat", label: "导师问答", icon: MessageCircle },
              { id: "notes", label: "笔记", icon: FileText },
              { id: "concepts", label: "概念", icon: BookOpen },
            ].map((tab) => (
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

          {activeTab === "chat" && chatPanel}
          {activeTab === "notes" && notesPanel}
          {activeTab === "concepts" && conceptsPanel}
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
