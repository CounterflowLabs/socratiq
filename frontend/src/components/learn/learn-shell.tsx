"use client";

import { useCallback, useSyncExternalStore } from "react";
import Link from "next/link";
import { Home } from "lucide-react";
import { clsx } from "clsx";

import { SIDEBAR_DESKTOP_QUERY } from "@/app/layout";

interface LearnShellProps {
  courseTitle: string;
  progressLabel: string;
  asideOpen: boolean;
  onOpenAside: () => void;
  onCloseAside: () => void;
  outline: React.ReactNode;
  lessonStage: React.ReactNode;
  aside: React.ReactNode;
}

function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      if (typeof window.matchMedia !== "function") {
        return () => {};
      }
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    [query],
  );
  const getSnapshot = useCallback(() => {
    if (typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia(query).matches;
  }, [query]);
  const getServerSnapshot = useCallback(() => false, []);
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export default function LearnShell({
  courseTitle,
  progressLabel,
  asideOpen,
  onOpenAside,
  onCloseAside,
  outline,
  lessonStage,
  aside,
}: LearnShellProps) {
  const isDesktop = useMediaQuery(SIDEBAR_DESKTOP_QUERY);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/"
              className="inline-flex shrink-0 items-center gap-2 rounded-full border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
            >
              <Home className="h-4 w-4" />
              返回首页
            </Link>
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-slate-500">
                Learn
              </p>
              <h1 className="truncate text-xl font-semibold text-slate-900">
                {courseTitle}
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-600 sm:inline-flex">
              {progressLabel}
            </span>
            <button
              type="button"
              onClick={onOpenAside}
              aria-expanded={asideOpen}
              className="inline-flex items-center rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700"
            >
              打开学习辅助区
            </button>
          </div>
        </div>
      </header>

      <div
        className={clsx(
          "mx-auto flex max-w-[1600px] flex-col gap-4 px-4 py-4 sm:px-6 xl:grid xl:items-start",
          asideOpen && isDesktop
            ? "xl:grid-cols-[280px_minmax(0,1fr)_320px]"
            : "xl:grid-cols-[280px_minmax(0,1fr)]"
        )}
      >
        <div className="xl:sticky xl:top-4">{outline}</div>
        <div className="min-w-0">{lessonStage}</div>
        {asideOpen && isDesktop ? (
          <div className="min-w-0 xl:sticky xl:top-4">
            {aside}
          </div>
        ) : null}
      </div>

      {asideOpen && !isDesktop ? (
        <div
          className="fixed inset-0 z-50 flex items-end bg-slate-950/40"
          role="dialog"
          aria-modal="true"
          aria-label="学习辅助区"
        >
          <button
            type="button"
            aria-label="关闭学习辅助区遮罩"
            className="absolute inset-0 bg-transparent"
            onClick={onCloseAside}
          />
          <div className="relative z-10 max-h-[88vh] w-full overflow-y-auto rounded-t-[28px] bg-white p-4 shadow-2xl">
            {aside}
          </div>
        </div>
      ) : null}
    </div>
  );
}
