"use client";

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
}: CourseOutlineProps) {
  return (
    <aside className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_16px_48px_rgba(15,23,42,0.08)]">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase text-teal-700">
              Learning Map
            </p>
            <h2 className="mt-1 text-lg font-semibold text-slate-900">课程目录</h2>
          </div>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600">
            {sections.length} 模块
          </span>
        </div>
        <p className="mt-2 text-sm text-slate-500">
          {lessonWaypoints.length > 0
            ? `${sections.length} 个章节，${lessonWaypoints.length} 个知识片段。`
            : `${sections.length} 个章节，按学习路径逐节推进。`}
        </p>
      </div>

      <div className="max-h-[42vh] overflow-y-auto p-3 xl:max-h-[70vh]">
        <div className="space-y-2">
          {sections.map((section, index) => {
            const isActive = section.id === currentSectionId;

            return (
              <button
                key={section.id}
                type="button"
                onClick={() => onSelectSection(section)}
                className={clsx(
                  "w-full rounded-lg border px-4 py-3 text-left transition",
                  isActive
                    ? "border-teal-300 bg-teal-50 text-teal-950 shadow-sm"
                    : "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-300 hover:bg-white"
                )}
              >
                <p className="text-xs font-medium uppercase text-slate-400">
                  Section {index + 1}
                </p>
                <p className="mt-1 text-sm font-semibold">{section.title}</p>
              </button>
            );
          })}
        </div>

        {lessonWaypoints.length > 0 ? (
          <nav aria-label="本节脉络" className="mt-4 border-t border-slate-200 pt-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold text-slate-900">本节脉络</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {lessonWaypoints.length} 个知识片段
                </p>
              </div>
              <span className="h-2 w-2 rounded-full bg-amber-400" />
            </div>
            <div className="space-y-2">
              {lessonWaypoints.map((waypoint, index) => (
                <button
                  key={waypoint.id}
                  type="button"
                  onClick={() => onSelectWaypoint?.(waypoint.id)}
                  className="group w-full rounded-lg border border-slate-200 bg-white px-3 py-3 text-left transition hover:border-amber-300 hover:bg-amber-50/70"
                >
                  <div className="flex items-start gap-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-950 text-xs font-semibold text-white">
                      {index + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold leading-5 text-slate-800 group-hover:text-amber-900">
                        {waypoint.title}
                      </span>
                      <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        {typeof waypoint.timestamp === "number" && waypoint.timestamp > 0 ? (
                          <span aria-hidden="true">{formatTimestamp(waypoint.timestamp)}</span>
                        ) : null}
                        {(waypoint.concepts ?? []).slice(0, 2).map((concept) => (
                          <span
                            key={`${waypoint.id}-${concept}`}
                            className="rounded-md bg-slate-100 px-1.5 py-0.5 text-slate-600"
                          >
                            {concept}
                          </span>
                        ))}
                      </span>
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </nav>
        ) : null}
      </div>
    </aside>
  );
}
