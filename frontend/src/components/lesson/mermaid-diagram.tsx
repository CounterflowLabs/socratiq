"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import mermaid from "mermaid";

import { useResolvedTheme } from "@/lib/theme";

import { isMermaidErrorSvg, normalizeMermaidSource } from "./mermaid-source";

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
  const normalizedContent = useMemo(() => normalizeMermaidSource(content), [content]);
  const signature = `${theme}:${normalizedContent}`;
  const error = failedSignature === signature;
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
        nodeSpacing: 48,
        rankSpacing: 48,
        padding: 16,
        useMaxWidth: false,
      },
      themeVariables: themeVars,
    });

    mermaid
      .parse(normalizedContent, { suppressErrors: false })
      .then(() => mermaid.render(id, normalizedContent))
      .then(({ svg }) => {
        if (!active || !container) return;
        if (isMermaidErrorSvg(svg)) {
          setFailedSignature(signature);
          return;
        }
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
  }, [normalizedContent, signature, theme, themeVars]);

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
      </div>

      {/* Diagram body */}
      <div className="p-4 sm:p-5">
        <div
          className="overflow-x-auto rounded-lg p-4"
          style={{ background: "var(--surface-alt)" }}
        >
          <div ref={ref} className="mermaid-canvas" />
        </div>
      </div>
    </section>
  );
}
