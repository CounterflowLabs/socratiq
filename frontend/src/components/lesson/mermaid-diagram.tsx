"use client";
import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

import { useResolvedTheme } from "@/lib/theme";

export default function MermaidDiagram({ content, title }: { content: string; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failedSignature, setFailedSignature] = useState<string | null>(null);
  const theme = useResolvedTheme();
  const signature = `${theme}:${content}`;
  const error = failedSignature === signature;

  useEffect(() => {
    let active = true;
    const id = `mermaid-${Math.random().toString(36).slice(2)}`;
    const container = ref.current;

    mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      flowchart: {
        curve: "basis",
        nodeSpacing: 36,
        rankSpacing: 54,
        padding: 18,
        useMaxWidth: false,
      },
      themeVariables:
        theme === "dark"
          ? {
              background: "#020617",
              primaryColor: "#13203C",
              primaryTextColor: "#F8FAFC",
              primaryBorderColor: "#3B82F6",
              secondaryColor: "#111827",
              secondaryTextColor: "#E2E8F0",
              secondaryBorderColor: "#10B981",
              tertiaryColor: "#0F172A",
              tertiaryTextColor: "#F8FAFC",
              tertiaryBorderColor: "#F59E0B",
              lineColor: "#94A3B8",
              textColor: "#E2E8F0",
              mainBkg: "#0B1120",
              nodeBorder: "#475569",
              clusterBkg: "#0F172A",
              clusterBorder: "#334155",
              edgeLabelBackground: "#0F172A",
              fontFamily: "SF Mono, ui-monospace, Menlo, monospace",
              fontSize: "18px",
            }
          : {
              background: "#F8FAFC",
              primaryColor: "#F8FBFF",
              primaryTextColor: "#0F172A",
              primaryBorderColor: "#2563EB",
              secondaryColor: "#F0FDF4",
              secondaryTextColor: "#14532D",
              secondaryBorderColor: "#10B981",
              tertiaryColor: "#FFF7ED",
              tertiaryTextColor: "#7C2D12",
              tertiaryBorderColor: "#F59E0B",
              lineColor: "#475569",
              textColor: "#0F172A",
              mainBkg: "#EEF4FF",
              nodeBorder: "#94A3B8",
              clusterBkg: "#FFFFFF",
              clusterBorder: "#CBD5E1",
              edgeLabelBackground: "#FFFFFF",
              fontFamily: "SF Mono, ui-monospace, Menlo, monospace",
              fontSize: "18px",
            },
    });

    mermaid
      .render(id, content)
      .then(({ svg }) => {
        if (!active || !container) return;
        container.innerHTML = svg;
      })
      .catch(() => {
        if (active) setFailedSignature(signature);
      });

    return () => {
      active = false;
      if (container) {
        container.innerHTML = "";
      }
    };
  }, [content, signature, theme]);

  if (error) {
    return (
      <pre
        className={
          theme === "dark"
            ? "overflow-x-auto rounded-[24px] border border-slate-800 bg-slate-950/90 p-4 text-xs text-slate-300"
            : "overflow-x-auto rounded-[24px] border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600"
        }
      >
        {content}
      </pre>
    );
  }

  return (
    <section
      className={
        theme === "dark"
          ? "my-6 overflow-hidden rounded-[28px] border border-slate-800 bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.16),_transparent_34%),linear-gradient(180deg,_#111827_0%,_#020617_100%)] shadow-[0_24px_80px_rgba(2,6,23,0.35)]"
          : "my-6 overflow-hidden rounded-[28px] border border-slate-200 bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.14),_transparent_34%),linear-gradient(180deg,_#F8FBFF_0%,_#FFFFFF_100%)] shadow-[0_20px_60px_rgba(148,163,184,0.18)]"
      }
    >
      <div
        className={
          theme === "dark"
            ? "flex items-center justify-between border-b border-white/10 px-5 py-4"
            : "flex items-center justify-between border-b border-slate-200 px-5 py-4"
        }
      >
        <div className="min-w-0">
          <p
            className={
              theme === "dark"
                ? "text-[11px] font-semibold uppercase tracking-[0.28em] text-sky-300/80"
                : "text-[11px] font-semibold uppercase tracking-[0.28em] text-sky-600"
            }
          >
            Flowchart
          </p>
          {title ? (
            <h3
              className={
                theme === "dark"
                  ? "mt-2 text-base font-semibold text-slate-50"
                  : "mt-2 text-base font-semibold text-slate-900"
              }
            >
              {title}
            </h3>
          ) : null}
        </div>
        <span
          className={
            theme === "dark"
              ? "rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium text-slate-300"
              : "rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-[11px] font-medium text-slate-500"
          }
        >
          {theme === "dark" ? "Dark" : "Light"}
        </span>
      </div>
      <div className="p-4 sm:p-6">
        <div
          className={
            theme === "dark"
              ? "overflow-x-auto rounded-[24px] border border-white/10 bg-slate-950/30 p-4 backdrop-blur-sm"
              : "overflow-x-auto rounded-[24px] border border-slate-200 bg-white/80 p-4 backdrop-blur-sm"
          }
        >
          <div ref={ref} className="mermaid-canvas" />
        </div>
      </div>
    </section>
  );
}
