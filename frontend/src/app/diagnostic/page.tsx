"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader, CheckCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  generateDiagnostic,
  submitDiagnostic,
  type DiagnosticQuestion,
  type DiagnosticResult,
} from "@/lib/api";

function DiagnosticInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const courseId = searchParams.get("courseId");

  const [questions, setQuestions] = useState<DiagnosticQuestion[]>([]);
  const [conceptMap, setConceptMap] = useState<Record<string, string>>({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<
    { question_id: string; selected_answer: number; time_spent_seconds: number }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [timer, setTimer] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load questions
  useEffect(() => {
    if (!courseId) {
      router.replace("/");
      return;
    }
    setLoading(true);
    generateDiagnostic(courseId)
      .then((data) => {
        setQuestions(data.questions);
        setConceptMap(data.concept_map);
      })
      .catch(() => setError("诊断题生成失败"))
      .finally(() => setLoading(false));
  }, [courseId, router]);

  // Timer per question
  useEffect(() => {
    if (loading || error || result) return;
    setTimer(0);
    timerRef.current = setInterval(() => setTimer((t) => t + 1), 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [currentIndex, loading, error, result]);

  const handleSelect = useCallback(
    async (optionIndex: number) => {
      if (selected !== null) return; // prevent double-click
      setSelected(optionIndex);

      const newAnswer = {
        question_id: questions[currentIndex].id,
        selected_answer: optionIndex,
        time_spent_seconds: timer,
      };
      const newAnswers = [...answers, newAnswer];
      setAnswers(newAnswers);

      // Brief pause before advancing
      await new Promise((r) => setTimeout(r, 400));

      if (currentIndex < questions.length - 1) {
        setCurrentIndex((i) => i + 1);
        setSelected(null);
      } else {
        // Submit all answers
        setSubmitting(true);
        try {
          const questionsMeta = questions.map((q) => ({
            id: q.id,
            correct_index: q.correct_index,
            concept_name: conceptMap[q.concept_id] ?? q.concept_id,
          }));
          const res = await submitDiagnostic(courseId!, questionsMeta, newAnswers);
          setResult(res);
        } catch {
          setError("提交诊断失败");
        } finally {
          setSubmitting(false);
        }
      }
    },
    [selected, questions, currentIndex, timer, answers, courseId, conceptMap],
  );

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <Loader className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-3" />
          <p className="text-sm text-gray-500">正在生成诊断题...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-6">
        <Card className="p-8 max-w-md w-full text-center">
          <XCircle className="w-12 h-12 text-red-400 mx-auto mb-3" />
          <h2 className="text-lg font-bold text-gray-900 mb-2">{error}</h2>
          <p className="text-sm text-gray-500 mb-6">
            你可以跳过诊断直接开始学习
          </p>
          <Button onClick={() => router.push(`/path?courseId=${courseId}`)}>
            跳过诊断
          </Button>
        </Card>
      </div>
    );
  }

  // Result state
  if (result) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-6">
        <Card className="p-8 max-w-lg w-full">
          <div className="text-center mb-6">
            <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-3" />
            <h2 className="text-xl font-bold text-gray-900">诊断完成</h2>
            <p className="text-sm text-gray-500 mt-1">
              你的水平：
              <span className="font-semibold text-blue-600 ml-1">{result.level}</span>
            </p>
          </div>
          <div className="text-center mb-6">
            <span className="text-4xl font-bold text-blue-600">{Math.round(result.score * 100)}%</span>
            <p className="text-xs text-gray-400 mt-1">正确率</p>
          </div>
          {result.mastered_concepts.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">已掌握</h3>
              <div className="flex flex-wrap gap-2">
                {result.mastered_concepts.map((c) => (
                  <span
                    key={c}
                    className="text-xs bg-green-50 text-green-700 px-2 py-1 rounded-full"
                  >
                    {c}
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.gaps.length > 0 && (
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">需要加强</h3>
              <div className="flex flex-wrap gap-2">
                {result.gaps.map((g) => (
                  <span
                    key={g}
                    className="text-xs bg-orange-50 text-orange-700 px-2 py-1 rounded-full"
                  >
                    {g}
                  </span>
                ))}
              </div>
            </div>
          )}
          <Button
            className="w-full"
            onClick={() => router.push(`/path?courseId=${courseId}`)}
          >
            开始学习
          </Button>
        </Card>
      </div>
    );
  }

  // Submitting state
  if (submitting) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <Loader className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-3" />
          <p className="text-sm text-gray-500">正在分析结果...</p>
        </div>
      </div>
    );
  }

  // Quiz UI
  const question = questions[currentIndex];
  const progress = ((currentIndex) / questions.length) * 100;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Progress bar */}
      <div className="h-1 bg-gray-200">
        <div
          className="h-full bg-blue-600 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <span className="text-sm font-medium text-gray-500">
            {currentIndex + 1} / {questions.length}
          </span>
          <span className="text-sm text-gray-400">{timer}s</span>
        </div>

        {/* Question */}
        <Card className="p-6 mb-6">
          <h2 className="text-base font-semibold text-gray-900 leading-relaxed">
            {question.question}
          </h2>
        </Card>

        {/* Options */}
        <div className="space-y-3">
          {question.options.map((option, idx) => (
            <button
              key={idx}
              onClick={() => handleSelect(idx)}
              disabled={selected !== null}
              className={`w-full text-left px-5 py-4 min-h-[44px] rounded-xl border text-sm transition-all duration-150 ${
                selected === idx
                  ? "border-blue-500 bg-blue-50 text-blue-700"
                  : "border-gray-200 bg-white text-gray-700 hover:border-blue-300 hover:bg-blue-50/50"
              } disabled:cursor-default`}
            >
              <span className="font-medium mr-3 text-gray-400">
                {String.fromCharCode(65 + idx)}.
              </span>
              {option}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function DiagnosticPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-sm text-gray-500">正在准备学习环境...</div>
        </div>
      }
    >
      <DiagnosticInner />
    </Suspense>
  );
}
