"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Play, FileText } from "lucide-react";
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
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors bg-transparent px-0 py-0.5"
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
        <span>{citations.length} 个来源引用</span>
      </button>

      {expanded && (
        <div className="mt-1.5 space-y-1.5">
          {citations.map((cite, i) => {
            const isVideo =
              cite.source_type === "youtube" ||
              cite.source_type === "bilibili" ||
              cite.source_type === "video";

            return (
              <div
                key={cite.chunk_id}
                className="flex items-start gap-2 rounded-lg bg-white border border-gray-200 px-2.5 py-2 text-xs"
              >
                <span className="font-medium text-blue-600 flex-shrink-0">
                  [{i + 1}]
                </span>
                <div className="flex-shrink-0 mt-0.5">
                  {isVideo ? (
                    <Play className="w-3.5 h-3.5 text-gray-400" />
                  ) : (
                    <FileText className="w-3.5 h-3.5 text-gray-400" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  {cite.source_title && (
                    <div className="font-medium text-gray-700 truncate">
                      {cite.source_title}
                    </div>
                  )}
                  {isVideo && cite.start_time != null && (
                    <div className="text-gray-400">
                      {formatTimestamp(cite.start_time)}
                      {cite.end_time != null &&
                        ` - ${formatTimestamp(cite.end_time)}`}
                    </div>
                  )}
                  {!isVideo && cite.page_start != null && (
                    <div className="text-gray-400">第 {cite.page_start} 页</div>
                  )}
                  <div className="text-gray-500 line-clamp-2 mt-0.5">
                    {cite.text}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
