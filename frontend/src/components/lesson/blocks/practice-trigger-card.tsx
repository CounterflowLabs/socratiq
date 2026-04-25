"use client";

import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";

import LabEditor from "@/components/lab/lab-editor";
import { getSectionLab, type LabResponse } from "@/lib/api";

interface PracticeTriggerCardProps {
  title: string;
  body: string;
  sectionId: string;
  enabled: boolean;
}

type PracticeLoadState = "idle" | "loading" | "ready" | "missing" | "error";

export function PracticeTriggerCard({
  title,
  body,
  sectionId,
  enabled,
}: PracticeTriggerCardProps) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<PracticeLoadState>("idle");
  const [lab, setLab] = useState<LabResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!enabled) return null;

  async function loadLab() {
    setStatus("loading");
    setError(null);

    try {
      const data = await getSectionLab(sectionId);
      if (data) {
        setLab(data);
        setStatus("ready");
        return;
      }

      setLab(null);
      setStatus("missing");
    } catch (fetchError) {
      setLab(null);
      setStatus("error");
      setError(fetchError instanceof Error ? fetchError.message : "练习加载失败，请稍后重试。");
    }
  }

  async function handleToggle() {
    const nextOpen = !open;
    setOpen(nextOpen);

    if (!nextOpen) {
      return;
    }

    if (status === "idle" || status === "error") {
      await loadLab();
    }
  }

  async function handleRetry() {
    await loadLab();
  }

  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50/60 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-2 rounded-md bg-white px-3 py-1 text-xs font-semibold uppercase text-amber-700">
            <FlaskConical className="h-3.5 w-3.5" />
            Practice
          </div>
          <h3 className="mt-3 text-base font-semibold text-slate-900">{title}</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{body}</p>
        </div>
        <button
          type="button"
          onClick={handleToggle}
          className="inline-flex items-center justify-center rounded-md bg-amber-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-600"
        >
          {status === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {open ? "收起练习" : "开始练习"}
        </button>
      </div>

      {open ? (
        <div
          className="mt-5 overflow-hidden transition-all duration-300 ease-out"
          style={{ animation: "expandIn 0.3s ease-out" }}
        >
          <style>{`
            @keyframes expandIn {
              from { opacity: 0; max-height: 0; margin-top: 0; }
              to { opacity: 1; max-height: 1000px; margin-top: 1.25rem; }
            }
          `}</style>
          {status === "loading" ? (
            <div className="rounded-lg border border-dashed border-amber-200 bg-white/80 px-4 py-6 text-sm text-slate-500">
              正在加载本节练习...
            </div>
          ) : status === "error" ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
              <p>{error ?? "练习加载失败，请稍后重试。"}</p>
              <button
                type="button"
                onClick={handleRetry}
                className="mt-3 inline-flex items-center rounded-md border border-red-200 bg-white px-3 py-1.5 text-sm font-medium text-red-700 transition hover:bg-red-100"
              >
                重试
              </button>
            </div>
          ) : status === "ready" && lab ? (
            <LabEditor lab={lab} embedded />
          ) : (
            <div className="rounded-lg border border-dashed border-slate-200 bg-white/80 px-4 py-6 text-sm text-slate-500">
              本节暂未提供可运行的 Lab，先继续阅读，我们稍后再接回来。
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
