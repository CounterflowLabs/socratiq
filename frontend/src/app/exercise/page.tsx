"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader, CheckCircle, XCircle, ArrowLeft, ArrowRight } from "lucide-react";
import Editor from "@monaco-editor/react";
import {
  getSectionExercises,
  submitExercise,
  type ExerciseResponse,
  type SubmissionResult,
} from "@/lib/api";

function ExerciseInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const courseId = searchParams.get("courseId");
  const sectionId = searchParams.get("sectionId");

  const [exercises, setExercises] = useState<ExerciseResponse[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Per-exercise state
  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [textAnswer, setTextAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SubmissionResult | null>(null);

  // Accumulated results for completion summary
  const [allResults, setAllResults] = useState<Array<{ exerciseId: string; score: number | null }>>([]);
  const [showSummary, setShowSummary] = useState(false);

  useEffect(() => {
    if (!sectionId) {
      setLoading(false);
      setError("缺少章节参数");
      return;
    }
    setLoading(true);
    getSectionExercises(sectionId)
      .then((data) => setExercises(data.exercises))
      .catch(() => setError("练习题加载失败"))
      .finally(() => setLoading(false));
  }, [sectionId]);

  const resetExerciseState = () => {
    setSelectedOption(null);
    setTextAnswer("");
    setResult(null);
    setSubmitting(false);
  };

  const handleSubmit = async () => {
    const ex = exercises[currentIndex];
    let answer: string;
    if (ex.type === "mcq") {
      if (selectedOption === null) return;
      answer = String(selectedOption);
    } else {
      if (!textAnswer.trim()) return;
      answer = textAnswer.trim();
    }

    setSubmitting(true);
    try {
      const res = await submitExercise(ex.id, answer);
      setResult(res);
      setAllResults((prev) => [...prev, { exerciseId: ex.id, score: res.score }]);
    } catch {
      const errorResult: SubmissionResult = {
        submission_id: "",
        score: null,
        feedback: "提交失败，请重试",
        explanation: null,
      };
      setResult(errorResult);
      setAllResults((prev) => [...prev, { exerciseId: ex.id, score: null }]);
    } finally {
      setSubmitting(false);
    }
  };

  const goToNext = () => {
    if (currentIndex < exercises.length - 1) {
      setCurrentIndex((i) => i + 1);
      resetExerciseState();
    }
  };

  const goToPrev = () => {
    if (currentIndex > 0) {
      setCurrentIndex((i) => i - 1);
      resetExerciseState();
    }
  };

  const handleFinish = () => {
    setShowSummary(true);
  };

  // Loading
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg)" }}>
        <Loader className="w-6 h-6 animate-spin mr-2" style={{ color: "var(--primary)" }} />
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>加载练习题...</span>
      </div>
    );
  }

  // Error
  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg)" }}>
        <div className="card max-w-md w-full text-center">
          <XCircle className="w-12 h-12 mx-auto mb-3" style={{ color: "var(--error)" }} />
          <h2 className="text-lg font-bold mb-4" style={{ color: "var(--text)" }}>{error}</h2>
          <button className="btn-secondary" onClick={() => router.back()}>返回</button>
        </div>
      </div>
    );
  }

  // Empty
  if (exercises.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg)" }}>
        <div className="card max-w-md w-full text-center">
          <h2 className="text-lg font-bold mb-2" style={{ color: "var(--text)" }}>此章节暂无练习题</h2>
          <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>导师会在你学习后生成针对性练习</p>
          <button className="btn-secondary" onClick={() => router.back()}>返回学习</button>
        </div>
      </div>
    );
  }

  // Completion summary
  if (showSummary) {
    const validScores = allResults.filter((r) => r.score !== null);
    const avgScore =
      validScores.length > 0
        ? validScores.reduce((sum, r) => sum + (r.score ?? 0), 0) / validScores.length
        : null;
    const passCount = allResults.filter((r) => r.score !== null && r.score >= 0.6).length;

    return (
      <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg)" }}>
        <div className="card max-w-md w-full">
          <div className="text-center mb-6">
            <CheckCircle className="w-14 h-14 mx-auto mb-3" style={{ color: "var(--success)" }} />
            <h2 className="text-xl font-bold mb-1" style={{ color: "var(--text)" }}>练习完成！</h2>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              共 {exercises.length} 题，答对 {passCount} 题
            </p>
          </div>

          {avgScore !== null && (
            <div
              className="rounded-xl p-4 mb-5 text-center"
              style={{ background: "var(--surface-alt)" }}
            >
              <p className="text-sm mb-1" style={{ color: "var(--text-secondary)" }}>综合得分</p>
              <p
                className="text-3xl font-bold"
                style={{ color: avgScore >= 0.6 ? "var(--success)" : "var(--error)" }}
              >
                {Math.round(avgScore * 100)}%
              </p>
            </div>
          )}

          {/* Per-question breakdown */}
          <div className="space-y-2 mb-6">
            {allResults.map((r, idx) => {
              const passed = r.score !== null && r.score >= 0.6;
              const noScore = r.score === null;
              return (
                <div
                  key={idx}
                  className="flex items-center justify-between rounded-xl px-4 py-3"
                  style={{ background: "var(--surface-alt)" }}
                >
                  <span className="text-sm" style={{ color: "var(--text)" }}>
                    第 {idx + 1} 题
                  </span>
                  <div className="flex items-center gap-2">
                    {noScore ? (
                      <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>未评分</span>
                    ) : passed ? (
                      <>
                        <CheckCircle className="w-4 h-4" style={{ color: "var(--success)" }} />
                        <span className="text-xs font-medium" style={{ color: "var(--success)" }}>
                          {Math.round((r.score ?? 0) * 100)}%
                        </span>
                      </>
                    ) : (
                      <>
                        <XCircle className="w-4 h-4" style={{ color: "var(--error)" }} />
                        <span className="text-xs font-medium" style={{ color: "var(--error)" }}>
                          {Math.round((r.score ?? 0) * 100)}%
                        </span>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <button
            className="btn-primary w-full"
            onClick={() => {
              if (courseId) {
                router.push(`/path?courseId=${courseId}`);
              } else {
                router.back();
              }
            }}
          >
            返回课程大纲
          </button>
        </div>
      </div>
    );
  }

  const exercise = exercises[currentIndex];
  const isLastExercise = currentIndex === exercises.length - 1;

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      {/* Progress bar */}
      <div className="h-1" style={{ background: "var(--border)" }}>
        <div
          className="h-full transition-all duration-300"
          style={{
            width: `${((currentIndex + 1) / exercises.length) * 100}%`,
            background: "var(--primary)",
          }}
        />
      </div>

      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <button
            onClick={() => router.back()}
            className="btn-ghost flex items-center gap-1 min-h-[44px] text-sm"
          >
            <ArrowLeft className="w-4 h-4" /> 返回
          </button>
          <span className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
            {currentIndex + 1} / {exercises.length}
          </span>
        </div>

        {/* Question card */}
        <div className="card mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{ background: "var(--surface-alt)", color: "var(--text-secondary)" }}
            >
              {exercise.type === "mcq" ? "选择题" : exercise.type === "code" ? "代码题" : "开放题"}
            </span>
            <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              难度 {exercise.difficulty}/5
            </span>
          </div>
          <h2 className="text-base font-semibold leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text)" }}>
            {exercise.question}
          </h2>
        </div>

        {/* Answer area */}
        {exercise.type === "mcq" && exercise.options ? (
          <div className="space-y-3 mb-6">
            {exercise.options.map((option, idx) => {
              let borderColor = "var(--border-medium)";
              let bgColor = "var(--surface)";
              let textColor = "var(--text)";

              if (result) {
                if (idx === selectedOption && result.score === 1) {
                  borderColor = "var(--success)";
                  bgColor = "var(--success-light)";
                  textColor = "var(--success)";
                } else if (idx === selectedOption && result.score !== 1) {
                  borderColor = "var(--error)";
                  bgColor = "var(--error-light)";
                  textColor = "var(--error)";
                }
              } else if (selectedOption === idx) {
                borderColor = "var(--primary)";
                bgColor = "var(--primary-light)";
                textColor = "var(--primary)";
              }

              return (
                <button
                  key={idx}
                  onClick={() => !result && setSelectedOption(idx)}
                  disabled={!!result}
                  className="w-full text-left px-4 sm:px-5 py-4 min-h-[44px] rounded-xl border text-sm transition-all duration-150 disabled:cursor-default"
                  style={{ borderColor, background: bgColor, color: textColor }}
                >
                  <span className="font-medium mr-3" style={{ color: "var(--text-tertiary)" }}>
                    {String.fromCharCode(65 + idx)}.
                  </span>
                  {option}
                </button>
              );
            })}
          </div>
        ) : exercise.type === "code" ? (
          <div className="mb-6 rounded-xl overflow-hidden border" style={{ borderColor: "var(--border-medium)" }}>
            <Editor
              height="300px"
              language="python"
              value={textAnswer}
              onChange={(v) => setTextAnswer(v ?? "")}
              options={{
                minimap: { enabled: false },
                fontSize: 14,
                lineNumbers: "on",
                scrollBeyondLastLine: false,
                readOnly: !!result,
              }}
              theme="vs-light"
            />
          </div>
        ) : (
          <div className="mb-6">
            <textarea
              value={textAnswer}
              onChange={(e) => setTextAnswer(e.target.value)}
              disabled={!!result}
              placeholder="在此输入你的答案..."
              className="w-full min-h-[120px] sm:min-h-[160px] px-4 py-3 rounded-xl text-sm focus:outline-none resize-y disabled:opacity-60"
              style={{
                border: "1px solid var(--border-medium)",
                background: result ? "var(--surface-alt)" : "var(--surface)",
                color: "var(--text)",
              }}
            />
            <p className="text-xs mt-1 text-right" style={{ color: "var(--text-tertiary)" }}>
              {textAnswer.length} 字
            </p>
          </div>
        )}

        {/* Result feedback */}
        {result && (
          <div className="card mb-6">
            <div className="flex items-start gap-3">
              {result.score === 1 ? (
                <CheckCircle className="w-5 h-5 mt-0.5 flex-shrink-0" style={{ color: "var(--success)" }} />
              ) : (
                <XCircle className="w-5 h-5 mt-0.5 flex-shrink-0" style={{ color: "var(--error)" }} />
              )}
              <div className="flex-1 min-w-0">
                {result.feedback && (
                  <p className="text-sm font-medium mb-1" style={{ color: "var(--text)" }}>
                    {result.feedback}
                  </p>
                )}
                {result.score !== null && result.score !== 1 && result.score !== 0 && (
                  <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
                    得分：{Math.round(result.score * 100)}%
                  </p>
                )}
              </div>
            </div>

            {result.explanation && (
              <div className="mt-3 p-4 rounded-xl" style={{ background: "var(--surface-alt)" }}>
                <p className="text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>解析</p>
                <p className="text-sm" style={{ color: "var(--text)" }}>{result.explanation}</p>
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between">
          <button
            className="btn-ghost flex items-center gap-1"
            onClick={goToPrev}
            disabled={currentIndex === 0}
            style={{ opacity: currentIndex === 0 ? 0.4 : 1, cursor: currentIndex === 0 ? "not-allowed" : "pointer" }}
          >
            <ArrowLeft className="w-4 h-4" /> 上一题
          </button>

          {!result ? (
            <button
              className="btn-primary flex items-center gap-2"
              onClick={handleSubmit}
              disabled={
                submitting ||
                (exercise.type === "mcq" ? selectedOption === null : !textAnswer.trim())
              }
            >
              {submitting ? (
                <>
                  <Loader className="w-4 h-4 animate-spin" /> 提交中...
                </>
              ) : (
                "提交答案"
              )}
            </button>
          ) : isLastExercise ? (
            <button className="btn-primary flex items-center gap-2" onClick={handleFinish}>
              完成 <ArrowRight className="w-4 h-4" />
            </button>
          ) : (
            <button className="btn-secondary flex items-center gap-2" onClick={goToNext}>
              下一题 <ArrowRight className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ExercisePage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg)" }}>
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>加载中...</div>
        </div>
      }
    >
      <ExerciseInner />
    </Suspense>
  );
}
