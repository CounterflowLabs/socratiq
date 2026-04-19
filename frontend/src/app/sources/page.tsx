"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { FileText, Filter, Loader, Play, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { listSources, type SourceResponse } from "@/lib/api";
import SourceDetailDrawer from "@/components/materials/source-detail-drawer";
import {
  deriveMaterialPresentation,
  isMaterialActive,
  matchesMaterialStatusFilter,
  type MaterialStatusFilter,
} from "@/lib/materials-state";

const STATUS_LABELS: Record<MaterialStatusFilter, string> = {
  all: "全部状态",
  ready: "已完成",
  processing: "处理中",
  error: "失败",
};

function TypeIcon({ type }: { type: string }) {
  if (type === "bilibili") return <Play className="w-5 h-5 text-blue-500" />;
  if (type === "youtube") return <Play className="w-5 h-5 text-red-500" />;
  return <FileText className="w-5 h-5 text-gray-400" />;
}

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<MaterialStatusFilter>("all");
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);

  const loadSources = useCallback(async (options?: { background?: boolean }) => {
    if (!options?.background) {
      setLoading(true);
    }

    try {
      const res = await listSources();
      setSources(res.items);
      setTotal(res.total);
    } catch (e) {
      console.error("Failed to load sources:", e);
    } finally {
      if (!options?.background) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    const hasActiveSource = sources.some((source) => isMaterialActive(source));
    if (!hasActiveSource) {
      return;
    }

    const interval = window.setInterval(() => {
      void loadSources({ background: true });
    }, 3000);

    return () => {
      window.clearInterval(interval);
    };
  }, [loadSources, sources]);

  useEffect(() => {
    if (selectedSourceId && !sources.some((source) => source.id === selectedSourceId)) {
      setSelectedSourceId(null);
    }
  }, [selectedSourceId, sources]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredSources = sources.filter((source) => {
    const title = (source.title || source.url || "").toLowerCase();
    const matchesQuery = normalizedQuery.length === 0 || title.includes(normalizedQuery);
    return matchesQuery && matchesMaterialStatusFilter(source, statusFilter);
  });
  const selectedSource = selectedSourceId
    ? sources.find((source) => source.id === selectedSourceId) ?? null
    : null;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-5xl px-4 pb-6 pt-14 sm:px-6 md:pt-6">
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">资料</h1>
            <p className="mt-1 text-sm text-gray-500">
              在这里查看已导入资料的处理进度、课程生成状态和下一步入口。
            </p>
          </div>
          <Link className="w-full sm:w-auto" href="/import">
            <Button className="w-full sm:w-auto" size="sm">
              <Plus className="w-3.5 h-3.5" /> 导入资料
            </Button>
          </Link>
        </div>

        <Card className="mb-6 p-4">
          <div className="flex flex-col gap-3 sm:flex-row">
            <label className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                className="h-10 w-full rounded-lg border border-gray-200 bg-white pl-9 pr-3 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索资料标题"
                value={query}
              />
            </label>

            <label className="relative sm:w-48">
              <span className="sr-only">状态筛选</span>
              <Filter className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <select
                aria-label="状态筛选"
                className="h-10 w-full appearance-none rounded-lg border border-gray-200 bg-white pl-9 pr-3 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                onChange={(event) => setStatusFilter(event.target.value as MaterialStatusFilter)}
                value={statusFilter}
              >
                {Object.entries(STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="mt-3 text-sm text-gray-500">
            {`当前显示 ${filteredSources.length} / ${total} 份资料`}
          </p>
        </Card>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader className="w-5 h-5 animate-spin mr-2" />
            <span className="text-sm">加载中...</span>
          </div>
        ) : sources.length === 0 ? (
          <Card className="p-10 text-center">
            <FileText className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <h3 className="text-base font-semibold text-gray-900 mb-2">还没有导入资料</h3>
            <p className="text-sm text-gray-500 mb-4">导入视频或 PDF 开始学习</p>
            <Link href="/import">
              <Button><Plus className="w-4 h-4" /> 导入第一份资料</Button>
            </Link>
          </Card>
        ) : filteredSources.length === 0 ? (
          <Card className="p-10 text-center">
            <h3 className="text-base font-semibold text-gray-900">没有匹配的资料</h3>
            <p className="mt-2 text-sm text-gray-500">试试更换关键词，或切换状态筛选。</p>
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {filteredSources.map((source) => {
              const presentation = deriveMaterialPresentation(source);

              return (
                <Card key={source.id} className="p-0 transition hover:border-blue-200 hover:shadow-sm">
                  <button
                    className="w-full bg-transparent p-4 text-left"
                    onClick={() => setSelectedSourceId(source.id)}
                    type="button"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-2xl bg-gray-100">
                        <TypeIcon type={source.type} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <h2 className="truncate text-sm font-semibold text-gray-900">
                            {source.title || source.url || "未命名资料"}
                          </h2>
                          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
                            {presentation.badge}
                          </span>
                        </div>
                        <p className="mt-2 line-clamp-2 text-sm text-gray-500">
                          {presentation.supportingText}
                        </p>
                        <div className="mt-3 flex items-center justify-between gap-3 text-xs text-gray-400">
                          <span>{new Date(source.updated_at).toLocaleDateString("zh-CN")}</span>
                          <span>{source.course_count} 门课程</span>
                        </div>
                      </div>
                    </div>
                  </button>
                </Card>
              );
            })}
          </div>
        )}

        <SourceDetailDrawer
          onClose={() => setSelectedSourceId(null)}
          open={selectedSource !== null}
          source={selectedSource}
        />
      </div>
    </div>
  );
}
