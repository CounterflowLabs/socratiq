"use client";

import { useCallback, useSyncExternalStore } from "react";
import Link from "next/link";

import {
  IcArrowLeft,
  IcCheckCircle,
  IcLoader,
  IcPanelLeftOpen,
  IcSparkle,
} from "@/components/icons";
import { SIDEBAR_DESKTOP_QUERY } from "@/app/layout-inner";

interface RegenerationBanner {
  state: "running" | "ready" | "failed";
  stage?: string | null;
  current?: number | null;
  total?: number | null;
  newCourseId?: string;
  message?: string;
  onOpenNewCourse?: () => void;
  onDismiss?: () => void;
}

const STAGE_PERCENT_RANGES: Record<string, [number, number]> = {
  pending: [0, 5],
  analyzing: [5, 25],
  generating_lessons: [25, 70],
  generating_labs: [70, 90],
  assembling: [90, 100],
};

function computeRegenPercent(banner: RegenerationBanner): number {
  if (banner.state === "ready") return 100;
  if (banner.state === "failed") return 0;
  const stage = banner.stage ?? "pending";
  const [base, ceiling] = STAGE_PERCENT_RANGES[stage] ?? [0, 100];
  const { current, total } = banner;
  if (typeof current === "number" && typeof total === "number" && total > 0) {
    return Math.round(base + (current / total) * (ceiling - base));
  }
  return base;
}

interface LearnShellProps {
  courseTitle: string;
  progressLabel: string;
  asideOpen: boolean;
  onOpenAside: () => void;
  onCloseAside: () => void;
  outlineOpen?: boolean;
  onOpenOutline?: () => void;
  outline: React.ReactNode;
  lessonStage: React.ReactNode;
  aside: React.ReactNode;
  backHref?: string;
  versionIndex?: number;
  parentCourseHref?: string | null;
  onRegenerate?: () => void;
  regenerationBanner?: RegenerationBanner | null;
}

const STAGE_LABELS_ZH: Record<string, string> = {
  analyzing: "分析内容",
  planning: "规划教学资产",
  generating_lessons: "生成课文",
  generating_labs: "生成 Lab",
  assembling: "组装课程",
  source_done: "资料处理完成",
};

