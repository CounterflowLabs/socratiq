"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Brain, Sparkles, Loader, CheckCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ProgressBar } from "@/components/ui/progress-bar";
import { clsx } from "clsx";

const QUESTIONS = [
  {
    q: "Tokenization 是把文本切分成更小的单位。你知道为什么不能直接用单词作为最小单位吗？",
    opts: [
      "不太清楚，感觉用单词就可以了",
      "好像和词汇表大小有关，但不确定细节",
      "因为会遇到未登录词（OOV）问题，子词切分能更灵活",
      "清楚原因，我了解 BPE / WordPiece / SentencePiece 等方案",
    ],
    concept: "Tokenization",
  },
  {
    q: "在神经网络中，Embedding 层的作用是什么？",
    opts: [
      "完全不了解 Embedding 是什么",
      "好像是把文字变成数字，但不确定怎么变的",
      "将离散 token 映射到连续向量空间，使语义相近的词距离更近",
      "熟悉 Embedding，了解 Word2Vec / GloVe 等预训练方法",
    ],
    concept: "Embedding",
  },
  {
    q: "Self-Attention 机制中的 Query、Key、Value 分别起什么作用？",
    opts: [
      "没听说过 Self-Attention",
      "知道 Attention 的大概思路，但 Q/K/V 不太清楚",
      "Query 用来提问，Key 用来匹配，Value 是被加权聚合的信息",
      "熟悉 Scaled Dot-Product Attention 和 Multi-Head 的完整计算流程",
    ],
    concept: "Self-Attention",
  },
  {
    q: "Transformer 中为什么需要 Positional Encoding？",
    opts: [
      "不了解 Transformer 的结构",
      "隐约知道和位置有关，但不清楚为什么需要",
      "因为 Self-Attention 本身不区分顺序，需要额外注入位置信息",
      "了解正弦位置编码和可学习位置编码的区别及各自优缺点",
    ],
    concept: "Positional Encoding",
  },
  {
    q: "GPT 模型在训练时的目标函数是什么？",
    opts: [
      "不知道 GPT 怎么训练的",
      "好像是预测什么东西，但不确定",
      "自回归语言模型——给定前文预测下一个 token",
      "清楚 next-token prediction、交叉熵损失，也了解 fine-tuning 和 RLHF",
    ],
    concept: "Training Objective",
  },
];

export default function DiagnosticPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [analyzing, setAnalyzing] = useState(false);

  const handleAnswer = async (idx: number) => {
    if (step < QUESTIONS.length - 1) {
      setStep(step + 1);
    } else {
      setAnalyzing(true);
      await new Promise((r) => setTimeout(r, 2200));
      router.push("/path");
    }
  };

  if (analyzing) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="text-center max-w-sm">
          <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-4 animate-pulse">
            <Brain className="w-6 h-6 text-blue-600" />
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">正在生成个性化学习路径...</h2>
          <p className="text-sm text-gray-500 mb-6">基于你的回答和视频内容，为你编排最优学习顺序</p>
          <div className="space-y-3 text-left bg-gray-50 rounded-xl p-4">
            {["结合回答评估知识基线", "标记已掌握 / 薄弱 / 未知概念", "按前置依赖排列学习顺序", "生成个性化学习路径"].map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                {i < 2 ? (
                  <CheckCircle className="w-4 h-4 text-green-500" />
                ) : i === 2 ? (
                  <Loader className="w-4 h-4 text-blue-500 animate-spin" />
                ) : (
                  <div className="w-4 h-4 rounded-full border border-gray-300" />
                )}
                <span className={clsx(i < 2 ? "text-gray-500" : i === 2 ? "text-gray-900 font-medium" : "text-gray-400")}>
                  {s}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const q = QUESTIONS[step];
  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="flex items-center justify-between px-6 h-14 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900">LearnMentor</span>
        </div>
        <span className="text-xs text-gray-400">{step + 1} / {QUESTIONS.length}</span>
      </header>

      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-lg">
          {step === 0 && (
            <div className="mb-6 p-3 rounded-xl bg-blue-50 border border-blue-100 flex items-start gap-2.5">
              <Sparkles className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-blue-800">基于内容的自适应评估</p>
                <p className="text-xs text-blue-600 mt-0.5">
                  我已分析了 3Blue1Brown 的 B站视频，从中提取了 5 个核心概念。回答以下问题帮助我了解你的起点，以便跳过你已经会的、聚焦你不会的。
                </p>
              </div>
            </div>
          )}

          <div className="mb-8">
            <ProgressBar value={(step / QUESTIONS.length) * 100} className="mb-6" />
            <div className="flex items-center gap-2 mb-2">
              <Badge color="violet">{q.concept}</Badge>
              <span className="text-xs text-gray-400">概念 {step + 1} / {QUESTIONS.length}</span>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 leading-relaxed">{q.q}</h2>
          </div>

          <div className="space-y-2">
            {q.opts.map((opt, i) => (
              <button
                key={i}
                onClick={() => handleAnswer(i)}
                className="w-full text-left px-4 py-3 rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-all duration-150 text-sm text-gray-700 hover:text-blue-700 bg-white"
              >
                <div className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full border border-gray-300 flex items-center justify-center text-xs text-gray-400 flex-shrink-0 mt-0.5">
                    {i + 1}
                  </span>
                  <span>{opt}</span>
                </div>
              </button>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-4 text-center">如实作答即可，这不是考试——是帮导师了解你的起点</p>
        </div>
      </div>
    </div>
  );
}
