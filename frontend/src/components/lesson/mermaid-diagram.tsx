"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import mermaid from "mermaid";

import { useResolvedTheme } from "@/lib/theme";

import { summarizeMermaidFlow } from "./mermaid-flow";

function getThemeVariables(theme: string) {
  const isDark = theme === "dark";
  return isDark
    ? {
        background: "transparent",
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
        background: "transparent",
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
      };
}

export default function MermaidDiagram({ content, title }: { content: string; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failedSignature, setFailedSignature] = useState<string | null>(null);
  const theme = useResolvedTheme();
  const signature = `${theme}:${content}`;
  const error = failedSignature === signature;
  const flowSummary = useMemo(() => summarizeMermaidFlow(content), [content]);
  const hasFlowSummary = flowSummary.nodes.length > 0 || flowSummary.edges.length > 0;
  const themeVars = useMemo(() => getThemeVariables(theme), [theme]);

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
      themeVariables: themeVars,
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
  }, [content, signature, theme, themeVars]);

  if (error) {
    return (
      <div className="my-6 rounded-lg border p-4" style={{ borderColor: "var(--border)", background: "var(--surface-alt)" }}>
        <p className="text-xs font-medium mb-2" style={{ color: "var(--warning)" }}>图表渲染失败，显示原始语法：</p>
        <pre className="overflow-x-auto rounded-lg p-4 text-xs" style={{ background: "var(--surface)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}>
          {content}
        </pre>
      </div>
    );
  }

  return (
    <section
      className="my-6 overflow-hidden rounded-lg border"
      style={{ borderColor: "var(--border)", background: "var(--surface)", boxShadow: "var(--shadow)" }}
    >
      <div
        className="flex items-center justify-between border-b px-5 py-4"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase" style={{ color: "var(--primary)" }}>
            Flowchart
          </p>
          {title ? (
            <h3 className="mt-2 text-base font-semibold" style={{ color: "var(--text)" }}>
              {title}
            </h3>
          ) : null}
        </div>
        <span
          className="rounded-md border px-3 py-1 text-[11px] font-medium"
          style={{ borderColor: "var(--border)", background: "var(--surface-alt)", color: "var(--text-secondary)" }}
        >
          {flowSummary.direction ?? "Flow"}
        </span>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_240px] sm:p-6">
        <div
          className="overflow-x-auto rounded-lg border p-4"
          style={{ borderColor: "var(--border)", background: "var(--surface-alt)" }}
        >
          <div ref={ref} className="mermaid-canvas" />
        </div>
        {hasFlowSummary ? (
          <aside
            className="rounded-lg border p-4"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          >
            <p className="text-xs font-semibold" style={{ color: "var(--text)" }}>
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
                  className="rounded-md border px-2 py-2"
                  style={{ borderColor: "var(--border)", background: "var(--surface-alt)" }}
                >
                  <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                    {label}
                  </p>
                  <p className="mt-1 text-base font-semibold" style={{ color: "var(--text)" }}>
                    {value}
                  </p>
                </div>
              ))}
            </div>
            <ol className="mt-4 space-y-2">
              {flowSummary.nodes.slice(0, 6).map((node, index) => (
                <li key={node.id} className="flex gap-2">
                  <span
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[11px] font-semibold"
                    style={{ background: "var(--warning)", color: "var(--text)" }}
                  >
                    {index + 1}
                  </span>
                  <span className="text-xs leading-5" style={{ color: "var(--text-secondary)" }}>
                    {node.label}
                  </span>
                </li>
              ))}
            </ol>
            <p
              className="mt-4 border-t pt-3 text-xs"
              style={{ borderColor: "var(--border)", color: "var(--text-tertiary)" }}
            >
              {flowSummary.isLinear ? "线性主线" : "含分支路径"}
            </p>
          </aside>
        ) : null}
      </div>
    </section>
  );
}
