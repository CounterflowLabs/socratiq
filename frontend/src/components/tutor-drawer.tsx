"use client";

import { useEffect, useRef, useState } from "react";
import { X, Send, Brain } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { clsx } from "clsx";
import { streamChat } from "@/lib/api";
import { useChatStore } from "@/lib/stores";
import CitationCards from "@/components/citation-card";

const QUICK_PROMPTS = [
  "解释这个概念",
  "举个例子",
  "我不理解",
  "能简单点说吗",
];

interface TutorDrawerProps {
  open: boolean;
  onClose: () => void;
  courseId: string | null;
  sectionId: string | null;
}

export default function TutorDrawer({ open, onClose, courseId, sectionId }: TutorDrawerProps) {
  const {
    messages,
    addMessage,
    appendToLast,
    setCitationsOnLast,
    isStreaming,
    setStreaming,
    conversationId,
    setConversationId,
  } = useChatStore();

  const [input, setInput] = useState("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  async function sendMessage(text?: string) {
    const msg = (text ?? input).trim();
    if (!msg || isStreaming) return;
    setInput("");

    addMessage({ id: crypto.randomUUID(), role: "user", content: msg });
    addMessage({ id: crypto.randomUUID(), role: "assistant", content: "" });
    setStreaming(true);

    try {
      for await (const event of streamChat({
        message: msg,
        conversationId: conversationId || undefined,
        courseId: courseId || undefined,
        sectionId: sectionId || undefined,
      })) {
        if (event.event === "text_delta" && event.text) {
          appendToLast(event.text);
        } else if (event.event === "tool_start") {
          appendToLast("\n\n_正在搜索知识库..._\n\n");
        } else if (event.event === "message_end" && event.conversation_id) {
          setConversationId(event.conversation_id);
        } else if (event.event === "citations" && event.citations) {
          setCitationsOnLast(event.citations);
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

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 bg-black/30 backdrop-blur-sm z-40 transition-opacity"
          onClick={onClose}
        />
      )}

      {/* Drawer */}
      <div
        className={clsx(
          "fixed top-0 right-0 h-full z-50 flex flex-col",
          "bg-white border-l border-gray-200 shadow-2xl",
          "transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full"
        )}
        style={{ width: "min(400px, 100vw)" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 flex-shrink-0">
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-blue-600" />
            <span className="text-sm font-semibold text-gray-900">AI 导师</span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors bg-transparent"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-12">
              <Brain className="w-8 h-8 text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-400">向导师提问，开始学习对话</p>
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
                  <>
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown>{msg.content || "..."}</ReactMarkdown>
                    </div>
                    {msg.citations && <CitationCards citations={msg.citations} />}
                  </>
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
              onClick={() => sendMessage(prompt)}
              className="px-2.5 py-1 rounded-full border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors bg-transparent"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="p-4 border-t border-gray-200 flex-shrink-0">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
              placeholder="向导师提问..."
              className="flex-1 px-3 py-2.5 min-h-[44px] rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || isStreaming}
              className="min-w-[44px] min-h-[44px] rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
