"use client";

import { useCallback, useSyncExternalStore } from "react";
import Link from "next/link";
import { CheckCircle2, Home, Loader2, Sparkles } from "lucide-react";
import { clsx } from "clsx";

import { SIDEBAR_DESKTOP_QUERY } from "@/app/layout";

interface RegenerationBanner {
  state: "running" | "ready" | "failed";
  stage?: string | null;
  newCourseId?: string;
  message?: string;
  onOpenNewCourse?: () => void;
  onDismiss?: () => void;
}

interface LearnShellProps {
  courseTitle: string;
  progressLabel: string;
  asideOpen: boolean;
  onOpenAside: () => void;
  onCloseAside: () => void;
  outline: React.ReactNode;
  lessonStage: React.ReactNode;
  aside: React.ReactNode;
  versionIndex?: number;
  parentCourseHref?: string | null;
  onRegenerate?: () => void;
  regenerationBanner?: RegenerationBanner | null;
}

const STAGE_LABELS_EN: Record<string, string> = {
  analyzing: "Analyzing content",
  planning: "Planning teaching assets",
  generating_lessons: "Generating lessons",
  generating_labs: "Generating labs",
  assembling: "Assembling course",
  source_done: "Source complete",
};

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
  versionIndex,
  parentCourseHref,
  onRegenerate,
  regenerationBanner,
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
              <div className="flex items-center gap-2">
                <p className="text-xs font-medium uppercase" style={{ color: "var(--text-tertiary)" }}>
                  Learn
                </p>
                {versionIndex && versionIndex > 1 ? (
                  <span
                    className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700"
                    title="This course was regenerated from an earlier version"
                  >
                    v{versionIndex}
                    {parentCourseHref ? (
                      <>
                        {" · "}
                        <Link
                          href={parentCourseHref}
                          className="underline-offset-2 hover:underline"
                        >
                          previous
                        </Link>
                      </>
                    ) : null}
                  </span>
                ) : null}
              </div>
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
            {onRegenerate ? (
              <button
                type="button"
                onClick={onRegenerate}
                disabled={regenerationBanner?.state === "running"}
                className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium transition hover:bg-violet-50 disabled:opacity-60"
                style={{ borderColor: "var(--border-medium)", color: "var(--text-secondary)" }}
              >
                <Sparkles className="h-4 w-4 text-violet-500" />
                Regenerate
              </button>
            ) : null}
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

      {regenerationBanner ? (
        <div
          className={clsx(
            "border-b px-4 py-3 text-sm sm:px-6",
            regenerationBanner.state === "running" && "bg-violet-50 text-violet-800 border-violet-200",
            regenerationBanner.state === "ready" && "bg-emerald-50 text-emerald-800 border-emerald-200",
            regenerationBanner.state === "failed" && "bg-red-50 text-red-800 border-red-200"
          )}
        >
          <div className="mx-auto flex max-w-[1760px] items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              {regenerationBanner.state === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : regenerationBanner.state === "ready" ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : null}
              <span>
                {regenerationBanner.state === "running"
                  ? `Regenerating · ${
                      STAGE_LABELS_EN[regenerationBanner.stage ?? ""] ??
                      regenerationBanner.stage ??
                      "in progress"
                    }`
                  : regenerationBanner.state === "ready"
                  ? "New version is ready."
                  : regenerationBanner.message ?? "Regeneration failed."}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {regenerationBanner.state === "ready" && regenerationBanner.onOpenNewCourse ? (
                <button
                  type="button"
                  onClick={regenerationBanner.onOpenNewCourse}
                  className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700"
                >
                  Open new version
                </button>
              ) : null}
              {regenerationBanner.state !== "running" && regenerationBanner.onDismiss ? (
                <button
                  type="button"
                  onClick={regenerationBanner.onDismiss}
                  className="rounded-md px-2 py-1 text-xs font-medium opacity-70 transition hover:opacity-100"
                >
                  Dismiss
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

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
