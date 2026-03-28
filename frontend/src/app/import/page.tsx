"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { Brain, Sparkles, Eye, Target, FileText, Upload, Loader, Play, X, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { clsx } from "clsx";
import { createSourceFromURL, createSourceFromFile, DuplicateSourceError } from "@/lib/api";
import { useSourcesStore, useTasksStore } from "@/lib/stores";

const goals = [
  { id: "overview", label: "快速了解大意", icon: Eye, desc: "用最短时间抓住核心思想" },
  { id: "master", label: "系统掌握核心概念", icon: Brain, desc: "深入理解每个知识点" },
  { id: "apply", label: "实战应用", icon: Target, desc: "做项目、写代码、能上手" },
];


export default function ImportPage() {
  const router = useRouter();
  const addSource = useSourcesStore((s) => s.addSource);
  const addTask = useTasksStore((s) => s.addTask);
  const [url, setUrl] = useState("");
  const [goal, setGoal] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sourceType, setSourceType] = useState<"bilibili" | "youtube" | "pdf">("bilibili");
  const [dragOver, setDragOver] = useState(false);
  const [pdfName, setPdfName] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const canSubmit = goal && (sourceType === "bilibili" || sourceType === "youtube" ? url.trim() : pdfName);

  const handleImport = async () => {
    if (!canSubmit) return;
    setLoading(true);
    setErrorMsg(null);

    try {
      let source;
      if (sourceType === "bilibili" || sourceType === "youtube") {
        source = await createSourceFromURL(url.trim());
      } else if (pdfFile) {
        source = await createSourceFromFile(pdfFile);
      } else {
        setErrorMsg("请选择文件");
        setLoading(false);
        return;
      }

      addSource(source);

      if (source.task_id) {
        // Add to task store and redirect — Dashboard will show progress
        addTask({
          taskId: source.task_id,
          sourceId: source.id,
          title: source.title || url.trim() || pdfName || "导入中...",
          sourceType,
          state: "PENDING",
        });
        router.push("/");
      } else {
        // Source ready immediately, go to dashboard
        router.push("/");
      }
    } catch (err) {
      if (err instanceof DuplicateSourceError) {
        const existing = err.existingSource;
        if (existing?.status === "ready") {
          setErrorMsg("该资源已导入完成，无需重复导入");
        } else {
          setErrorMsg("该资源正在导入中，请稍候查看");
        }
      } else {
        setErrorMsg(err instanceof Error ? err.message : "导入失败，请检查链接或文件后重试");
      }
      setLoading(false);
    }
  };

  const handleFileSelect = (file: File | undefined) => {
    if (file && file.type === "application/pdf") {
      setPdfName(file.name);
      setPdfFile(file);
    }
  };

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="flex items-center justify-between px-4 sm:px-6 h-14 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900">Socratiq</span>
        </div>
      </header>

      <div className="flex-1 flex items-center justify-center px-4 sm:px-6">
        <div className="w-full max-w-xl">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">导入学习资料</h1>
          <p className="text-sm text-gray-500 mb-8">粘贴 B站视频链接或上传 PDF，开始你的个性化学习之旅</p>

          {/* Error message */}
          {errorMsg && (
            <div className="mb-6 flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Source type tabs */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-6">
            <button
              onClick={() => setSourceType("bilibili")}
              className={clsx(
                "flex items-center justify-center gap-2 py-2.5 min-h-[44px] rounded-lg border text-sm font-medium transition-all bg-white",
                sourceType === "bilibili" ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-gray-300"
              )}
            >
              <Play className="w-4 h-4" /> B站视频
            </button>
            <button
              onClick={() => setSourceType("youtube")}
              className={clsx(
                "flex items-center justify-center gap-2 py-2.5 min-h-[44px] rounded-lg border text-sm font-medium transition-all bg-white",
                sourceType === "youtube" ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-gray-300"
              )}
            >
              <Play className="w-4 h-4" /> YouTube
            </button>
            <button
              onClick={() => setSourceType("pdf")}
              className={clsx(
                "flex items-center justify-center gap-2 py-2.5 min-h-[44px] rounded-lg border text-sm font-medium transition-all bg-white",
                sourceType === "pdf" ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-gray-300"
              )}
            >
              <FileText className="w-4 h-4" /> PDF 文档
            </button>
          </div>

          {/* Bilibili URL input */}
          {sourceType === "bilibili" && (
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">视频链接</label>
              <div className="flex gap-2">
                <div className="flex-1 relative">
                  <Play className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://www.bilibili.com/video/BV..."
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                </div>
              </div>
              <button
                onClick={() => setUrl("https://www.bilibili.com/video/BV1gZ4y1F7hS")}
                className="mt-2 text-xs text-blue-600 hover:text-blue-700 bg-transparent border-none cursor-pointer"
              >
                试试看：3Blue1Brown - 深度学习之数学原理
              </button>
            </div>
          )}

          {/* YouTube URL input */}
          {sourceType === "youtube" && (
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">视频链接</label>
              <div className="flex gap-2">
                <div className="flex-1 relative">
                  <Play className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=..."
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                </div>
              </div>
              <button
                onClick={() => setUrl("https://www.youtube.com/watch?v=kCc8FmEb1nY")}
                className="mt-2 text-xs text-blue-600 hover:text-blue-700 bg-transparent border-none cursor-pointer"
              >
                试试看：Karpathy - Let&apos;s build GPT from scratch
              </button>
            </div>
          )}

          {/* PDF upload area */}
          {sourceType === "pdf" && (
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">上传 PDF</label>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFileSelect(e.dataTransfer.files[0]); }}
                onClick={() => fileRef.current?.click()}
                className={clsx(
                  "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
                  dragOver ? "border-blue-400 bg-blue-50" : pdfName ? "border-green-400 bg-green-50" : "border-gray-300 hover:border-gray-400 hover:bg-gray-50"
                )}
              >
                {pdfName ? (
                  <div className="flex items-center justify-center gap-2">
                    <FileText className="w-5 h-5 text-green-600" />
                    <span className="text-sm font-medium text-green-700">{pdfName}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); setPdfName(""); setPdfFile(null); }}
                      className="text-gray-400 hover:text-gray-600 bg-transparent border-none cursor-pointer"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <>
                    <Upload className={clsx("w-8 h-8 mx-auto mb-2", dragOver ? "text-blue-500" : "text-gray-400")} />
                    <p className="text-sm text-gray-600 mb-1">拖拽 PDF 到这里，或点击选择文件</p>
                    <p className="text-xs text-gray-400">支持论文、教材、技术文档等</p>
                  </>
                )}
              </div>
              <input
                ref={fileRef}
                type="file"
                accept=".pdf"
                onChange={(e) => handleFileSelect(e.target.files?.[0])}
                className="hidden"
              />
            </div>
          )}

          {/* Goal Selection */}
          <div className="mb-8">
            <label className="block text-sm font-medium text-gray-700 mb-3">选择学习目标</label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {goals.map((g) => (
                <button
                  key={g.id}
                  onClick={() => setGoal(g.id)}
                  className={clsx(
                    "p-4 min-h-[44px] rounded-xl border text-left transition-all duration-150 bg-white",
                    goal === g.id
                      ? "border-blue-500 bg-blue-50 ring-1 ring-blue-500"
                      : "border-gray-200 hover:border-gray-300"
                  )}
                >
                  <g.icon className={clsx("w-5 h-5 mb-2", goal === g.id ? "text-blue-600" : "text-gray-400")} />
                  <div className={clsx("text-sm font-medium mb-0.5", goal === g.id ? "text-blue-700" : "text-gray-700")}>
                    {g.label}
                  </div>
                  <div className="text-xs text-gray-500">{g.desc}</div>
                </button>
              ))}
            </div>
          </div>

          <Button size="lg" className="w-full" onClick={handleImport} disabled={!canSubmit}>
            <Sparkles className="w-4 h-4" /> 生成学习路径
          </Button>
        </div>
      </div>
    </div>
  );
}
