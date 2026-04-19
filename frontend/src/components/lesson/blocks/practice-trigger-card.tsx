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

export function PracticeTriggerCard({
  title,
  body,
  sectionId,
  enabled,
}: PracticeTriggerCardProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lab, setLab] = useState<LabResponse | null>(null);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!enabled) return null;

  async function handleToggle() {
    const nextOpen = !open;
    setOpen(nextOpen);

    if (!nextOpen || lab || attempted) {
      return;
    }

    setAttempted(true);
    setLoading(true);
    setError(null);

    try {
      const data = await getSectionLab(sectionId);
      setLab(data);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "练习加载失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50/60 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-amber-700">
            <FlaskConical className="h-3.5 w-3.5" />
            Practice
          </div>
          <h3 className="mt-3 text-base font-semibold text-slate-900">{title}</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{body}</p>
        </div>
        <button
          type="button"
          onClick={handleToggle}
          className="inline-flex items-center justify-center rounded-full bg-amber-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-600"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {open ? "收起练习" : "开始练习"}
        </button>
      </div>

      {open ? (
        <div className="mt-5">
          {loading ? (
            <div className="rounded-2xl border border-dashed border-amber-200 bg-white/80 px-4 py-6 text-sm text-slate-500">
              正在加载本节练习...
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
              {error}
            </div>
          ) : lab ? (
            <LabEditor lab={lab} embedded />
          ) : (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-white/80 px-4 py-6 text-sm text-slate-500">
              本节暂未提供可运行的 Lab，先继续阅读，我们稍后再接回来。
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
