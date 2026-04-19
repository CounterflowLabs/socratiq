"use client";

import { clsx } from "clsx";

import type { SectionResponse } from "@/lib/api";

interface CourseOutlineProps {
  sections: SectionResponse[];
  currentSectionId: string | null;
  onSelectSection: (section: SectionResponse) => void;
}

export default function CourseOutline({
  sections,
  currentSectionId,
  onSelectSection,
}: CourseOutlineProps) {
  return (
    <aside className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <h2 className="text-lg font-semibold text-slate-900">课程目录</h2>
        <p className="mt-1 text-sm text-slate-500">
          {sections.length} 个章节，按学习路径逐节推进。
        </p>
      </div>

      <div className="max-h-[70vh] overflow-y-auto p-3">
        <div className="space-y-2">
          {sections.map((section, index) => {
            const isActive = section.id === currentSectionId;

            return (
              <button
                key={section.id}
                type="button"
                onClick={() => onSelectSection(section)}
                className={clsx(
                  "w-full rounded-2xl border px-4 py-3 text-left transition",
                  isActive
                    ? "border-blue-200 bg-blue-50 text-blue-900 shadow-sm"
                    : "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-300 hover:bg-white"
                )}
              >
                <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">
                  Section {index + 1}
                </p>
                <p className="mt-1 text-sm font-semibold">{section.title}</p>
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
