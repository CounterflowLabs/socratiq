"use client";

import Link from "next/link";
import { ChevronLeft, Clock, BookOpen, Target, ArrowRight, CheckCircle, Brain } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { clsx } from "clsx";

const PATH = [
  { id: 1, title: "Tokenization 基础", desc: "理解文本如何转换为数字", difficulty: "入门", duration: "15 min", status: "current", concepts: ["BPE", "Token", "Vocabulary"] },
  { id: 2, title: "Embedding 与向量空间", desc: "词向量的直觉与数学基础", difficulty: "入门", duration: "20 min", status: "locked", concepts: ["Word2Vec", "Cosine Similarity"] },
  { id: 3, title: "Self-Attention 机制", desc: "Transformer 的核心：注意力如何工作", difficulty: "进阶", duration: "30 min", status: "locked", concepts: ["Q/K/V", "Attention Score", "Multi-Head"] },
  { id: 4, title: "Transformer 架构全景", desc: "从 Encoder-Decoder 到 GPT", difficulty: "进阶", duration: "25 min", status: "locked", concepts: ["Layer Norm", "FFN", "Positional Encoding"] },
  { id: 5, title: "Training & Fine-tuning", desc: "预训练、微调与 RLHF", difficulty: "高级", duration: "35 min", status: "locked", concepts: ["Loss Function", "LoRA", "RLHF"] },
];

export default function PathPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <Link href="/" className="text-xs text-gray-400 hover:text-gray-600 mb-2 flex items-center gap-1 no-underline">
            <ChevronLeft className="w-3 h-3" /> 返回
          </Link>
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-lg font-bold text-gray-900">深度学习之数学原理</h1>
              <p className="text-sm text-gray-500 mt-0.5">3Blue1Brown · Bilibili</p>
            </div>
            <Badge color="blue">系统掌握</Badge>
          </div>
          <div className="flex items-center gap-6 mt-4 text-xs text-gray-500">
            <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> 预计 2 小时 5 分钟</span>
            <span className="flex items-center gap-1"><BookOpen className="w-3.5 h-3.5" /> 5 个章节</span>
            <span className="flex items-center gap-1"><Target className="w-3.5 h-3.5" /> 12 个核心概念</span>
          </div>
        </div>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-6">
        {/* Mentor suggestion */}
        <Card className="p-4 mb-6 border-blue-200 bg-blue-50">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <div>
              <p className="text-sm text-blue-900 font-medium">导师建议</p>
              <p className="text-sm text-blue-800 mt-1 leading-relaxed">
                基于你的评估结果，你对 Python 有不错的基础，但对 Transformer 架构比较陌生。我建议从 Tokenization 开始——这是最基础的概念，理解它会让后续学习事半功倍。每学完一个章节我会用练习来检验你的理解。
              </p>
            </div>
          </div>
        </Card>

        {/* Path sections */}
        <div className="space-y-3">
          {PATH.map((section, idx) => (
            <Link
              key={section.id}
              href={section.status === "current" ? "/learn" : "#"}
              className="no-underline block"
            >
              <Card
                hover={section.status === "current"}
                className={clsx("p-4", section.status === "current" && "border-blue-300 ring-1 ring-blue-100")}
              >
                <div className="flex items-center gap-4">
                  <div
                    className={clsx(
                      "w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold flex-shrink-0",
                      section.status === "current"
                        ? "bg-blue-600 text-white"
                        : section.status === "completed"
                        ? "bg-green-100 text-green-600"
                        : "bg-gray-100 text-gray-400"
                    )}
                  >
                    {section.status === "completed" ? <CheckCircle className="w-5 h-5" /> : idx + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <h3 className={clsx("text-sm font-semibold", section.status === "locked" ? "text-gray-400" : "text-gray-900")}>
                        {section.title}
                      </h3>
                      <Badge color={section.difficulty === "入门" ? "green" : section.difficulty === "进阶" ? "orange" : "red"}>
                        {section.difficulty}
                      </Badge>
                    </div>
                    <p className={clsx("text-xs mb-2", section.status === "locked" ? "text-gray-300" : "text-gray-500")}>
                      {section.desc}
                    </p>
                    <div className="flex items-center gap-2 flex-wrap">
                      {section.concepts.map((c) => (
                        <span
                          key={c}
                          className={clsx(
                            "px-1.5 py-0.5 rounded text-xs",
                            section.status === "locked" ? "bg-gray-50 text-gray-300" : "bg-gray-100 text-gray-500"
                          )}
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className={clsx("text-xs", section.status === "locked" ? "text-gray-300" : "text-gray-400")}>
                      {section.duration}
                    </span>
                    {section.status === "current" && <ArrowRight className="w-4 h-4 text-blue-600" />}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
