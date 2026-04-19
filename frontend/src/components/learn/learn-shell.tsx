"use client";

import { clsx } from "clsx";

interface LearnShellProps {
  courseTitle: string;
  progressLabel: string;
  asideOpen: boolean;
  onOpenAside: () => void;
  outline: React.ReactNode;
  lessonStage: React.ReactNode;
  aside: React.ReactNode;
}

export default function LearnShell({
  courseTitle,
  progressLabel,
  asideOpen,
  onOpenAside,
  outline,
  lessonStage,
  aside,
}: LearnShellProps) {
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.24em] text-slate-500">
              Learn
            </p>
            <h1 className="truncate text-xl font-semibold text-slate-900">
              {courseTitle}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-600 sm:inline-flex">
              {progressLabel}
            </span>
            <button
              type="button"
              onClick={onOpenAside}
              className="inline-flex items-center rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700"
            >
              打开学习辅助区
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1600px] flex-col gap-4 px-4 py-4 sm:px-6 xl:grid xl:grid-cols-[280px_minmax(0,1fr)_320px] xl:items-start">
        <div className="xl:sticky xl:top-4">{outline}</div>
        <div className="min-w-0">{lessonStage}</div>
        <div
          className={clsx(
            "min-w-0 xl:sticky xl:top-4 xl:block",
            asideOpen ? "block" : "hidden"
          )}
        >
          {aside}
        </div>
      </div>
    </div>
  );
}
