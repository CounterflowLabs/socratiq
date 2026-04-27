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
        fontSize: "14px",
      }
    : {
        background: "transparent",
        primaryColor: "#EEF4FF",
        primaryTextColor: "#0F172A",
        primaryBorderColor: "#93B4F8",
        secondaryColor: "#F0FDF4",
        secondaryTextColor: "#14532D",
        secondaryBorderColor: "#86EFAC",
        tertiaryColor: "#FFF7ED",
        tertiaryTextColor: "#7C2D12",
        tertiaryBorderColor: "#FCD34D",
        lineColor: "#94A3B8",
        textColor: "#0F172A",
        mainBkg: "#EEF4FF",
        nodeBorder: "#93B4F8",
        clusterBkg: "#FFFFFF",
        clusterBorder: "#CBD5E1",
        edgeLabelBackground: "#FFFFFF",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif",
        fontSize: "14px",
      };
}

export default function MermaidDiagram({
  content,
  title,
}: {
  content: string;
  title: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [failedSignature, setFailedSignature] = useState<string | null>(null);
  const theme = useResolvedTheme();
  const signature = `${theme}:${content}`;
  const error = failedSignature === signature;
  const flowSummary = useMemo(() => summarizeMermaidFlow(content), [content]);
  const themeVars = useMemo(() => getThemeVariables(theme), [theme]);

  // Only show aside for complex diagrams (has branches or many nodes)
  const showAside = flowSummary.branchCount > 0 || flowSummary.nodes.length > 6;

  useEffect(() => {
    let active = true;
    const id = `mermaid-${Math.random().toString(36).slice(2)}`;
    const container = ref.current;

    mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      flowchart: {
        curve: "basis",
        nodeSpacing: 48,
        rankSpacing: 48,
        padding: 16,
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
      <div
        className="my-4 rounded-lg border p-4"
        style={{
          borderColor: "var(--border)",
          background: "var(--surface-alt)",
        }}
      >
        <p className="text-xs font-medium mb-2" style={{ color: "var(--warning)" }}>
          图表渲染失败，显示原始语法：
        </p>
        <pre
          className="overflow-x-auto rounded-lg p-4 text-xs"
          style={{
            background: "var(--surface)",
            color: "var(--text-secondary)",
            border: "1px solid var(--border)",
          }}
        >
          {content}
        </pre>
      </div>
    );
  }

  // Compact inline summary for simple diagrams
  const inlineSummary = !showAside && flowSummary.nodes.length > 0 && (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-5 py-3 text-xs"
      style={{ borderColor: "var(--border)", color: "var(--text-tertiary)" }}
    >
      <span>{flowSummary.nodes.length} 个节点</span>
      <span>{flowSummary.edges.length} 个连接</span>
      <span>{flowSummary.isLinear ? "线性主线" : `${flowSummary.branchCount} 个分支`}</span>
      <span style={{ color: "var(--text-secondary)" }}>
        {flowSummary.direction ?? ""}
      </span>
    </div>
  );

  return (
    <section
      className="my-4 overflow-hidden rounded-lg border"
      style={{
        borderColor: "var(--border)",
        background: "var(--surface)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      {/* Header — compact */}
      <div
        className="flex items-center justify-between px-5 py-3 border-b"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="text-[11px] font-semibold uppercase"
            style={{ color: "var(--primary)" }}
          >
            Flowchart
          </span>
          {title ? (
            <>
              <span style={{ color: "var(--border-medium)" }}>·</span>
              <h3
                className="text-sm font-medium truncate"
                style={{ color: "var(--text)" }}
              >
                {title}
              </h3>
            </>
          ) : null}
        </div>
        {flowSummary.direction ? (
          <span
            className="rounded-full border px-2 py-0.5 text-[10px] font-medium"
            style={{
              borderColor: "var(--border)",
              color: "var(--text-tertiary)",
            }}
          >
            {flowSummary.direction}
          </span>
        ) : null}
      </div>

      {/* Diagram body */}
      {showAside ? (
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_200px] sm:p-5">
          <div
            className="overflow-x-auto rounded-lg border p-4"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface-alt)",
            }}
          >
            <div ref={ref} className="mermaid-canvas" />
          </div>
          <aside className="space-y-3">
            <div className="grid grid-cols-3 gap-1.5">
              {(
                [
                  ["节点", flowSummary.nodes.length],
                  ["连接", flowSummary.edges.length],
                  ["分支", flowSummary.branchCount],
                ] as const
              ).map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-md border px-2 py-1.5 text-center"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface-alt)",
                  }}
                >
                  <p
                    className="text-[10px]"
                    style={{ color: "var(--text-tertiary)" }}
                  >
                    {label}
                  </p>
                  <p
                    className="text-sm font-semibold"
                    style={{ color: "var(--text)" }}
                  >
                    {value}
                  </p>
                </div>
              ))}
            </div>
            <ol className="space-y-1">
              {flowSummary.nodes.slice(0, 8).map((node, index) => (
                <li key={node.id} className="flex items-start gap-2">
                  <span
                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-semibold mt-0.5"
                    style={{
                      background: "var(--primary-light)",
                      color: "var(--primary)",
                    }}
                  >
                    {index + 1}
                  </span>
                  <span
                    className="text-xs leading-4"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {node.label}
                  </span>
                </li>
              ))}
            </ol>
            <p
              className="border-t pt-2 text-[11px]"
              style={{
                borderColor: "var(--border)",
                color: "var(--text-tertiary)",
              }}
            >
              {flowSummary.isLinear ? "线性主线" : "含分支路径"}
            </p>
          </aside>
        </div>
      ) : (
        /* Simple diagram — full width, no aside */
        <div className="p-4 sm:p-5">
          <div
            className="overflow-x-auto rounded-lg p-4"
            style={{ background: "var(--surface-alt)" }}
          >
            <div ref={ref} className="mermaid-canvas" />
          </div>
        </div>
      )}

      {/* Compact inline stats for simple diagrams */}
      {inlineSummary}
    </section>
  );
}
