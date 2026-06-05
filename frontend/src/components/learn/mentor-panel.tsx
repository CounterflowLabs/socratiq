"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { clsx } from "clsx";

import {
  IcArrowUp,
  IcCite,
  IcClose,
  IcMemory,
  IcSparkle,
  SocratiqMark,
} from "@/components/icons";
import { streamChat, type Citation } from "@/lib/api";
import { useChatStore } from "@/lib/stores";
import { useT } from "@/lib/i18n";
import CitationCards from "@/components/citation-card";

interface MentorPanelProps {
  /** Inline = render as a flat column inside the learn shell (no overlay).
   *  Overlay = render as a slide-in drawer (mobile / legacy). */
  variant?: "inline" | "overlay";
  open?: boolean;
  onClose?: () => void;
  courseId: string | null;
  sectionId: string | null;
  /** Height passthrough so the inline rail can stretch to the lesson reader. */
  fillHeight?: boolean;
}

/**
 * The Socratic mentor — moved from a hidden drawer to a first-class column.
 * The same component renders in two shapes:
 *   - inline: lives in the Learn shell's third column (PRD §5.5)
 *   - overlay: legacy slide-in drawer for mobile and the dashboard "Mentor" CTA
 */
export default function MentorPanel({
  variant = "inline",
  open = true,
  onClose,
  courseId,
  sectionId,
  fillHeight = true,
}: MentorPanelProps) {
  const { t, lang } = useT();
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

  const quickPrompts =
    lang === "zh"
      ? ["解释这个概念", "举个例子", "我不理解", "能简单点说吗"]
      : ["Explain this concept", "Give an example", "I don't follow", "In plainer terms"];

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (variant !== "overlay") return;
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open, variant]);

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
        switch (event.type) {
          case "RUN_STARTED":
            // The conversation id is carried as the run's thread id.
            if (event.threadId) setConversationId(event.threadId);
            break;
          case "TEXT_MESSAGE_CONTENT":
            if (event.delta) appendToLast(event.delta);
            break;
          case "TOOL_CALL_START":
            appendToLast(
              lang === "zh"
                ? "\n\n_正在搜索知识库…_\n\n"
                : "\n\n_Searching the knowledge base…_\n\n",
            );
            break;
          case "CUSTOM":
            if (event.name === "citations" && Array.isArray(event.value)) {
              setCitationsOnLast(event.value as Citation[]);
            }
            break;
          case "RUN_ERROR":
            appendToLast(`\n\n_Error: ${event.message}_`);
            break;
          default:
            break;
        }
      }
    } catch (e) {
      appendToLast(
        `\n\n_${e instanceof Error ? e.message : lang === "zh" ? "未知错误" : "Unknown error"}_`,
      );
    } finally {
      setStreaming(false);
    }
  }

  const chat = (
    <>
      {/* Header — Socratiq mark + tagline + memory icon */}
      <div
        style={{
          padding: "14px 18px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: "var(--accent-soft)",
            color: "var(--accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <SocratiqMark size={20} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="serif" style={{ fontSize: 14, fontWeight: 500 }}>
            {t("learn.mentor")}
          </div>
          <div style={{ fontSize: 10, color: "var(--ink-3)" }}>
            {t("learn.mentorBlurb")}
          </div>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-icon btn-sm"
          title={t("learn.memory")}
        >
          <IcMemory size={14} />
        </button>
        {onClose ? (
          <button
            type="button"
            className="btn btn-ghost btn-icon btn-sm"
            onClick={onClose}
            aria-label={t("common.close")}
          >
            <IcClose size={14} />
          </button>
        ) : null}
      </div>

      {/* Memory strip */}
      <div
        style={{
          padding: "8px 16px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          gap: 6,
          flexWrap: "wrap",
          flexShrink: 0,
        }}
      >
        <span className="chip chip-sage">
          <span
            style={{
              width: 4,
              height: 4,
              borderRadius: "50%",
              background: "var(--sage)",
            }}
          />
          {t("learn.remembers")}
        </span>
        <span className="chip">
          <span
            style={{
              width: 4,
              height: 4,
              borderRadius: "50%",
              background: "var(--warn)",
            }}
          />
          {t("learn.shaky")}
        </span>
      </div>

      {/* Messages */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "20px 18px",
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        {messages.length === 0 ? (
          <div style={{ textAlign: "center", padding: "32px 0" }}>
            <SocratiqMark size={28} />
            <p style={{ marginTop: 8, fontSize: 13, color: "var(--ink-3)", lineHeight: 1.6 }}>
              {lang === "zh"
                ? "向导师提问，开始一次苏格拉底式对话。导师不会直接给答案，而是引导你自己思考。"
                : "Ask the mentor anything to start a Socratic exchange. It guides your thinking — it won't hand you the answer."}
            </p>
          </div>
        ) : null}

        {messages.map((msg) =>
          msg.role === "user" ? (
            <div key={msg.id} style={{ display: "flex", justifyContent: "flex-end" }}>
              <div
                style={{
                  background: "var(--ink)",
                  color: "var(--surface)",
                  padding: "8px 12px",
                  borderRadius: 12,
                  borderTopRightRadius: 3,
                  fontSize: 13,
                  lineHeight: 1.45,
                  maxWidth: "85%",
                  whiteSpace: "pre-wrap",
                }}
              >
                {msg.content}
              </div>
            </div>
          ) : (
            <div key={msg.id} style={{ display: "flex", gap: 10 }}>
              <SocratiqMark size={20} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  className="serif"
                  style={{ fontSize: 14, lineHeight: 1.55, color: "var(--ink)" }}
                >
                  <ReactMarkdown>{msg.content || "…"}</ReactMarkdown>
                </div>
                {msg.citations ? <CitationCards citations={msg.citations} /> : null}
              </div>
            </div>
          ),
        )}

        {isStreaming && messages.length > 0 && !messages[messages.length - 1]?.content ? (
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <SocratiqMark size={18} />
            <span className="pulse" style={{ fontSize: 12, color: "var(--ink-3)" }}>
              {t("learn.thinking")}
            </span>
          </div>
        ) : null}

        <div ref={chatEndRef} />
      </div>

      {/* Quick prompts */}
      <div
        style={{
          padding: "0 16px 8px",
          display: "flex",
          gap: 6,
          flexWrap: "wrap",
          flexShrink: 0,
        }}
      >
        {quickPrompts.map((prompt) => (
          <button
            key={prompt}
            type="button"
            className="chip"
            style={{ cursor: "pointer", height: 24 }}
            onClick={() => sendMessage(prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>

      {/* Composer */}
      <div
        style={{
          padding: 14,
          borderTop: "1px solid var(--border)",
          background: "var(--surface)",
          flexShrink: 0,
        }}
      >
        <div style={{ position: "relative" }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder={t("learn.askPlaceholder")}
            className="input"
            style={{
              height: "auto",
              minHeight: 64,
              paddingRight: 44,
              paddingTop: 10,
              paddingBottom: 10,
              fontSize: 13,
              resize: "none",
            }}
          />
          <button
            type="button"
            onClick={() => sendMessage()}
            disabled={!input.trim() || isStreaming}
            className={clsx("btn btn-icon btn-sm")}
            style={{
              position: "absolute",
              right: 6,
              bottom: 6,
              background: input.trim() ? "var(--ink)" : "var(--surface-2)",
              color: input.trim() ? "var(--surface)" : "var(--ink-3)",
              border: "none",
            }}
            aria-label={lang === "zh" ? "发送" : "Send"}
          >
            <IcArrowUp size={14} />
          </button>
        </div>
        <div
          style={{
            marginTop: 8,
            display: "flex",
            gap: 6,
            fontSize: 10,
            color: "var(--ink-3)",
          }}
        >
          <span className="chip" style={{ height: 20, padding: "0 6px", fontSize: 10 }}>
            <IcSparkle size={10} />
            {t("learn.suggest")}
          </span>
          <span className="chip" style={{ height: 20, padding: "0 6px", fontSize: 10 }}>
            <IcCite size={10} />
            {t("learn.citeLesson")}
          </span>
        </div>
      </div>
    </>
  );

  if (variant === "inline") {
    return (
      <aside
        style={{
          display: "flex",
          flexDirection: "column",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-lg)",
          overflow: "hidden",
          height: fillHeight ? "calc(100vh - 110px)" : undefined,
          maxHeight: fillHeight ? "calc(100vh - 110px)" : undefined,
        }}
      >
        {chat}
      </aside>
    );
  }

  // Overlay variant — slide-in drawer
  return (
    <>
      {open ? (
        <div
          role="presentation"
          onClick={onClose}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 40,
            background: "rgba(26, 22, 17, 0.35)",
            backdropFilter: "blur(2px)",
          }}
        />
      ) : null}
      <aside
        aria-hidden={!open}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          height: "100%",
          zIndex: 50,
          display: "flex",
          flexDirection: "column",
          width: "min(400px, 100vw)",
          background: "var(--surface)",
          borderLeft: "1px solid var(--border)",
          boxShadow: "var(--shadow-lg)",
          transform: open ? "translateX(0)" : "translateX(100%)",
          transition: "transform 0.3s var(--ease-out)",
        }}
      >
        {chat}
      </aside>
    </>
  );
}
