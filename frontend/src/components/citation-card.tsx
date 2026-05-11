"use client";

import { useState } from "react";
import { IcChevronDown, IcChevronRight, IcDoc, IcVideo } from "@/components/icons";
import type { Citation } from "@/lib/api";

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface CitationCardsProps {
  citations: Citation[];
}

export default function CitationCards({ citations }: CitationCardsProps) {
  const [expanded, setExpanded] = useState(false);

  if (citations.length === 0) return null;

  return (
    <div style={{ marginTop: 8 }}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="btn btn-ghost btn-sm"
        style={{ paddingLeft: 0, color: "var(--ink-3)" }}
      >
        {expanded ? <IcChevronDown size={12} /> : <IcChevronRight size={12} />}
        <span>{citations.length} 个来源引用</span>
      </button>

      {expanded ? (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
          {citations.map((cite, i) => {
            const isVideo =
              cite.source_type === "youtube" ||
              cite.source_type === "bilibili" ||
              cite.source_type === "video";

            return (
              <div
                key={cite.chunk_id}
                className="card-quiet"
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  padding: "8px 10px",
                  fontSize: 12,
                }}
              >
                <span
                  className="mono"
                  style={{ color: "var(--accent)", fontWeight: 500, flexShrink: 0 }}
                >
                  [{i + 1}]
                </span>
                <div style={{ flexShrink: 0, marginTop: 2, color: "var(--ink-3)" }}>
                  {isVideo ? <IcVideo size={14} /> : <IcDoc size={14} />}
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  {cite.source_title ? (
                    <div
                      style={{
                        fontWeight: 500,
                        color: "var(--ink-2)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {cite.source_title}
                    </div>
                  ) : null}
                  {isVideo && cite.start_time != null ? (
                    <div className="mono" style={{ color: "var(--ink-4)" }}>
                      {formatTimestamp(cite.start_time)}
                      {cite.end_time != null && ` – ${formatTimestamp(cite.end_time)}`}
                    </div>
                  ) : null}
                  {!isVideo && cite.page_start != null ? (
                    <div style={{ color: "var(--ink-4)" }}>第 {cite.page_start} 页</div>
                  ) : null}
                  <div
                    style={{
                      color: "var(--ink-3)",
                      marginTop: 2,
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {cite.text}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
