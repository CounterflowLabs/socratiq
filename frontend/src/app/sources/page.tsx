"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Play, FileText, Loader, AlertCircle, CheckCircle, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { listSources, cancelSource, retrySource, type SourceResponse } from "@/lib/api";

const STATUS_CONFIG: Record<string, { label: string; color: string; bgColor: string }> = {
  pending: { label: "排队中", color: "text-blue-700", bgColor: "bg-blue-50" },
  extracting: { label: "提取中", color: "text-blue-700", bgColor: "bg-blue-50" },
  analyzing: { label: "分析中", color: "text-blue-700", bgColor: "bg-blue-50" },
  storing: { label: "存储中", color: "text-blue-700", bgColor: "bg-blue-50" },
  embedding: { label: "向量化", color: "text-blue-700", bgColor: "bg-blue-50" },
  waiting_donor: { label: "复用中", color: "text-purple-700", bgColor: "bg-purple-50" },
  generating_lessons: { label: "生成课文", color: "text-blue-700", bgColor: "bg-blue-50" },
  generating_labs: { label: "生成 Lab", color: "text-blue-700", bgColor: "bg-blue-50" },
  assembling_course: { label: "组装课程", color: "text-blue-700", bgColor: "bg-blue-50" },
  ready: { label: "已完成", color: "text-green-700", bgColor: "bg-green-50" },
  error: { label: "失败", color: "text-red-700", bgColor: "bg-red-50" },
};

function TypeIcon({ type }: { type: string }) {
  if (type === "bilibili") return <Play className="w-5 h-5 text-blue-500" />;
  if (type === "youtube") return <Play className="w-5 h-5 text-red-500" />;
  return <FileText className="w-5 h-5 text-gray-400" />;
}

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || { label: status, color: "text-gray-700", bgColor: "bg-gray-50" };
  const isProcessing = !["ready", "error"].includes(status);
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${config.color} ${config.bgColor}`}>
      {isProcessing && <Loader className="w-3 h-3 animate-spin" />}
      {status === "ready" && <CheckCircle className="w-3 h-3" />}
      {status === "error" && <AlertCircle className="w-3 h-3" />}
      {config.label}
    </span>
  );
}

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    loadSources();
  }, []);

  // Auto-refresh while any source is still processing
  useEffect(() => {
    const hasActive = sources.some((s) => !["ready", "error"].includes(s.status));
    if (!hasActive) return;
    const interval = setInterval(() => {
      listSources().then((res) => { setSources(res.items); setTotal(res.total); }).catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, [sources]);

  async function loadSources() {
    setLoading(true);
    try {
      const res = await listSources();
      setSources(res.items);
      setTotal(res.total);
    } catch (e) {
      console.error("Failed to load sources:", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-14 md:pt-6 pb-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900">导入历史</h1>
            <p className="text-sm text-gray-500 mt-1">
              {total > 0 ? `共 ${total} 个资源` : "暂无导入的资源"}
            </p>
          </div>
          <Link href="/import">
            <Button size="sm">
              <Plus className="w-3.5 h-3.5" /> 导入新资料
            </Button>
          </Link>
        </div>

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
        ) : (
          <div className="space-y-3">
            {sources.map((source) => (
              <Card key={source.id} className="p-4">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-gray-50 flex items-center justify-center flex-shrink-0">
                    <TypeIcon type={source.type} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 truncate">
                      {source.title || source.url || "未命名资源"}
                    </h3>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusBadge status={source.status} />
                      <span className="text-xs text-gray-400">
                        {new Date(source.created_at).toLocaleDateString("zh-CN")}
                      </span>
                    </div>
                    {source.status === "error" && source.metadata_?.error && (
                      <p className="text-xs text-red-500 mt-0.5 truncate">
                        {String(source.metadata_.error)}
                      </p>
                    )}
                  </div>
                  <div className="flex-shrink-0 flex gap-2">
                    {source.status === "error" && (
                      <Button size="sm" variant="ghost" onClick={async () => {
                        try { await retrySource(source.id); loadSources(); } catch {}
                      }}>
                        <RefreshCw className="w-3.5 h-3.5" /> 重试
                      </Button>
                    )}
                    {!["ready", "error"].includes(source.status) && (
                      <Button size="sm" variant="ghost" onClick={async () => {
                        try {
                          await cancelSource(source.id);
                        } catch (e) {
                          console.error("Cancel failed:", e);
                        }
                        loadSources();
                      }}>
                        <X className="w-3.5 h-3.5" /> 取消
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
