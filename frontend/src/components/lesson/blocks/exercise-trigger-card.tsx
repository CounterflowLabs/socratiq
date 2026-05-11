"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { IcExercise, IcLoader, IcSparkle } from "@/components/icons";
import { generateSectionExercises, getSectionExercises } from "@/lib/api";

interface ExerciseTriggerCardProps {
  title: string;
  body: string;
  sectionId: string;
  courseId?: string | null;
  enabled: boolean;
}

type ExerciseLoadState =
  | "idle"
  | "checking"
  | "ready"
  | "empty"
  | "generating"
  | "error";

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

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
  const pollDeadlineRef = useRef<number | null>(null);

  // Initial load + listen for in-flight generation that the user
  // returns to mid-flight.
  useEffect(() => {
    if (!enabled || !sectionId) return;
    let cancelled = false;
    setStatus("checking");
    setError(null);
    getSectionExercises(sectionId)
      .then((data) => {
        if (cancelled) return;
        setCount(data.exercises.length);
        setError(data.error);
        if (data.is_generating) {
          pollDeadlineRef.current = Date.now() + POLL_TIMEOUT_MS;
          setStatus("generating");
        } else {
          setStatus(data.exercises.length > 0 ? "ready" : "empty");
        }
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

  // Poll while a generation task is in flight.
  useEffect(() => {
    if (status !== "generating" || !sectionId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (cancelled) return;
      try {
        const data = await getSectionExercises(sectionId);
        if (cancelled) return;
        setCount(data.exercises.length);
        if (data.is_generating) {
          if (
            pollDeadlineRef.current !== null &&
            Date.now() > pollDeadlineRef.current
          ) {
            setStatus("error");
            setError("生成超时，请稍后重试");
            return;
          }
          timer = setTimeout(tick, POLL_INTERVAL_MS);
          return;
        }
        // Generation finished
        setError(data.error);
        if (data.exercises.length > 0) {
          setStatus("ready");
        } else {
          setStatus("empty");
        }
      } catch (err) {
        if (cancelled) return;
        setStatus("error");
        setError(err instanceof Error ? err.message : "生成轮询失败");
      }
    };

    timer = setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [status, sectionId]);

  if (!enabled) return null;

  function gotoExercise() {
    const qs = new URLSearchParams();
    if (courseId) qs.set("courseId", courseId);
    qs.set("sectionId", sectionId);
    router.push(`/exercise?${qs.toString()}`);
  }

  async function handleGenerate() {
    setError(null);
    setStatus("generating");
    pollDeadlineRef.current = Date.now() + POLL_TIMEOUT_MS;
    try {
      await generateSectionExercises(sectionId, 3, ["mcq", "open"]);
      // Polling effect handles the rest.
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "生成失败，请稍后重试");
    }
  }

  return (
    <section className="rounded-lg border border-sky-200 bg-sky-50/60 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-2 rounded-md bg-white px-3 py-1 text-xs font-semibold uppercase text-sky-700">
            <IcExercise size={14} />
            Exercise
          </div>
          <h3 className="mt-3 text-base font-semibold text-slate-900">{title}</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{body}</p>
          {status === "ready" ? (
            <p className="mt-2 text-xs text-sky-700">已为本节生成 {count} 道题</p>
          ) : status === "empty" ? (
            <p className="mt-2 text-xs text-slate-500">本节尚未生成练习题</p>
          ) : status === "generating" ? (
            <p className="mt-2 text-xs text-sky-700">正在后台生成练习，可以继续浏览课程，本卡片会自动更新。</p>
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
              className="inline-flex items-center gap-1.5 rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
            >
              <IcSparkle size={14} />
              生成练习
            </button>
          ) : status === "generating" ? (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-sky-200 bg-white px-4 py-2 text-sm text-slate-600">
              <IcLoader size={14} className="spin" />
              生成中…
            </span>
          ) : status === "checking" ? (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-sky-200 bg-white px-4 py-2 text-sm text-slate-500">
              <IcLoader size={14} className="spin" />
              加载中…
            </span>
          ) : status === "error" ? (
            <button
              type="button"
              onClick={handleGenerate}
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
