"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
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
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clsx } from "clsx";
import {
  streamChat,
  getCourse,
  type CourseDetailResponse,
  type SectionResponse,
} from "@/lib/api";
import { useChatStore } from "@/lib/stores";

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
  const chatEndRef = useRef<HTMLDivElement>(null);

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

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* Top bar */}
      <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-4 flex-shrink-0">
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
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Clock className="w-3.5 h-3.5" />
          <span>{course?.sections.length ?? 0} 个章节</span>
        </div>
        <Link href="/exercise">
          <Button variant="accent" size="sm">
            <CheckCircle className="w-3.5 h-3.5" /> 开始练习
          </Button>
        </Link>
      </header>

      {/* Main content — split view */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Video (60%) */}
        <div className="w-3/5 flex flex-col border-r border-gray-200">
          {/* Video player / embed */}
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

          {/* Chapter navigation */}
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
                      "flex items-center gap-3 px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors w-full text-left bg-transparent",
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

          {/* Chat Tab */}
          {activeTab === "chat" && (
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
                    className="flex-1 px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  <Button
                    size="md"
                    onClick={sendMessage}
                    disabled={!input.trim() || isStreaming}
                  >
                    <Send className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Notes Tab */}
          {activeTab === "notes" && (
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
          )}

          {/* Concepts Tab */}
          {activeTab === "concepts" && (
            <div className="flex-1 p-4 overflow-y-auto">
              <div className="text-center py-8">
                <BookOpen className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-400">
                  概念图谱将在学习过程中自动生成
                </p>
              </div>
            </div>
          )}
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
