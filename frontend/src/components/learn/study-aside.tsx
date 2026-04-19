"use client";

import { useEffect, useState } from "react";
import { BookOpen, ExternalLink, FileText, MessageCircle, PlayCircle } from "lucide-react";

import { clsx } from "clsx";

import type { SourceSummary } from "@/lib/api";

type AsidePanelId = "video" | "pdf" | "references" | "tutor";

interface StudyAsideProps {
  courseTitle: string;
  currentSectionTitle: string;
  progressLabel: string;
  onOpenTutor: () => void;
  onClose?: () => void;
  videoEmbed: { src: string } | null;
  pdfSource: SourceSummary | null;
  referenceSources: SourceSummary[];
}

export default function StudyAside({
  courseTitle,
  currentSectionTitle,
  progressLabel,
  onOpenTutor,
  onClose,
  videoEmbed,
  pdfSource,
  referenceSources,
}: StudyAsideProps) {
  const panels: AsidePanelId[] = [];

  if (videoEmbed) panels.push("video");
  if (pdfSource) panels.push("pdf");
  if (referenceSources.length > 0) panels.push("references");
  panels.push("tutor");

  const [activePanel, setActivePanel] = useState<AsidePanelId>(panels[0]);

  useEffect(() => {
    setActivePanel((currentPanel) =>
      panels.includes(currentPanel) ? currentPanel : panels[0]
    );
  }, [videoEmbed, pdfSource, referenceSources.length]);

  return (
    <aside className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-slate-400">
            Study Support
          </p>
          <h2 className="mt-1 text-lg font-semibold text-slate-900">学习辅助区</h2>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-3 py-1 text-sm text-slate-500 transition hover:bg-slate-100"
          >
            关闭学习辅助区
          </button>
        ) : null}
      </div>

      <div className="mt-5 space-y-4">
        <section className="rounded-2xl bg-slate-50 p-4">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">
            当前学习
          </p>
          <p className="mt-2 text-base font-semibold text-slate-900">{currentSectionTitle}</p>
          <p className="mt-1 text-sm text-slate-500">{courseTitle}</p>
          <p className="mt-3 inline-flex rounded-full bg-white px-3 py-1 text-sm font-medium text-slate-600 shadow-sm">
            {progressLabel}
          </p>
        </section>

        <div className="flex flex-wrap gap-2">
          {panels.includes("video") ? (
            <button
              type="button"
              onClick={() => setActivePanel("video")}
              className={clsx(
                "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition",
                activePanel === "video"
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              )}
            >
              <PlayCircle className="h-4 w-4" />
              原视频
            </button>
          ) : null}
          {panels.includes("pdf") ? (
            <button
              type="button"
              onClick={() => setActivePanel("pdf")}
              className={clsx(
                "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition",
                activePanel === "pdf"
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              )}
            >
              <FileText className="h-4 w-4" />
              原 PDF
            </button>
          ) : null}
          {panels.includes("references") ? (
            <button
              type="button"
              onClick={() => setActivePanel("references")}
              className={clsx(
                "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition",
                activePanel === "references"
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              )}
            >
              <BookOpen className="h-4 w-4" />
              参考资料
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setActivePanel("tutor")}
            className={clsx(
              "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition",
              activePanel === "tutor"
                ? "bg-slate-900 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            )}
          >
            <MessageCircle className="h-4 w-4" />
            AI 导师
          </button>
        </div>

        <section className="rounded-2xl border border-slate-200 p-4">
          {activePanel === "video" && videoEmbed ? (
            <>
              <h3 className="text-sm font-semibold text-slate-900">原视频</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                需要回看原材料时再展开，不占据正文主舞台。
              </p>
              <div className="mt-4 overflow-hidden rounded-2xl bg-slate-950">
                <div className="relative w-full pb-[56.25%]">
                  <iframe
                    title="课程原视频"
                    src={videoEmbed.src}
                    className="absolute inset-0 h-full w-full"
                    allowFullScreen
                    sandbox="allow-scripts allow-same-origin allow-popups"
                  />
                </div>
              </div>
            </>
          ) : null}

          {activePanel === "pdf" && pdfSource ? (
            <>
              <h3 className="text-sm font-semibold text-slate-900">原 PDF</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                这份原始资料可用于和正文内容对照阅读。
              </p>
              <a
                href={pdfSource.url ?? "#"}
                target="_blank"
                rel="noreferrer"
                className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                打开原 PDF
                <ExternalLink className="h-4 w-4" />
              </a>
            </>
          ) : null}

          {activePanel === "references" ? (
            <>
              <h3 className="text-sm font-semibold text-slate-900">参考资料</h3>
              <div className="mt-3 space-y-3">
                {referenceSources.map((source) => (
                  <a
                    key={source.id}
                    href={source.url ?? "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center justify-between rounded-2xl border border-slate-200 px-4 py-3 text-sm text-slate-700 transition hover:bg-slate-50"
                  >
                    <span>
                      {source.type === "pdf" ? "PDF 资料" : "参考链接"}
                    </span>
                    <ExternalLink className="h-4 w-4 text-slate-400" />
                  </a>
                ))}
              </div>
            </>
          ) : null}

          {activePanel === "tutor" ? (
            <>
              <h3 className="text-sm font-semibold text-slate-900">AI 导师</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                把当前章节里的疑问、例子扩展和思路卡点集中交给导师处理，不打断正文阅读节奏。
              </p>
              <button
                type="button"
                onClick={onOpenTutor}
                className="mt-4 inline-flex w-full items-center justify-center rounded-2xl bg-blue-600 px-4 py-3 text-sm font-medium text-white transition hover:bg-blue-700"
              >
                打开 AI 导师
              </button>
            </>
          ) : null}
        </section>
      </div>
    </aside>
  );
}
