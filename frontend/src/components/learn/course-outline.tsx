"use client";

import { useState } from "react";

import { IcExercise, IcPanelLeftClose } from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Ornament } from "@/components/ui/ornament";

import type { SectionResponse } from "@/lib/api";

export interface LessonWaypoint {
  id: string;
  title: string;
  timestamp?: number | null;
  concepts?: string[];
}

interface CourseOutlineProps {
  sections: SectionResponse[];
  currentSectionId: string | null;
  onSelectSection: (section: SectionResponse) => void;
  lessonWaypoints?: LessonWaypoint[];
  onSelectWaypoint?: (waypointId: string) => void;
  onCollapse?: () => void;
  // Manual-override hooks. When omitted, the merge/split affordances are
  // hidden — keeps read-only callers (e.g. preview, embedded outlines)
  // visually unchanged.
  onMergeWithNext?: (section: SectionResponse) => Promise<void> | void;
  onSplit?: (section: SectionResponse) => Promise<void> | void;
}

function formatTimestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.floor(seconds % 60);
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

export default function CourseOutline({
  sections,
  currentSectionId,
  onSelectSection,
  lessonWaypoints = [],
  onSelectWaypoint,
  onCollapse,
  onMergeWithNext,
  onSplit,
}: CourseOutlineProps) {
  // Per-section "operation in progress" guard so a slow merge call doesn't
  // let the user double-fire and end up with confusing partial state.
  const [busySectionId, setBusySectionId] = useState<string | null>(null);

  const handleMerge = async (section: SectionResponse) => {
    if (!onMergeWithNext || busySectionId) return;
    setBusySectionId(section.id);
    try {
      await onMergeWithNext(section);
    } finally {
      setBusySectionId(null);
    }
  };

  const handleSplit = async (section: SectionResponse) => {
    if (!onSplit || busySectionId) return;
    setBusySectionId(section.id);
    try {
      await onSplit(section);
    } finally {
      setBusySectionId(null);
    }
  };

  const overridesEnabled = Boolean(onMergeWithNext || onSplit);

  return (
    <aside
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-lg)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "14px 16px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
          <div>
            <Eyebrow>Learning map</Eyebrow>
            <h2
              className="serif"
              style={{ fontSize: 16, fontWeight: 500, margin: "4px 0 0", color: "var(--ink)" }}
            >
              课程目录
            </h2>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span className="chip chip-mono">{sections.length} 模块</span>
            {onCollapse ? (
              <button
                type="button"
                onClick={onCollapse}
                aria-label="收起课程目录"
                className="btn btn-ghost btn-icon btn-sm"
                style={{ color: "var(--ink-3)" }}
              >
                <IcPanelLeftClose size={14} />
              </button>
            ) : null}
          </div>
        </div>
        <p style={{ marginTop: 6, fontSize: 11, color: "var(--ink-3)" }}>
          {lessonWaypoints.length > 0
            ? `${sections.length} 个章节 · ${lessonWaypoints.length} 个知识片段`
            : `${sections.length} 个章节`}
        </p>
      </div>

      <div
        style={{
          maxHeight: "70vh",
          overflowY: "auto",
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {sections.map((section, index) => {
          const isActive = section.id === currentSectionId;
          const isLast = index === sections.length - 1;
          const isBusy = busySectionId === section.id;
          return (
            <div
              key={section.id}
              className="outline-row"
              style={{
                position: "relative",
                display: "flex",
                alignItems: "stretch",
                background: isActive ? "var(--surface-2)" : "transparent",
                borderRadius: 6,
                opacity: isBusy ? 0.5 : 1,
                pointerEvents: isBusy ? "none" : undefined,
              }}
            >
              <button
                type="button"
                onClick={() => onSelectSection(section)}
                className="nav-item"
                style={{
                  flex: 1,
                  fontSize: 13,
                  paddingLeft: 16,
                  paddingRight: overridesEnabled ? 56 : undefined,
                  position: "relative",
                  color: isActive ? "var(--ink)" : "var(--ink-2)",
                  fontWeight: isActive ? 500 : 400,
                  background: "transparent",
                  alignItems: "flex-start",
                  gap: 10,
                  whiteSpace: "normal",
                }}
              >
                {isActive ? (
                  <span
                    style={{
                      position: "absolute",
                      left: 4,
                      top: 12,
                      bottom: 12,
                      width: 2,
                      background: "var(--accent)",
                      borderRadius: 1,
                    }}
                  />
                ) : null}
                <span
                  className="mono num"
                  style={{ fontSize: 11, color: "var(--ink-4)", marginTop: 2 }}
                >
                  L{String(index + 1).padStart(2, "0")}
                </span>
                <span
                  style={{
                    display: "block",
                    fontFamily: "var(--serif)",
                    lineHeight: 1.35,
                  }}
                >
                  {section.title}
                </span>
              </button>
              {overridesEnabled ? (
                <div
                  className="outline-row-actions"
                  style={{
                    position: "absolute",
                    right: 6,
                    top: "50%",
                    transform: "translateY(-50%)",
                    display: "flex",
                    gap: 2,
                  }}
                >
                  {onSplit ? (
                    <button
                      type="button"
                      title="在此处拆分章节"
                      aria-label="拆分章节"
                      onClick={() => handleSplit(section)}
                      className="btn btn-ghost btn-icon btn-sm"
                      style={{ color: "var(--ink-3)" }}
                    >
                      ⫶
                    </button>
                  ) : null}
                  {onMergeWithNext && !isLast ? (
                    <button
                      type="button"
                      title="并入下一节"
                      aria-label="并入下一节"
                      onClick={() => handleMerge(section)}
                      className="btn btn-ghost btn-icon btn-sm"
                      style={{ color: "var(--ink-3)" }}
                    >
                      ⤓
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}

        {lessonWaypoints.length > 0 ? (
          <nav aria-label="本节脉络" style={{ marginTop: 4 }}>
            <Ornament width={32} />
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "0 4px",
                marginBottom: 6,
              }}
            >
              <Eyebrow>本节脉络</Eyebrow>
              <span style={{ fontSize: 10, color: "var(--ink-4)" }}>
                {lessonWaypoints.length} 片段
              </span>
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 2 }}>
              {lessonWaypoints.map((waypoint, index) => (
                <li key={waypoint.id}>
                  <button
                    type="button"
                    onClick={() => onSelectWaypoint?.(waypoint.id)}
                    className="nav-item"
                    style={{
                      fontSize: 12,
                      padding: "6px 10px",
                      gap: 8,
                      alignItems: "flex-start",
                    }}
                  >
                    <span
                      className="mono num"
                      style={{
                        fontSize: 10,
                        color: "var(--ink-4)",
                        marginTop: 2,
                        minWidth: 18,
                        textAlign: "right",
                      }}
                    >
                      {index + 1}
                    </span>
                    <span
                      style={{
                        flex: 1,
                        lineHeight: 1.4,
                        color: "var(--ink-2)",
                        whiteSpace: "normal",
                      }}
                    >
                      {waypoint.title}
                    </span>
                    {typeof waypoint.timestamp === "number" && waypoint.timestamp > 0 ? (
                      <span
                        aria-hidden="true"
                        className="mono num"
                        style={{ fontSize: 10, color: "var(--ink-4)", marginTop: 2 }}
                      >
                        {formatTimestamp(waypoint.timestamp)}
                      </span>
                    ) : null}
                    {waypoint.concepts && waypoint.concepts.length > 0 ? (
                      <IcExercise size={12} style={{ color: "var(--ink-4)", marginTop: 2 }} />
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
      </div>
    </aside>
  );
}
