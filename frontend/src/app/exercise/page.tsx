"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader, CheckCircle, XCircle, ArrowLeft, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
    } catch {
      setResult({
        submission_id: "",
        score: null,
        feedback: "提交失败，请重试",
        explanation: "",
      });
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

  // Loading
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <Loader className="w-6 h-6 animate-spin text-blue-600 mr-2" />
        <span className="text-sm text-gray-500">加载练习题...</span>
      </div>
    );
  }

  // Error
  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-6">
        <Card className="p-8 max-w-md w-full text-center">
          <XCircle className="w-12 h-12 text-red-400 mx-auto mb-3" />
          <h2 className="text-lg font-bold text-gray-900 mb-4">{error}</h2>
          <Button onClick={() => router.back()}>返回</Button>
        </Card>
      </div>
    );
  }

  // Empty
  if (exercises.length === 0) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-6">
        <Card className="p-8 max-w-md w-full text-center">
          <h2 className="text-lg font-bold text-gray-900 mb-2">此章节暂无练习题</h2>
          <p className="text-sm text-gray-500 mb-6">导师会在你学习后生成针对性练习</p>
          <Button onClick={() => router.back()}>返回学习</Button>
        </Card>
      </div>
    );
  }

  const exercise = exercises[currentIndex];
  const isLastExercise = currentIndex === exercises.length - 1;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Progress */}
      <div className="h-1 bg-gray-200">
        <div
          className="h-full bg-blue-600 transition-all duration-300"
          style={{ width: `${((currentIndex + 1) / exercises.length) * 100}%` }}
        />
      </div>

      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <button
            onClick={() => router.back()}
            className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1"
          >
            <ArrowLeft className="w-4 h-4" /> 返回
          </button>
          <span className="text-sm font-medium text-gray-500">
            {currentIndex + 1} / {exercises.length}
          </span>
        </div>

        {/* Question card */}
        <Card className="p-6 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
              {exercise.type === "mcq" ? "选择题" : exercise.type === "code" ? "代码题" : "开放题"}
            </span>
            <span className="text-xs text-gray-400">
              难度 {exercise.difficulty}/5
            </span>
          </div>
          <h2 className="text-base font-semibold text-gray-900 leading-relaxed whitespace-pre-wrap">
            {exercise.question}
          </h2>
        </Card>

        {/* Answer area */}
        {exercise.type === "mcq" && exercise.options ? (
          <div className="space-y-3 mb-6">
            {exercise.options.map((option, idx) => {
              let optionStyle = "border-gray-200 bg-white text-gray-700 hover:border-blue-300";
              if (result) {
                if (idx === selectedOption && result.score === 1) {
                  optionStyle = "border-green-500 bg-green-50 text-green-700";
                } else if (idx === selectedOption && result.score !== 1) {
                  optionStyle = "border-red-500 bg-red-50 text-red-700";
                }
              } else if (selectedOption === idx) {
                optionStyle = "border-blue-500 bg-blue-50 text-blue-700";
              }
              return (
                <button
                  key={idx}
                  onClick={() => !result && setSelectedOption(idx)}
                  disabled={!!result}
                  className={`w-full text-left px-5 py-4 rounded-xl border text-sm transition-all duration-150 ${optionStyle} disabled:cursor-default`}
                >
                  <span className="font-medium mr-3 text-gray-400">
                    {String.fromCharCode(65 + idx)}.
                  </span>
                  {option}
                </button>
              );
            })}
          </div>
        ) : (
          <div className="mb-6">
            <textarea
              value={textAnswer}
              onChange={(e) => setTextAnswer(e.target.value)}
              disabled={!!result}
              placeholder={exercise.type === "code" ? "在此输入代码..." : "在此输入你的答案..."}
              className={`w-full min-h-[160px] px-4 py-3 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y disabled:bg-gray-50 ${
                exercise.type === "code" ? "font-mono" : ""
              }`}
            />
            {exercise.type === "open" && (
              <p className="text-xs text-gray-400 mt-1 text-right">
                {textAnswer.length} 字
              </p>
            )}
          </div>
        )}

        {/* Result feedback */}
        {result && (
          <Card className="p-5 mb-6">
            <div className="flex items-start gap-3">
              {result.score === 1 ? (
                <CheckCircle className="w-5 h-5 text-green-500 mt-0.5 flex-shrink-0" />
              ) : (
                <XCircle className="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" />
              )}
              <div>
                <p className="text-sm font-medium text-gray-900 mb-1">
                  {result.feedback}
                </p>
                {result.explanation && (
                  <p className="text-sm text-gray-600">{result.explanation}</p>
                )}
                {result.score !== null && result.score !== 1 && result.score !== 0 && (
                  <p className="text-xs text-gray-400 mt-1">
                    得分：{Math.round(result.score * 100)}%
                  </p>
                )}
              </div>
            </div>
          </Card>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={goToPrev}
            disabled={currentIndex === 0}
          >
            <ArrowLeft className="w-4 h-4" /> 上一题
          </Button>

          {!result ? (
            <Button
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
            </Button>
          ) : isLastExercise ? (
            <Button onClick={() => {
              if (courseId) {
                router.push(`/path?courseId=${courseId}`);
              } else {
                router.back();
              }
            }}>
              完成 <ArrowRight className="w-4 h-4" />
            </Button>
          ) : (
            <Button onClick={goToNext}>
              下一题 <ArrowRight className="w-4 h-4" />
            </Button>
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
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
          <div className="text-sm text-gray-500">加载中...</div>
        </div>
      }
    >
      <ExerciseInner />
    </Suspense>
  );
}
