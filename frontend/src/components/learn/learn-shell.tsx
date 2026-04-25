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
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <header
        className="sticky top-0 z-30 border-b backdrop-blur"
        style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--surface) 95%, transparent)" }}
      >
        <div className="mx-auto flex max-w-[1760px] items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/"
              className="inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition hover:opacity-80"
              style={{ borderColor: "var(--border-medium)", color: "var(--text-secondary)" }}
            >
              <Home className="h-4 w-4" />
              返回首页
            </Link>
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase" style={{ color: "var(--text-tertiary)" }}>
                Learn
              </p>
              <h1 className="truncate text-xl font-semibold" style={{ color: "var(--text)" }}>
                {courseTitle}
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span
              className="hidden rounded-md border px-3 py-1.5 text-sm font-medium sm:inline-flex"
              style={{ borderColor: "var(--border)", background: "var(--surface-alt)", color: "var(--text-secondary)" }}
            >
              {progressLabel}
            </span>
            <button
              type="button"
              onClick={onOpenAside}
              aria-expanded={asideOpen}
              className="inline-flex items-center rounded-md px-4 py-2 text-sm font-medium text-white transition hover:opacity-90"
              style={{ background: "var(--text)" }}
            >
              打开学习辅助区
            </button>
          </div>
        </div>
      </header>

      <div
        className={clsx(
          "mx-auto flex max-w-[1760px] flex-col gap-4 px-4 py-4 transition-all duration-300 ease-out sm:px-6 lg:grid lg:items-start",
          asideOpen && isDesktop
            ? "lg:grid-cols-[320px_minmax(0,1fr)_360px]"
            : "lg:grid-cols-[320px_minmax(0,1fr)]"
        )}
      >
        <div className="lg:sticky lg:top-4">{outline}</div>
        <div className="min-w-0">{lessonStage}</div>
        {asideOpen && isDesktop ? (
          <div className="min-w-0 lg:sticky lg:top-4">
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
          <div
            className="relative z-10 max-h-[88vh] w-full overflow-y-auto rounded-t-lg p-4 shadow-2xl animate-[slideUp_0.3s_ease-out]"
            style={{ background: "var(--surface)" }}
          >
            {aside}
          </div>
          <style>{`
            @keyframes slideUp {
              from { transform: translateY(100%); }
              to { transform: translateY(0); }
            }
          `}</style>
        </div>
      ) : null}
    </div>
  );
}
