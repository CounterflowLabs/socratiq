"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ClipboardList, Loader2, Sparkles } from "lucide-react";

import { generateSectionExercises, getSectionExercises } from "@/lib/api";

interface ExerciseTriggerCardProps {
  title: string;
  body: string;
  sectionId: string;
  courseId?: string | null;
  enabled: boolean;
}

type ExerciseLoadState = "idle" | "checking" | "ready" | "empty" | "error";

export function ExerciseTriggerCard({
  title,
  body,
  sectionId,
  courseId,
  enabled,
}: ExerciseTriggerCardProps) {
  const router = useRouter();
  const [status, setStatus] = useState<ExerciseLoadState>("idle");
  const [count, setCount] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!enabled || !sectionId) return;
    let cancelled = false;
    setStatus("checking");
    setError(null);
    getSectionExercises(sectionId)
      .then((data) => {
        if (cancelled) return;
        setCount(data.exercises.length);
        setStatus(data.exercises.length > 0 ? "ready" : "empty");
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus("error");
        setError(err instanceof Error ? err.message : "练习状态加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, sectionId]);

  if (!enabled) return null;

  function gotoExercise() {
    const qs = new URLSearchParams();
    if (courseId) qs.set("courseId", courseId);
    qs.set("sectionId", sectionId);
    router.push(`/exercise?${qs.toString()}`);
  }

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const data = await generateSectionExercises(sectionId, 3, ["mcq", "open"]);
      setCount(data.exercises.length);
      setStatus(data.exercises.length > 0 ? "ready" : "empty");
      if (data.exercises.length > 0) {
        gotoExercise();
      }
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "生成失败，请稍后重试");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <section className="rounded-lg border border-sky-200 bg-sky-50/60 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-2 rounded-md bg-white px-3 py-1 text-xs font-semibold uppercase text-sky-700">
            <ClipboardList className="h-3.5 w-3.5" />
            Exercise
          </div>
          <h3 className="mt-3 text-base font-semibold text-slate-900">{title}</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{body}</p>
          {status === "ready" ? (
            <p className="mt-2 text-xs text-sky-700">已为本节生成 {count} 道题</p>
          ) : status === "empty" ? (
            <p className="mt-2 text-xs text-slate-500">本节尚未生成练习题</p>
          ) : null}
          {error ? (
            <p className="mt-2 text-xs text-red-600">{error}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {status === "ready" ? (
            <button
              type="button"
              onClick={gotoExercise}
              className="inline-flex items-center gap-1.5 rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
            >
              开始练习
            </button>
          ) : status === "empty" ? (
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating}
              className="inline-flex items-center gap-1.5 rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:opacity-60"
            >
              {generating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  生成中…
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  生成练习
                </>
              )}
            </button>
          ) : status === "checking" ? (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-sky-200 bg-white px-4 py-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </span>
          ) : status === "error" ? (
            <button
              type="button"
              onClick={() => {
                setStatus("idle");
                setError(null);
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-sky-200 bg-white px-4 py-2 text-sm font-medium text-sky-700 transition hover:bg-sky-100"
            >
              重试
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
