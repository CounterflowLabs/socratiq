"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Clock, Play, Volume2, CheckCircle, MessageCircle, FileText, BookOpen, Brain, Send, AlertCircle, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/progress-bar";
import { clsx } from "clsx";
import { streamChat } from "@/lib/api";

type ChatMessage = { role: "mentor" | "user"; content: string };

const INITIAL_CHAT: ChatMessage[] = [
  { role: "mentor" as const, content: "你好！我看到你正在学习 3Blue1Brown 的「深度学习之数学原理」系列视频。基于我们的初始评估，你对 Python 编程有不错的基础，但对 Transformer 架构还比较陌生。我建议我们从 Tokenization 开始——这是理解 LLM 的第一块拼图。准备好了吗？" },
];

const CHAPTERS = [
  { time: "0:00", title: "什么是 Tokenization", active: true, done: true },
  { time: "8:20", title: "BPE 算法原理", active: true, done: false },
  { time: "18:45", title: "Vocabulary 构建", active: false, done: false },
  { time: "28:10", title: "特殊 Token 处理", active: false, done: false },
];

const QUICK_PROMPTS = ["这个概念能再解释一下吗？", "给我举个例子", "这和前面学的有什么关系？"];

const FALLBACK_RESPONSES = [
  "这是个很好的问题！让我先问你：你觉得为什么我们需要把文字转换成数字？计算机本身能直接\"理解\"文字吗？试着从计算机底层的角度想一想。",
  "你的思路方向是对的！不过让我再追问一下——你提到计算机只能处理数字，那为什么不简单地给每个字一个编号就行了？为什么还需要 Tokenization 这么复杂的过程？",
  "非常好的分析！你提到了一个关键点。让我们看看视频 23:15 处 3Blue1Brown 的解释，他用了一个非常直观的可视化。看完那段后我们继续讨论。",
];

export default function LearnPage() {
  const [messages, setMessages] = useState(INITIAL_CHAT);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [activeTab, setActiveTab] = useState("chat");
  const [videoProgress] = useState(35);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const responseIdx = useRef(0);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || typing) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setTyping(true);

    try {
      let assistantContent = "";
      setMessages((prev) => [...prev, { role: "mentor", content: "" }]);

      for await (const event of streamChat(userMsg)) {
        if (event.type === "text_delta" && event.text) {
          assistantContent += event.text;
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = { role: "mentor", content: assistantContent };
            return copy;
          });
        }
      }
    } catch {
      // Fallback for when backend is unavailable
      const response = FALLBACK_RESPONSES[responseIdx.current % FALLBACK_RESPONSES.length];
      responseIdx.current++;
      await new Promise((r) => setTimeout(r, 1200));
      setMessages((prev) => [...prev, { role: "mentor", content: response }]);
    } finally {
      setTyping(false);
    }
  };

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* Top bar */}
      <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-4 flex-shrink-0">
        <Link href="/path" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-900 truncate">第 1 章：Tokenization 基础</span>
            <Badge color="green">入门</Badge>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Clock className="w-3.5 h-3.5" />
          <span>15 min 剩余</span>
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
          {/* Video player mockup */}
          <div className="bg-gray-900 aspect-video relative flex-shrink-0">
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <div className="w-16 h-16 rounded-full bg-white/20 flex items-center justify-center mb-2 mx-auto backdrop-blur-sm cursor-pointer hover:bg-white/30 transition-colors">
                  <Play className="w-8 h-8 text-white ml-1" />
                </div>
                <p className="text-white/60 text-xs">深度学习之数学原理 — 3Blue1Brown · Bilibili</p>
              </div>
            </div>
            {/* Video controls */}
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-3">
              <div className="h-1 bg-white/20 rounded-full mb-2 cursor-pointer">
                <div className="h-full bg-blue-500 rounded-full" style={{ width: `${videoProgress}%` }} />
              </div>
              <div className="flex items-center justify-between text-white/80 text-xs">
                <div className="flex items-center gap-3">
                  <Play className="w-3.5 h-3.5 cursor-pointer" />
                  <span>12:35 / 35:42</span>
                </div>
                <div className="flex items-center gap-3">
                  <Volume2 className="w-3.5 h-3.5 cursor-pointer" />
                  <span className="cursor-pointer">1x</span>
                </div>
              </div>
            </div>
          </div>

          {/* Chapter navigation */}
          <div className="flex-1 overflow-y-auto p-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">章节导航</h3>
            <div className="space-y-1">
              {CHAPTERS.map((ch, i) => (
                <div
                  key={i}
                  className={clsx(
                    "flex items-center gap-3 px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors",
                    ch.active && !ch.done ? "bg-blue-50 text-blue-700 font-medium" : ch.done ? "text-gray-400" : "text-gray-500 hover:bg-gray-50"
                  )}
                >
                  {ch.done ? <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" /> : <Play className="w-4 h-4 flex-shrink-0" />}
                  <span className="text-xs text-gray-400 w-10 flex-shrink-0">{ch.time}</span>
                  <span className="flex-1">{ch.title}</span>
                </div>
              ))}
            </div>

            {/* Difficulty detection */}
            <div className="mt-6 p-3 rounded-xl bg-amber-50 border border-amber-100">
              <div className="flex items-center gap-2 text-xs font-medium text-amber-700 mb-1">
                <AlertCircle className="w-3.5 h-3.5" /> 系统检测到难点
              </div>
              <p className="text-xs text-amber-600">你在 8:20-12:35 区间回看了 3 次，这可能是难点。需要我用不同方式讲解 BPE 算法吗？</p>
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
                  activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-gray-400 hover:text-gray-600"
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
                {messages.map((msg, i) => (
                  <div key={i} className={clsx("flex gap-2", msg.role === "user" ? "flex-row-reverse" : "")}>
                    {msg.role === "mentor" && (
                      <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                        <Brain className="w-3.5 h-3.5 text-blue-600" />
                      </div>
                    )}
                    <div className={clsx(
                      "max-w-[85%] px-3 py-2 rounded-xl text-sm leading-relaxed",
                      msg.role === "user" ? "bg-blue-600 text-white rounded-br-sm" : "bg-gray-100 text-gray-800 rounded-bl-sm"
                    )}>
                      {msg.content || "..."}
                    </div>
                  </div>
                ))}
                {typing && (
                  <div className="flex gap-2">
                    <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                      <Brain className="w-3.5 h-3.5 text-blue-600" />
                    </div>
                    <div className="bg-gray-100 rounded-xl rounded-bl-sm px-3 py-2">
                      <div className="flex gap-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "300ms" }} />
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
                  <Button size="md" onClick={sendMessage} disabled={!input.trim() || typing}>
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
                <p className="text-sm text-gray-400">学习过程中的笔记会自动保存在这里</p>
                <Button variant="secondary" size="sm" className="mt-3">
                  <Plus className="w-3.5 h-3.5" /> 添加笔记
                </Button>
              </div>
            </div>
          )}

          {/* Concepts Tab */}
          {activeTab === "concepts" && (
            <div className="flex-1 p-4 overflow-y-auto space-y-3">
              {["BPE (Byte Pair Encoding)", "Token", "Vocabulary", "Subword"].map((concept, i) => (
                <div key={i} className="p-3 rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-gray-900">{concept}</span>
                    <Badge color={i < 2 ? "green" : "gray"}>{i < 2 ? "学习中" : "未开始"}</Badge>
                  </div>
                  {i < 2 && <ProgressBar value={i === 0 ? 60 : 30} className="mt-2" />}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