function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      if (typeof window.matchMedia !== "function") return () => {};
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    [query],
  );
  const getSnapshot = useCallback(() => {
    if (typeof window.matchMedia !== "function") return false;
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
  backHref = "/",
  outlineOpen = true,
  onOpenOutline,
  versionIndex,
  parentCourseHref,
  onRegenerate,
  regenerationBanner,
}: LearnShellProps) {
  const isDesktop = useMediaQuery(SIDEBAR_DESKTOP_QUERY);

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          background: "var(--surface)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div
          style={{
            maxWidth: 1760,
            margin: "0 auto",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            padding: "10px 24px",
          }}
        >
          <div style={{ display: "flex", minWidth: 0, alignItems: "center", gap: 12 }}>
            <Link
              href={backHref}
              aria-label="返回首页"
              className="btn btn-ghost btn-icon btn-sm"
            >
              <IcArrowLeft size={14} />
            </Link>
            {!outlineOpen && onOpenOutline ? (
              <button
                type="button"
                onClick={onOpenOutline}
                aria-label="展开课程目录"
                className="btn btn-ghost btn-icon btn-sm"
              >
                <IcPanelLeftOpen size={14} />
              </button>
            ) : null}
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="eyebrow">Learn</span>
                {versionIndex && versionIndex > 1 ? (
                  <span className="chip chip-accent" title="该课程是从先前版本重新生成的">
                    第 {versionIndex} 版
                    {parentCourseHref ? (
                      <>
                        {" · "}
                        <Link
                          href={parentCourseHref}
                          style={{ textDecoration: "underline", color: "inherit" }}
                        >
                          上一版
                        </Link>
                      </>
                    ) : null}
                  </span>
                ) : null}
              </div>
              <h1
                className="serif"
                style={{
                  fontSize: 20,
                  fontWeight: 500,
                  margin: "2px 0 0",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {courseTitle}
              </h1>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="chip chip-mono" style={{ display: isDesktop ? "inline-flex" : "none" }}>
              {progressLabel}
            </span>
            {onRegenerate ? (
              <button
                type="button"
                onClick={onRegenerate}
                disabled={regenerationBanner?.state === "running"}
                className="btn btn-outline btn-sm"
              >
                <IcSparkle size={12} />
                <span>重新生成</span>
              </button>
            ) : null}
            <button
              type="button"
              onClick={onOpenAside}
              aria-expanded={asideOpen}
              className="btn btn-primary btn-sm"
            >
              打开学习辅助区
            </button>
          </div>
        </div>
      </header>

      {regenerationBanner ? (
        <div
          className="card-quiet"
          style={{
            margin: 0,
            borderRadius: 0,
            borderLeft: 0,
            borderRight: 0,
            padding: "10px 24px",
            background:
              regenerationBanner.state === "running"
                ? "var(--accent-soft)"
                : regenerationBanner.state === "ready"
                  ? "var(--sage-soft)"
                  : "var(--error-soft)",
            color:
              regenerationBanner.state === "running"
                ? "var(--accent-ink)"
                : regenerationBanner.state === "ready"
                  ? "var(--sage-ink)"
                  : "var(--error)",
            borderTop: "none",
            fontSize: 13,
          }}
        >
          <div
            style={{
              maxWidth: 1760,
              margin: "0 auto",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {regenerationBanner.state === "running" ? (
                  <IcLoader size={14} className="spin" />
                ) : regenerationBanner.state === "ready" ? (
                  <IcCheckCircle size={14} />
                ) : null}
                <span>
                  {regenerationBanner.state === "running" ? (
                    <>
                      重新生成中 ·{" "}
                      {STAGE_LABELS_ZH[regenerationBanner.stage ?? ""] ??
                        regenerationBanner.stage ??
                        "进行中"}
                      {typeof regenerationBanner.current === "number" &&
                      typeof regenerationBanner.total === "number" &&
                      regenerationBanner.total > 1
                        ? ` (${regenerationBanner.current}/${regenerationBanner.total})`
                        : ""}
                      {" · "}
                      {computeRegenPercent(regenerationBanner)}%
                    </>
                  ) : regenerationBanner.state === "ready" ? (
                    "新版本已生成完毕。"
                  ) : (
                    regenerationBanner.message ?? "重新生成失败。"
                  )}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {regenerationBanner.state === "ready" && regenerationBanner.onOpenNewCourse ? (
                  <button
                    type="button"
                    onClick={regenerationBanner.onOpenNewCourse}
                    className="btn btn-accent btn-sm"
                  >
                    打开新版本
                  </button>
                ) : null}
                {regenerationBanner.state !== "running" && regenerationBanner.onDismiss ? (
                  <button
                    type="button"
                    onClick={regenerationBanner.onDismiss}
                    className="btn btn-ghost btn-sm"
                  >
                    关闭
                  </button>
                ) : null}
              </div>
            </div>
            {regenerationBanner.state === "running" ? (
              <div
                style={{
                  height: 4,
                  borderRadius: 100,
                  background: "rgba(201, 100, 66, 0.18)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${computeRegenPercent(regenerationBanner)}%`,
                    background: "var(--accent)",
                    borderRadius: 100,
                    transition: "width 0.4s ease",
                  }}
                />
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div
        style={{
          maxWidth: 1760,
          margin: "0 auto",
          padding: "16px 24px 80px",
          display: isDesktop ? "grid" : "flex",
          flexDirection: isDesktop ? undefined : "column",
          gridTemplateColumns: isDesktop
            ? outlineOpen && asideOpen
              ? "260px minmax(0,1fr) 380px"
              : outlineOpen
                ? "260px minmax(0,1fr)"
                : asideOpen
                  ? "minmax(0,1fr) 380px"
                  : "minmax(0,1fr)"
            : undefined,
          gap: 20,
          alignItems: "flex-start",
        }}
      >
        {outlineOpen ? (
          <div style={{ position: isDesktop ? "sticky" : "static", top: 76 }}>{outline}</div>
        ) : null}
        <div style={{ minWidth: 0 }}>{lessonStage}</div>
        {asideOpen && isDesktop ? (
          <div style={{ minWidth: 0, position: "sticky", top: 76 }}>{aside}</div>
        ) : null}
      </div>

      {asideOpen && !isDesktop ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="学习辅助区"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            display: "flex",
            alignItems: "flex-end",
            background: "rgba(26, 22, 17, 0.45)",
          }}
        >
          <button
            type="button"
            aria-label="关闭学习辅助区遮罩"
            onClick={onCloseAside}
            style={{
              position: "absolute",
              inset: 0,
              background: "transparent",
              border: "none",
            }}
          />
          <div
            style={{
              position: "relative",
              zIndex: 10,
              maxHeight: "88vh",
              width: "100%",
              overflowY: "auto",
              padding: 16,
              borderTopLeftRadius: 12,
              borderTopRightRadius: 12,
              background: "var(--surface)",
              boxShadow: "var(--shadow-lg)",
              animation: "slideUp 0.3s ease-out",
            }}
          >
            {aside}
          </div>
          <style>{`@keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }`}</style>
        </div>
      ) : null}
    </div>
  );
}
