"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import mermaid from "mermaid";

import { useResolvedTheme } from "@/lib/theme";

import { summarizeMermaidFlow } from "./mermaid-flow";

export default function MermaidDiagram({ content, title }: { content: string; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failedSignature, setFailedSignature] = useState<string | null>(null);
  const theme = useResolvedTheme();
  const signature = `${theme}:${content}`;
  const error = failedSignature === signature;
  const flowSummary = useMemo(() => summarizeMermaidFlow(content), [content]);
  const hasFlowSummary = flowSummary.nodes.length > 0 || flowSummary.edges.length > 0;

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
            ? "overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/90 p-4 text-xs text-slate-300"
            : "overflow-x-auto rounded-lg border border-[#dbe3ef] bg-[#f8fafc] p-4 text-xs text-[#475569]"
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
          ? "my-6 overflow-hidden rounded-lg border border-slate-800 bg-slate-950 shadow-[0_24px_80px_rgba(2,6,23,0.35)]"
          : "my-6 overflow-hidden rounded-lg border border-[#dbe3ef] bg-[#ffffff] shadow-[0_20px_60px_rgba(148,163,184,0.18)]"
      }
    >
      <div
        className={
          theme === "dark"
            ? "flex items-center justify-between border-b border-white/10 px-5 py-4"
            : "flex items-center justify-between border-b border-[#dbe3ef] px-5 py-4"
        }
      >
        <div className="min-w-0">
          <p
            className={
              theme === "dark"
                ? "text-[11px] font-semibold uppercase text-cyan-300/80"
                : "text-[11px] font-semibold uppercase text-[#0e7490]"
            }
          >
            Flowchart
          </p>
          {title ? (
            <h3
              className={
                theme === "dark"
                  ? "mt-2 text-base font-semibold text-slate-50"
                  : "mt-2 text-base font-semibold text-[#0f172a]"
              }
            >
              {title}
            </h3>
          ) : null}
        </div>
        <span
          className={
            theme === "dark"
              ? "rounded-md border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium text-slate-300"
              : "rounded-md border border-[#dbe3ef] bg-[#f8fafc] px-3 py-1 text-[11px] font-medium text-[#475569]"
          }
        >
          {flowSummary.direction ?? (theme === "dark" ? "Dark" : "Light")}
        </span>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_240px] sm:p-6">
        <div
          className={
            theme === "dark"
              ? "overflow-x-auto rounded-lg border border-white/10 bg-slate-900/70 p-4"
              : "overflow-x-auto rounded-lg border border-[#dbe3ef] bg-[#f8fafc] p-4"
          }
        >
          <div ref={ref} className="mermaid-canvas" />
        </div>
        {hasFlowSummary ? (
          <aside
            className={
              theme === "dark"
                ? "rounded-lg border border-white/10 bg-slate-900/80 p-4"
                : "rounded-lg border border-[#dbe3ef] bg-[#ffffff] p-4"
            }
          >
            <p
              className={
                theme === "dark"
                  ? "text-xs font-semibold text-slate-100"
                  : "text-xs font-semibold text-[#0f172a]"
              }
            >
              流程摘要
            </p>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {[
                ["节点", flowSummary.nodes.length],
                ["连接", flowSummary.edges.length],
                ["分支", flowSummary.branchCount],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className={
                    theme === "dark"
                      ? "rounded-md border border-white/10 bg-white/5 px-2 py-2"
                      : "rounded-md border border-[#dbe3ef] bg-[#f8fafc] px-2 py-2"
                  }
                >
                  <p className={theme === "dark" ? "text-[11px] text-slate-500" : "text-[11px] text-[#64748b]"}>
                    {label}
                  </p>
                  <p
                    className={
                      theme === "dark"
                        ? "mt-1 text-base font-semibold text-slate-50"
                        : "mt-1 text-base font-semibold text-[#0f172a]"
                    }
                  >
                    {value}
                  </p>
                </div>
              ))}
            </div>
            <ol className="mt-4 space-y-2">
              {flowSummary.nodes.slice(0, 6).map((node, index) => (
                <li key={node.id} className="flex gap-2">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-amber-400 text-[11px] font-semibold text-slate-900">
                    {index + 1}
                  </span>
                  <span
                    className={
                      theme === "dark"
                        ? "text-xs leading-5 text-slate-300"
                        : "text-xs leading-5 text-[#475569]"
                    }
                  >
                    {node.label}
                  </span>
                </li>
              ))}
            </ol>
            <p
              className={
                theme === "dark"
                  ? "mt-4 border-t border-white/10 pt-3 text-xs text-slate-400"
                  : "mt-4 border-t border-[#dbe3ef] pt-3 text-xs text-[#64748b]"
              }
            >
              {flowSummary.isLinear ? "线性主线" : "含分支路径"}
            </p>
          </aside>
        ) : null}
      </div>
    </section>
  );
}
