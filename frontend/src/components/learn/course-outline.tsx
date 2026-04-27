"use client";

import { PanelLeftClose } from "lucide-react";
import { clsx } from "clsx";

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
}: CourseOutlineProps) {
  return (
    <aside className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_16px_48px_rgba(15,23,42,0.08)]">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-teal-700">
              Learning Map
            </p>
            <h2 className="mt-0.5 text-base font-semibold text-slate-900">课程目录</h2>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600">
              {sections.length} 模块
            </span>
            {onCollapse ? (
              <button
                type="button"
                onClick={onCollapse}
                aria-label="收起课程目录"
                className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
              >
                <PanelLeftClose className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">
          {lessonWaypoints.length > 0
            ? `${sections.length} 个章节 · ${lessonWaypoints.length} 个知识片段`
            : `${sections.length} 个章节`}
        </p>
      </div>

      <div className="max-h-[60vh] overflow-y-auto p-2 lg:max-h-[70vh]">
        <div className="space-y-1">
          {sections.map((section, index) => {
            const isActive = section.id === currentSectionId;

            return (
              <button
                key={section.id}
                type="button"
                onClick={() => onSelectSection(section)}
                className={clsx(
                  "w-full rounded-md border px-3 py-2 text-left transition",
                  isActive
                    ? "border-teal-300 bg-teal-50 text-teal-950"
                    : "border-transparent text-slate-700 hover:border-slate-200 hover:bg-slate-50"
                )}
              >
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                  Section {index + 1}
                </p>
                <p className="mt-0.5 text-[13px] font-semibold leading-snug">
                  {section.title}
                </p>
              </button>
            );
          })}
        </div>

        {lessonWaypoints.length > 0 ? (
          <nav aria-label="本节脉络" className="mt-3 border-t border-slate-200 pt-3">
            <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                本节脉络
              </p>
              <span className="text-[10px] text-slate-400">
                {lessonWaypoints.length} 片段
              </span>
            </div>
            <ul className="space-y-px">
              {lessonWaypoints.map((waypoint, index) => (
                <li key={waypoint.id}>
                  <button
                    type="button"
                    onClick={() => onSelectWaypoint?.(waypoint.id)}
                    className="group flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-amber-50/70"
                  >
                    <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-medium tabular-nums text-slate-400 group-hover:text-amber-700">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] leading-snug text-slate-700 group-hover:text-amber-900 line-clamp-2">
                        {waypoint.title}
                      </span>
                    </span>
                    {typeof waypoint.timestamp === "number" && waypoint.timestamp > 0 ? (
                      <span
                        aria-hidden="true"
                        className="mt-0.5 shrink-0 text-[10px] tabular-nums text-slate-400"
                      >
                        {formatTimestamp(waypoint.timestamp)}
                      </span>
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
