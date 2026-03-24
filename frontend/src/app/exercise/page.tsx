"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, ArrowRight, CheckCircle, AlertCircle, Brain, Award } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress-bar";
import { clsx } from "clsx";

const EXERCISES = [
  {
    type: "choice",
    question: "在 BPE (Byte Pair Encoding) 算法中，合并操作的依据是什么？",
    options: ["字符出现频率最高", "相邻字符对出现频率最高", "字符的 Unicode 编码顺序", "随机选择字符对"],
    answer: 1,
    explanation: "BPE 通过统计语料库中相邻字符对（bigram）的出现频率，每次合并频率最高的字符对，逐步构建子词词汇表。",
  },
  {
    type: "choice",
    question: "为什么现代 LLM 通常使用子词级别的 tokenization，而不是字符级别或单词级别？",
    options: ["计算速度更快", "平衡了词汇表大小和序列长度，同时能处理未知词", "实现起来更简单", "占用更少的存储空间"],
    answer: 1,
    explanation: "子词 tokenization 是一种折中方案：相比字符级别，序列更短（计算效率高）；相比单词级别，词汇表更小且能通过子词组合处理未见过的词（OOV 问题）。",
  },
];

export default function ExercisePage() {
  const [current, setCurrent] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [results, setResults] = useState<{ correct: boolean }[]>([]);
  const [showFeedback, setShowFeedback] = useState(false);

  const ex = EXERCISES[current];
  const isCorrect = selected === ex.answer;

  const handleSubmit = () => {
    setSubmitted(true);
    setResults([...results, { correct: isCorrect }]);
  };

  const handleNext = () => {
    if (current < EXERCISES.length - 1) {
      setCurrent(current + 1);
      setSelected(null);
      setSubmitted(false);
    } else {
      setShowFeedback(true);
    }
  };

  if (showFeedback) {
    const score = results.filter((r) => r.correct).length;
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-6">
        <Card className="p-8 max-w-md w-full text-center">
          <div className={clsx("w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4", score === results.length ? "bg-green-100" : "bg-amber-100")}>
            {score === results.length ? <Award className="w-8 h-8 text-green-600" /> : <Brain className="w-8 h-8 text-amber-600" />}
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">
            {score === results.length ? "全部正确！" : "继续努力！"}
          </h2>
          <p className="text-sm text-gray-500 mb-4">{score} / {results.length} 题正确</p>
          <ProgressBar value={(score / results.length) * 100} className="mb-6" />

          <Card className="p-4 text-left mb-6 bg-blue-50 border-blue-200">
            <div className="flex items-start gap-2">
              <Brain className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-blue-900 mb-1">导师反馈</p>
                <p className="text-sm text-blue-800 leading-relaxed">
                  {score === results.length
                    ? "你对 Tokenization 的理解很扎实！特别是对 BPE 算法的掌握让我印象深刻。我们可以继续学习下一章 Embedding 了。"
                    : "你对 Tokenization 的基本概念有了初步理解，但在 BPE 算法的细节上还需要加强。我建议回看视频 8:20-15:00 的部分，然后我们用不同角度再讲一次。"}
                </p>
              </div>
            </div>
          </Card>

          <div className="flex gap-3">
            <Link href="/learn" className="flex-1">
              <Button variant="secondary" className="w-full">回到课程</Button>
            </Link>
            <Link href="/" className="flex-1">
              <Button className="w-full">
                {score === results.length ? "下一章" : "复习薄弱点"}
                <ArrowRight className="w-4 h-4" />
              </Button>
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 h-12 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/learn" className="text-gray-400 hover:text-gray-600">
            <ChevronLeft className="w-4 h-4" />
          </Link>
          <span className="text-sm font-medium text-gray-900">章节练习：Tokenization 基础</span>
        </div>
        <span className="text-xs text-gray-400">{current + 1} / {EXERCISES.length}</span>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8">
        <ProgressBar value={((current + (submitted ? 1 : 0)) / EXERCISES.length) * 100} className="mb-8" />

        <div className="mb-2">
          <Badge color="violet">选择题</Badge>
        </div>
        <h2 className="text-lg font-semibold text-gray-900 mb-6 leading-relaxed">{ex.question}</h2>

        <div className="space-y-3 mb-8">
          {ex.options.map((opt, i) => {
            let style = "border-gray-200 hover:border-gray-300";
            if (submitted) {
              if (i === ex.answer) style = "border-green-500 bg-green-50 ring-1 ring-green-500";
              else if (i === selected && !isCorrect) style = "border-red-500 bg-red-50 ring-1 ring-red-500";
              else style = "border-gray-200 opacity-50";
            } else if (i === selected) {
              style = "border-blue-500 bg-blue-50 ring-1 ring-blue-500";
            }
            return (
              <button
                key={i}
                disabled={submitted}
                onClick={() => setSelected(i)}
                className={clsx("w-full text-left px-4 py-3 rounded-xl border transition-all duration-150 text-sm bg-white", style)}
              >
                <div className="flex items-start gap-3">
                  <span
                    className={clsx(
                      "w-6 h-6 rounded-full border flex items-center justify-center text-xs font-medium flex-shrink-0 mt-0.5",
                      submitted && i === ex.answer ? "bg-green-500 text-white border-green-500" :
                      submitted && i === selected && !isCorrect ? "bg-red-500 text-white border-red-500" :
                      i === selected ? "bg-blue-500 text-white border-blue-500" : "border-gray-300 text-gray-500"
                    )}
                  >
                    {String.fromCharCode(65 + i)}
                  </span>
                  <span className={clsx(submitted && i !== ex.answer && i !== selected && "text-gray-400")}>{opt}</span>
                </div>
              </button>
            );
          })}
        </div>

        {submitted && (
          <Card className={clsx("p-4 mb-6", isCorrect ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200")}>
            <div className="flex items-start gap-2">
              {isCorrect ? <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" /> : <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />}
              <div>
                <p className={clsx("text-sm font-medium mb-1", isCorrect ? "text-green-800" : "text-red-800")}>
                  {isCorrect ? "回答正确！" : "还不太对"}
                </p>
                <p className={clsx("text-sm leading-relaxed", isCorrect ? "text-green-700" : "text-red-700")}>{ex.explanation}</p>
              </div>
            </div>
          </Card>
        )}

        <div className="flex justify-end">
          {!submitted ? (
            <Button onClick={handleSubmit} disabled={selected === null}>提交答案</Button>
          ) : (
            <Button onClick={handleNext}>
              {current < EXERCISES.length - 1 ? "下一题" : "查看结果"} <ArrowRight className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
