/**
 * LearnMentor Interactive Prototype v1.1
 *
 * Changelog (v1.0 → v1.1):
 * ─────────────────────────────────────────────────────────────
 * 1. [ImportPage] YouTube → Bilibili：URL 输入框、placeholder、
 *    示例链接、图标全部改为 B站；新增 PDF 拖拽上传区域，
 *    PDF 现在是 MVP 一等公民而非"即将上线"。
 * 2. [ImportPage] 加载动画文案从"提取视频字幕"改为区分视频/PDF
 *    两种来源的步骤描述。
 * 3. [WelcomePage] Landing 文案从"YouTube 链接"改为"B站视频链接
 *    或上传 PDF"。
 * 4. [MOCK_CHAT] 导师开场白从引用 Karpathy YouTube 视频改为
 *    引用 B站 3Blue1Brown 视频。
 * 5. [DiagnosticPage] 评估说明从"分析了 Karpathy 的视频"改为
 *    "分析了 3Blue1Brown 的 B站视频"。
 * 6. [LearningPathPage] 课程来源标注从"YouTube"改为"Bilibili"。
 * 7. [VideoLearningPage] 视频播放器说明改为 B站嵌入。
 * 8. [DashboardPage] 课程来源标注从"Karpathy · YouTube"改为
 *    "3Blue1Brown · Bilibili"。
 * 9. [Sidebar] 新增 Settings（设置）导航项，对应 /settings 路由。
 * 10.[App] 新增 settings 页面路由占位。
 * ─────────────────────────────────────────────────────────────
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { BookOpen, Play, MessageCircle, CheckCircle, ChevronRight, ChevronLeft, ArrowRight, Sparkles, Brain, Target, Clock, BarChart3, Zap, Send, X, Menu, User, Settings, LogOut, Home, Plus, Search, Star, TrendingUp, AlertCircle, Volume2, Pause, SkipForward, RotateCcw, Award, Flame, Calendar, Eye, FileText, Upload, Loader } from "lucide-react";

// ─── Theme ───────────────────────────────────────────────────
const colors = {
  bg: "#FAFAFA", surface: "#FFFFFF", surfaceAlt: "#F5F5F5",
  border: "#E5E5E5", borderLight: "#F0F0F0",
  text: "#171717", textSecondary: "#525252", textTertiary: "#A3A3A3",
  primary: "#2563EB", primaryLight: "#DBEAFE", primaryDark: "#1D4ED8",
  success: "#16A34A", successLight: "#DCFCE7",
  warning: "#D97706", warningLight: "#FEF3C7",
  error: "#DC2626", errorLight: "#FEE2E2",
  accent: "#7C3AED", accentLight: "#EDE9FE",
};

// ─── Helpers ─────────────────────────────────────────────────
const cn = (...classes) => classes.filter(Boolean).join(" ");
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

// ─── Mock Data ───────────────────────────────────────────────
const MOCK_PATH = [
  { id: 1, title: "Tokenization 基础", desc: "理解文本如何转换为数字", difficulty: "入门", duration: "15 min", status: "current", concepts: ["BPE", "Token", "Vocabulary"] },
  { id: 2, title: "Embedding 与向量空间", desc: "词向量的直觉与数学基础", difficulty: "入门", duration: "20 min", status: "locked", concepts: ["Word2Vec", "Cosine Similarity"] },
  { id: 3, title: "Self-Attention 机制", desc: "Transformer 的核心：注意力如何工作", difficulty: "进阶", duration: "30 min", status: "locked", concepts: ["Q/K/V", "Attention Score", "Multi-Head"] },
  { id: 4, title: "Transformer 架构全景", desc: "从 Encoder-Decoder 到 GPT", difficulty: "进阶", duration: "25 min", status: "locked", concepts: ["Layer Norm", "FFN", "Positional Encoding"] },
  { id: 5, title: "Training & Fine-tuning", desc: "预训练、微调与 RLHF", difficulty: "高级", duration: "35 min", status: "locked", concepts: ["Loss Function", "LoRA", "RLHF"] },
];

const MOCK_EXERCISES = [
  { id: 1, type: "choice", question: "在 BPE (Byte Pair Encoding) 算法中，合并操作的依据是什么？", options: ["字符出现频率最高", "相邻字符对出现频率最高", "字符的 Unicode 编码顺序", "随机选择字符对"], answer: 1, explanation: "BPE 通过统计语料库中相邻字符对（bigram）的出现频率，每次合并频率最高的字符对，逐步构建子词词汇表。" },
  { id: 2, type: "choice", question: "为什么现代 LLM 通常使用子词级别的 tokenization，而不是字符级别或单词级别？", options: ["计算速度更快", "平衡了词汇表大小和序列长度，同时能处理未知词", "实现起来更简单", "占用更少的存储空间"], answer: 1, explanation: "子词 tokenization 是一种折中方案：相比字符级别，序列更短（计算效率高）；相比单词级别，词汇表更小且能通过子词组合处理未见过的词（OOV 问题）。" },
];

const MOCK_CHAT = [
  { role: "mentor", content: "你好！我看到你正在学习 3Blue1Brown 的「深度学习之数学原理」系列视频。基于我们的初始评估，你对 Python 编程有不错的基础，但对 Transformer 架构还比较陌生。我建议我们从 Tokenization 开始——这是理解 LLM 的第一块拼图。准备好了吗？" },
];

// Adaptive diagnostic questions — generated from extracted video concepts
const DIAGNOSTIC_QUESTIONS = [
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

// ─── Components ──────────────────────────────────────────────

function Button({ children, variant = "primary", size = "md", className, ...props }) {
  const base = "inline-flex items-center justify-center font-medium transition-all duration-150 rounded-lg focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed";
  const variants = {
    primary: "bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800 shadow-sm",
    secondary: "bg-white text-gray-700 border border-gray-300 hover:bg-gray-50 active:bg-gray-100",
    ghost: "text-gray-600 hover:bg-gray-100 active:bg-gray-200",
    accent: "bg-violet-600 text-white hover:bg-violet-700 active:bg-violet-800 shadow-sm",
  };
  const sizes = { sm: "text-sm px-3 py-1.5 gap-1.5", md: "text-sm px-4 py-2 gap-2", lg: "text-base px-6 py-2.5 gap-2" };
  return <button className={cn(base, variants[variant], sizes[size], className)} {...props}>{children}</button>;
}

function Badge({ children, color = "blue" }) {
  const map = { blue: "bg-blue-50 text-blue-700", green: "bg-emerald-50 text-emerald-700", orange: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700", violet: "bg-violet-50 text-violet-700", gray: "bg-gray-100 text-gray-600" };
  return <span className={cn("inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium", map[color])}>{children}</span>;
}

function ProgressBar({ value, max = 100, className }) {
  return (
    <div className={cn("h-1.5 bg-gray-100 rounded-full overflow-hidden", className)}>
      <div className="h-full bg-blue-600 rounded-full transition-all duration-500" style={{ width: `${(value / max) * 100}%` }} />
    </div>
  );
}

function Card({ children, className, onClick, hover }) {
  return (
    <div onClick={onClick} className={cn("bg-white rounded-xl border border-gray-200", hover && "cursor-pointer hover:border-blue-300 hover:shadow-md transition-all duration-150", className)}>
      {children}
    </div>
  );
}

// ─── Sidebar ─────────────────────────────────────────────────
function Sidebar({ currentPage, onNavigate, collapsed, onToggle }) {
  const items = [
    { id: "dashboard", label: "首页", icon: Home },
    { id: "courses", label: "我的课程", icon: BookOpen },
    { id: "explore", label: "发现", icon: Search },
    { id: "progress", label: "学习统计", icon: BarChart3 },
    { id: "settings", label: "设置", icon: Settings },
  ];
  return (
    <aside className={cn("fixed left-0 top-0 h-full bg-white border-r border-gray-200 z-30 transition-all duration-200 flex flex-col", collapsed ? "w-16" : "w-56")}>
      <div className="flex items-center gap-2 px-4 h-14 border-b border-gray-100">
        <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0">
          <Brain className="w-4 h-4 text-white" />
        </div>
        {!collapsed && <span className="font-semibold text-gray-900 text-sm">LearnMentor</span>}
      </div>
      <nav className="flex-1 py-2 px-2 space-y-0.5">
        {items.map((item) => (
          <button key={item.id} onClick={() => onNavigate(item.id)} className={cn("w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors", currentPage === item.id ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-600 hover:bg-gray-50 hover:text-gray-900")}>
            <item.icon className="w-4 h-4 flex-shrink-0" />
            {!collapsed && <span>{item.label}</span>}
          </button>
        ))}
      </nav>
      <div className="p-2 border-t border-gray-100">
        <button onClick={onToggle} className="w-full flex items-center justify-center p-2 rounded-lg text-gray-400 hover:bg-gray-50 hover:text-gray-600">
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>
    </aside>
  );
}

// ─── Page: Welcome / Landing ─────────────────────────────────
function WelcomePage({ onStart }) {
  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="flex items-center justify-between px-6 h-14 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900">LearnMentor</span>
        </div>
        <Button variant="secondary" size="sm">登录</Button>
      </header>

      <main className="flex-1 flex items-center justify-center px-6">
        <div className="max-w-2xl text-center">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-medium mb-6">
            <Sparkles className="w-3 h-3" /> AI 驱动的个性化学习
          </div>
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight mb-4" style={{ lineHeight: 1.2 }}>
            把任何学习资料，<br />变成你的<span className="text-blue-600">私人导师</span>
          </h1>
          <p className="text-lg text-gray-500 mb-8 max-w-lg mx-auto" style={{ lineHeight: 1.6 }}>
            粘贴一个 B站视频链接或上传 PDF，LearnMentor 会为你生成个性化学习路径，用苏格拉底式引导帮你真正学会。
          </p>

          <div className="flex items-center justify-center gap-3 mb-12">
            <Button size="lg" onClick={onStart}>
              开始学习 <ArrowRight className="w-4 h-4" />
            </Button>
            <Button variant="secondary" size="lg">
              <Play className="w-4 h-4" /> 观看演示
            </Button>
          </div>

          <div className="grid grid-cols-3 gap-6 text-left">
            {[
              { icon: Zap, title: "3 分钟生成路径", desc: "粘贴链接后自动分析内容，按难度编排学习路径" },
              { icon: Brain, title: "它知道你哪里不会", desc: "练习中识别知识缺口，回溯前置知识重新讲解" },
              { icon: Target, title: "推着你往前走", desc: "苏格拉底式引导，不只回答问题，而是推进学习" },
            ].map((f, i) => (
              <div key={i} className="p-4 rounded-xl bg-gray-50 border border-gray-100">
                <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center mb-3">
                  <f.icon className="w-4 h-4 text-blue-600" />
                </div>
                <h3 className="font-semibold text-gray-900 text-sm mb-1">{f.title}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}

// ─── Page: Adaptive Diagnostic (based on video content) ──────
function DiagnosticPage({ onComplete }) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState([]);
  const [analyzing, setAnalyzing] = useState(false);

  const handleAnswer = async (idx) => {
    const next = [...answers, idx];
    setAnswers(next);
    if (step < DIAGNOSTIC_QUESTIONS.length - 1) {
      setStep(step + 1);
    } else {
      setAnalyzing(true);
      await delay(2200);
      onComplete(next);
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
                {i < 2 ? <CheckCircle className="w-4 h-4 text-green-500" /> : i === 2 ? <Loader className="w-4 h-4 text-blue-500 animate-spin" /> : <div className="w-4 h-4 rounded-full border border-gray-300" />}
                <span className={i < 2 ? "text-gray-500" : i === 2 ? "text-gray-900 font-medium" : "text-gray-400"}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const q = DIAGNOSTIC_QUESTIONS[step];
  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="flex items-center justify-between px-6 h-14 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900">LearnMentor</span>
        </div>
        <span className="text-xs text-gray-400">{step + 1} / {DIAGNOSTIC_QUESTIONS.length}</span>
      </header>

      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-lg">
          {/* Context banner: shows this is based on video content */}
          {step === 0 && (
            <div className="mb-6 p-3 rounded-xl bg-blue-50 border border-blue-100 flex items-start gap-2.5">
              <Sparkles className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-blue-800">基于内容的自适应评估</p>
                <p className="text-xs text-blue-600 mt-0.5">我已分析了 3Blue1Brown 的 B站视频，从中提取了 5 个核心概念。回答以下问题帮助我了解你的起点，以便跳过你已经会的、聚焦你不会的。</p>
              </div>
            </div>
          )}

          <div className="mb-8">
            <ProgressBar value={(step / DIAGNOSTIC_QUESTIONS.length) * 100} className="mb-6" />
            <div className="flex items-center gap-2 mb-2">
              <Badge color="violet">{q.concept}</Badge>
              <span className="text-xs text-gray-400">概念 {step + 1} / {DIAGNOSTIC_QUESTIONS.length}</span>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 leading-relaxed">{q.q}</h2>
          </div>
          <div className="space-y-2">
            {q.opts.map((opt, i) => (
              <button key={i} onClick={() => handleAnswer(i)} className="w-full text-left px-4 py-3 rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-all duration-150 text-sm text-gray-700 hover:text-blue-700">
                <div className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full border border-gray-300 flex items-center justify-center text-xs text-gray-400 flex-shrink-0 mt-0.5">{i + 1}</span>
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

// ─── Page: Import Resource ───────────────────────────────────
function ImportPage({ onImport }) {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [goal, setGoal] = useState(null);
  const [sourceType, setSourceType] = useState("bilibili"); // "bilibili" | "pdf"
  const [dragOver, setDragOver] = useState(false);
  const [pdfName, setPdfName] = useState("");

  const canSubmit = goal && (sourceType === "bilibili" ? url.trim() : pdfName);

  const handleImport = async () => {
    if (!canSubmit) return;
    setLoading(true);
    await delay(2500);
    onImport(sourceType === "bilibili" ? url : pdfName, goal);
  };

  const goals = [
    { id: "overview", label: "快速了解大意", icon: Eye, desc: "用最短时间抓住核心思想" },
    { id: "master", label: "系统掌握核心概念", icon: Brain, desc: "深入理解每个知识点" },
    { id: "apply", label: "实战应用", icon: Target, desc: "做项目、写代码、能上手" },
  ];

  const loadingSteps = sourceType === "bilibili"
    ? ["提取 B站视频字幕", "识别核心概念与前置依赖", "评估难度等级", "准备自适应评估题"]
    : ["解析 PDF 文档结构", "提取文本与代码块", "识别核心概念与前置依赖", "准备自适应评估题"];

  if (loading) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="text-center max-w-md">
          <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-4">
            <Loader className="w-6 h-6 text-blue-600 animate-spin" />
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">
            {sourceType === "bilibili" ? "正在分析视频内容..." : "正在分析 PDF 文档..."}
          </h2>
          <p className="text-sm text-gray-500 mb-1">分析完成后，我会出几道题来了解你的基础</p>
          <div className="space-y-3 mt-6 text-left bg-gray-50 rounded-xl p-4">
            {loadingSteps.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                {i < 2 ? <CheckCircle className="w-4 h-4 text-green-500" /> : i === 2 ? <Loader className="w-4 h-4 text-blue-500 animate-spin" /> : <div className="w-4 h-4 rounded-full border border-gray-300" />}
                <span className={i < 2 ? "text-gray-500" : i === 2 ? "text-gray-900 font-medium" : "text-gray-400"}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="flex items-center justify-between px-6 h-14 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900">LearnMentor</span>
        </div>
      </header>

      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-xl">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">导入学习资料</h1>
          <p className="text-sm text-gray-500 mb-8">粘贴 B站视频链接或上传 PDF，开始你的个性化学习之旅</p>

          {/* Source type tabs */}
          <div className="flex gap-2 mb-6">
            <button onClick={() => setSourceType("bilibili")}
              className={cn("flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg border text-sm font-medium transition-all",
                sourceType === "bilibili" ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-gray-300")}>
              <Play className="w-4 h-4" /> B站视频
            </button>
            <button onClick={() => setSourceType("pdf")}
              className={cn("flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg border text-sm font-medium transition-all",
                sourceType === "pdf" ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-gray-300")}>
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
              <button onClick={() => setUrl("https://www.bilibili.com/video/BV1gZ4y1F7hS")} className="mt-2 text-xs text-blue-600 hover:text-blue-700">
                试试看：3Blue1Brown - 深度学习之数学原理
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
                onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f?.type === "application/pdf") setPdfName(f.name); }}
                onClick={() => { const input = document.createElement("input"); input.type = "file"; input.accept = ".pdf"; input.onchange = (e) => { const f = e.target.files[0]; if (f) setPdfName(f.name); }; input.click(); }}
                className={cn("border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
                  dragOver ? "border-blue-400 bg-blue-50" : pdfName ? "border-green-400 bg-green-50" : "border-gray-300 hover:border-gray-400 hover:bg-gray-50")}
              >
                {pdfName ? (
                  <div className="flex items-center justify-center gap-2">
                    <FileText className="w-5 h-5 text-green-600" />
                    <span className="text-sm font-medium text-green-700">{pdfName}</span>
                    <button onClick={(e) => { e.stopPropagation(); setPdfName(""); }} className="text-gray-400 hover:text-gray-600">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <>
                    <Upload className={cn("w-8 h-8 mx-auto mb-2", dragOver ? "text-blue-500" : "text-gray-400")} />
                    <p className="text-sm text-gray-600 mb-1">拖拽 PDF 到这里，或点击选择文件</p>
                    <p className="text-xs text-gray-400">支持论文、教材、技术文档等</p>
                  </>
                )}
              </div>
            </div>
          )}

          <div className="mb-8">
            <label className="block text-sm font-medium text-gray-700 mb-3">选择学习目标</label>
            <div className="grid grid-cols-3 gap-3">
              {goals.map((g) => (
                <button key={g.id} onClick={() => setGoal(g.id)} className={cn("p-4 rounded-xl border text-left transition-all duration-150", goal === g.id ? "border-blue-500 bg-blue-50 ring-1 ring-blue-500" : "border-gray-200 hover:border-gray-300")}>
                  <g.icon className={cn("w-5 h-5 mb-2", goal === g.id ? "text-blue-600" : "text-gray-400")} />
                  <div className={cn("text-sm font-medium mb-0.5", goal === g.id ? "text-blue-700" : "text-gray-700")}>{g.label}</div>
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

// ─── Page: Learning Path ─────────────────────────────────────
function LearningPathPage({ onStartLesson, onBack }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <button onClick={onBack} className="text-xs text-gray-400 hover:text-gray-600 mb-2 flex items-center gap-1">
            <ChevronLeft className="w-3 h-3" /> 返回
          </button>
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

        <div className="space-y-3">
          {MOCK_PATH.map((section, idx) => (
            <Card key={section.id} hover={section.status === "current"} onClick={section.status === "current" ? () => onStartLesson(section) : undefined}
              className={cn("p-4", section.status === "current" && "border-blue-300 ring-1 ring-blue-100")}>
              <div className="flex items-center gap-4">
                <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold flex-shrink-0",
                  section.status === "current" ? "bg-blue-600 text-white" : section.status === "completed" ? "bg-green-100 text-green-600" : "bg-gray-100 text-gray-400")}>
                  {section.status === "completed" ? <CheckCircle className="w-5 h-5" /> : idx + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <h3 className={cn("text-sm font-semibold", section.status === "locked" ? "text-gray-400" : "text-gray-900")}>{section.title}</h3>
                    <Badge color={section.difficulty === "入门" ? "green" : section.difficulty === "进阶" ? "orange" : "red"}>{section.difficulty}</Badge>
                  </div>
                  <p className={cn("text-xs mb-2", section.status === "locked" ? "text-gray-300" : "text-gray-500")}>{section.desc}</p>
                  <div className="flex items-center gap-2 flex-wrap">
                    {section.concepts.map((c) => (
                      <span key={c} className={cn("px-1.5 py-0.5 rounded text-xs", section.status === "locked" ? "bg-gray-50 text-gray-300" : "bg-gray-100 text-gray-500")}>{c}</span>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className={cn("text-xs", section.status === "locked" ? "text-gray-300" : "text-gray-400")}>{section.duration}</span>
                  {section.status === "current" && <ArrowRight className="w-4 h-4 text-blue-600" />}
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Page: Video Learning Shell ──────────────────────────────
function VideoLearningPage({ section, onExercise, onBack }) {
  const [messages, setMessages] = useState(MOCK_CHAT);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [activeTab, setActiveTab] = useState("chat");
  const [videoProgress, setVideoProgress] = useState(35);
  const chatEndRef = useRef(null);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || typing) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setTyping(true);
    await delay(1500);

    const mentorResponses = [
      "这是个很好的问题！在回答之前，让我先问你：你觉得为什么我们需要把文字转换成数字？计算机本身能直接\"理解\"文字吗？试着从计算机底层的角度想一想。",
      "你的思路方向是对的！不过让我再追问一下——你提到计算机只能处理数字，那为什么不简单地给每个字一个编号（比如 Unicode）就行了？为什么还需要 Tokenization 这么复杂的过程？",
      "非常好的分析！你提到了一个关键点。让我们看看视频 23:15 处 3Blue1Brown 的解释，他用了一个非常直观的可视化。看完那段后我们继续讨论。",
    ];

    setMessages((prev) => [
      ...prev,
      { role: "mentor", content: mentorResponses[messages.length % mentorResponses.length] },
    ]);
    setTyping(false);
  };

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* Top bar */}
      <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-4 flex-shrink-0">
        <button onClick={onBack} className="text-gray-400 hover:text-gray-600">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-900 truncate">第 1 章：{section?.title || "Tokenization 基础"}</span>
            <Badge color="green">入门</Badge>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Clock className="w-3.5 h-3.5" />
          <span>15 min 剩余</span>
        </div>
        <Button variant="accent" size="sm" onClick={onExercise}>
          <CheckCircle className="w-3.5 h-3.5" /> 开始练习
        </Button>
      </header>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Video */}
        <div className="w-3/5 flex flex-col border-r border-gray-200">
          {/* Video player mockup */}
          <div className="bg-gray-900 aspect-video relative flex-shrink-0">
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <div className="w-16 h-16 rounded-full bg-white/20 flex items-center justify-center mb-2 mx-auto backdrop-blur-sm">
                  <Play className="w-8 h-8 text-white ml-1" />
                </div>
                <p className="text-white/60 text-xs">深度学习之数学原理 — 3Blue1Brown · Bilibili</p>
              </div>
            </div>
            {/* Video controls */}
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-3">
              <div className="h-1 bg-white/20 rounded-full mb-2 cursor-pointer">
                <div className="h-full bg-blue-500 rounded-full" style={{ width: `${videoProgress}%` }} />
              </div>
              <div className="flex items-center justify-between text-white/80 text-xs">
                <div className="flex items-center gap-3">
                  <Play className="w-3.5 h-3.5 cursor-pointer" />
                  <span>12:35 / 35:42</span>
                </div>
                <div className="flex items-center gap-3">
                  <Volume2 className="w-3.5 h-3.5 cursor-pointer" />
                  <span className="cursor-pointer">1x</span>
                </div>
              </div>
            </div>
          </div>

          {/* Chapter navigation */}
          <div className="flex-1 overflow-y-auto p-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">章节导航</h3>
            <div className="space-y-1">
              {[
                { time: "0:00", title: "什么是 Tokenization", active: true, done: true },
                { time: "8:20", title: "BPE 算法原理", active: true, done: false },
                { time: "18:45", title: "Vocabulary 构建", active: false, done: false },
                { time: "28:10", title: "特殊 Token 处理", active: false, done: false },
              ].map((ch, i) => (
                <div key={i} className={cn("flex items-center gap-3 px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors",
                  ch.active && !ch.done ? "bg-blue-50 text-blue-700 font-medium" : ch.done ? "text-gray-400" : "text-gray-500 hover:bg-gray-50")}>
                  {ch.done ? <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" /> : <Play className="w-4 h-4 flex-shrink-0" />}
                  <span className="text-xs text-gray-400 w-10 flex-shrink-0">{ch.time}</span>
                  <span className="flex-1">{ch.title}</span>
                </div>
              ))}
            </div>

            <div className="mt-6 p-3 rounded-xl bg-amber-50 border border-amber-100">
              <div className="flex items-center gap-2 text-xs font-medium text-amber-700 mb-1">
                <AlertCircle className="w-3.5 h-3.5" /> 系统检测到难点
              </div>
              <p className="text-xs text-amber-600">你在 8:20-12:35 区间回看了 3 次，这可能是难点。需要我用不同方式讲解 BPE 算法吗？</p>
            </div>
          </div>
        </div>

        {/* Right: Chat / Notes */}
        <div className="w-2/5 flex flex-col">
          {/* Tabs */}
          <div className="flex border-b border-gray-200 px-4 flex-shrink-0">
            {[
              { id: "chat", label: "导师问答", icon: MessageCircle },
              { id: "notes", label: "笔记", icon: FileText },
              { id: "concepts", label: "概念", icon: BookOpen },
            ].map((tab) => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                className={cn("flex items-center gap-1.5 px-3 py-3 text-xs font-medium border-b-2 transition-colors",
                  activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-gray-400 hover:text-gray-600")}>
                <tab.icon className="w-3.5 h-3.5" /> {tab.label}
              </button>
            ))}
          </div>

          {/* Chat */}
          {activeTab === "chat" && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.map((msg, i) => (
                  <div key={i} className={cn("flex gap-2", msg.role === "user" ? "flex-row-reverse" : "")}>
                    {msg.role === "mentor" && (
                      <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                        <Brain className="w-3.5 h-3.5 text-blue-600" />
                      </div>
                    )}
                    <div className={cn("max-w-[85%] px-3 py-2 rounded-xl text-sm leading-relaxed",
                      msg.role === "user" ? "bg-blue-600 text-white rounded-br-sm" : "bg-gray-100 text-gray-800 rounded-bl-sm")}>
                      {msg.content}
                    </div>
                  </div>
                ))}
                {typing && (
                  <div className="flex gap-2">
                    <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                      <Brain className="w-3.5 h-3.5 text-blue-600" />
                    </div>
                    <div className="bg-gray-100 rounded-xl rounded-bl-sm px-3 py-2">
                      <div className="flex gap-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "300ms" }} />
                      </div>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Quick prompts */}
              <div className="px-4 pb-2 flex gap-2 flex-wrap flex-shrink-0">
                {["这个概念能再解释一下吗？", "给我举个例子", "这和前面学的有什么关系？"].map((prompt) => (
                  <button key={prompt} onClick={() => { setInput(prompt); }}
                    className="px-2.5 py-1 rounded-full border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors">
                    {prompt}
                  </button>
                ))}
              </div>

              {/* Input */}
              <div className="p-4 border-t border-gray-100 flex-shrink-0">
                <div className="flex gap-2">
                  <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                    placeholder="向导师提问..."
                    className="flex-1 px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  <Button size="md" onClick={sendMessage} disabled={!input.trim() || typing}>
                    <Send className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Notes tab */}
          {activeTab === "notes" && (
            <div className="flex-1 p-4 overflow-y-auto">
              <div className="text-center py-8">
                <FileText className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-400">学习过程中的笔记会自动保存在这里</p>
                <Button variant="secondary" size="sm" className="mt-3">
                  <Plus className="w-3.5 h-3.5" /> 添加笔记
                </Button>
              </div>
            </div>
          )}

          {/* Concepts tab */}
          {activeTab === "concepts" && (
            <div className="flex-1 p-4 overflow-y-auto space-y-3">
              {["BPE (Byte Pair Encoding)", "Token", "Vocabulary", "Subword"].map((concept, i) => (
                <div key={i} className="p-3 rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-gray-900">{concept}</span>
                    <Badge color={i < 2 ? "green" : "gray"}>{i < 2 ? "学习中" : "未开始"}</Badge>
                  </div>
                  {i < 2 && <ProgressBar value={i === 0 ? 60 : 30} className="mt-2" />}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Page: Exercise ──────────────────────────────────────────
function ExercisePage({ onComplete, onBack }) {
  const [current, setCurrent] = useState(0);
  const [selected, setSelected] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const [results, setResults] = useState([]);
  const [showFeedback, setShowFeedback] = useState(false);

  const ex = MOCK_EXERCISES[current];
  const isCorrect = selected === ex.answer;

  const handleSubmit = () => {
    setSubmitted(true);
    setResults([...results, { correct: isCorrect, selected }]);
  };

  const handleNext = () => {
    if (current < MOCK_EXERCISES.length - 1) {
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
          <div className={cn("w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4", score === results.length ? "bg-green-100" : "bg-amber-100")}>
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
            <Button variant="secondary" className="flex-1" onClick={onBack}>回到课程</Button>
            <Button className="flex-1" onClick={onComplete}>
              {score === results.length ? "下一章" : "复习薄弱点"}
              <ArrowRight className="w-4 h-4" />
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 h-12 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-gray-400 hover:text-gray-600"><ChevronLeft className="w-4 h-4" /></button>
          <span className="text-sm font-medium text-gray-900">章节练习：Tokenization 基础</span>
        </div>
        <span className="text-xs text-gray-400">{current + 1} / {MOCK_EXERCISES.length}</span>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8">
        <ProgressBar value={((current + (submitted ? 1 : 0)) / MOCK_EXERCISES.length) * 100} className="mb-8" />

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
              <button key={i} disabled={submitted} onClick={() => setSelected(i)}
                className={cn("w-full text-left px-4 py-3 rounded-xl border transition-all duration-150 text-sm", style)}>
                <div className="flex items-start gap-3">
                  <span className={cn("w-6 h-6 rounded-full border flex items-center justify-center text-xs font-medium flex-shrink-0 mt-0.5",
                    submitted && i === ex.answer ? "bg-green-500 text-white border-green-500" :
                    submitted && i === selected && !isCorrect ? "bg-red-500 text-white border-red-500" :
                    i === selected ? "bg-blue-500 text-white border-blue-500" : "border-gray-300 text-gray-500")}>
                    {String.fromCharCode(65 + i)}
                  </span>
                  <span className={cn(submitted && i !== ex.answer && i !== selected && "text-gray-400")}>{opt}</span>
                </div>
              </button>
            );
          })}
        </div>

        {submitted && (
          <Card className={cn("p-4 mb-6", isCorrect ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200")}>
            <div className="flex items-start gap-2">
              {isCorrect ? <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" /> : <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />}
              <div>
                <p className={cn("text-sm font-medium mb-1", isCorrect ? "text-green-800" : "text-red-800")}>
                  {isCorrect ? "回答正确！" : "还不太对"}
                </p>
                <p className={cn("text-sm leading-relaxed", isCorrect ? "text-green-700" : "text-red-700")}>{ex.explanation}</p>
              </div>
            </div>
          </Card>
        )}

        <div className="flex justify-end">
          {!submitted ? (
            <Button onClick={handleSubmit} disabled={selected === null}>提交答案</Button>
          ) : (
            <Button onClick={handleNext}>
              {current < MOCK_EXERCISES.length - 1 ? "下一题" : "查看结果"} <ArrowRight className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Page: Dashboard ─────────────────────────────────────────
function DashboardPage({ onContinue, onImport }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-6 py-6">
        {/* Greeting */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-gray-900">欢迎回来 👋</h1>
          <p className="text-sm text-gray-500 mt-1">你已经连续学习 3 天了，继续保持！</p>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { icon: Flame, label: "连续天数", value: "3 天", color: "text-orange-500", bg: "bg-orange-50" },
            { icon: Clock, label: "本周学习", value: "2.5 h", color: "text-blue-500", bg: "bg-blue-50" },
            { icon: Target, label: "概念掌握", value: "4 / 12", color: "text-green-500", bg: "bg-green-50" },
            { icon: TrendingUp, label: "正确率", value: "72%", color: "text-violet-500", bg: "bg-violet-50" },
          ].map((stat, i) => (
            <Card key={i} className="p-4">
              <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center mb-2", stat.bg)}>
                <stat.icon className={cn("w-4 h-4", stat.color)} />
              </div>
              <p className="text-xl font-bold text-gray-900">{stat.value}</p>
              <p className="text-xs text-gray-500">{stat.label}</p>
            </Card>
          ))}
        </div>

        {/* Today's suggestion */}
        <Card className="p-4 mb-6 border-blue-200 bg-gradient-to-r from-blue-50 to-white">
          <div className="flex items-center justify-between">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
                <Brain className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">今日建议</p>
                <p className="text-sm text-gray-600 mt-0.5">继续学习「Tokenization 基础」——你上次学到了 BPE 算法部分。今天完成这一章的练习后，我们就可以进入 Embedding 了。</p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="text-xs text-gray-400 flex items-center gap-1"><Clock className="w-3 h-3" /> 预计 15 分钟</span>
                  <span className="text-xs text-gray-400 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> 2 道练习待完成</span>
                </div>
              </div>
            </div>
            <Button onClick={onContinue}>继续学习 <ArrowRight className="w-4 h-4" /></Button>
          </div>
        </Card>

        {/* Spaced repetition reminder */}
        <Card className="p-4 mb-6 border-amber-200 bg-amber-50">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <RotateCcw className="w-5 h-5 text-amber-600" />
              <div>
                <p className="text-sm font-medium text-amber-800">间隔复习提醒</p>
                <p className="text-xs text-amber-700 mt-0.5">「BPE 算法原理」的知识点即将进入遗忘期，建议今天复习</p>
              </div>
            </div>
            <Button variant="secondary" size="sm">开始复习</Button>
          </div>
        </Card>

        {/* Active courses */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">进行中的课程</h2>
          <Button variant="ghost" size="sm" onClick={onImport}><Plus className="w-3.5 h-3.5" /> 导入新资料</Button>
        </div>

        <Card className="p-4 mb-6" hover onClick={onContinue}>
          <div className="flex items-center gap-4">
            <div className="w-16 h-10 rounded-lg bg-gray-900 flex items-center justify-center flex-shrink-0">
              <Play className="w-4 h-4 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-semibold text-gray-900">深度学习之数学原理</h3>
              <p className="text-xs text-gray-500">3Blue1Brown · Bilibili · 5 章节 · 12 概念</p>
              <div className="mt-2 flex items-center gap-2">
                <ProgressBar value={20} className="flex-1" />
                <span className="text-xs text-gray-400">20%</span>
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
          </div>
        </Card>

        {/* Weekly activity */}
        <h2 className="text-sm font-semibold text-gray-900 mb-4">本周学习活动</h2>
        <Card className="p-4">
          <div className="flex items-end justify-between gap-2 h-24">
            {["一", "二", "三", "四", "五", "六", "日"].map((day, i) => {
              const heights = [40, 65, 30, 80, 50, 0, 0];
              const isToday = i === 3;
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1">
                  <div className="w-full flex items-end justify-center" style={{ height: 80 }}>
                    <div className={cn("w-full max-w-[24px] rounded-t-md transition-all", isToday ? "bg-blue-500" : heights[i] > 0 ? "bg-blue-200" : "bg-gray-100")}
                      style={{ height: heights[i] || 4 }} />
                  </div>
                  <span className={cn("text-xs", isToday ? "text-blue-600 font-medium" : "text-gray-400")}>{day}</span>
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ─── App ─────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("welcome");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [currentSection, setCurrentSection] = useState(null);
  const [diagnosed, setDiagnosed] = useState(false);

  const showSidebar = ["dashboard", "courses", "explore", "progress", "settings"].includes(page);

  const navigateTo = useCallback((p) => setPage(p), []);

  return (
    <div className="font-sans antialiased" style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif' }}>
      {showSidebar && <Sidebar currentPage={page} onNavigate={navigateTo} collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} />}

      <main className={cn(showSidebar && (sidebarCollapsed ? "ml-16" : "ml-56"), "transition-all duration-200")}>
        {page === "welcome" && (
          <WelcomePage onStart={() => setPage("import")} />
        )}

        {page === "import" && (
          <ImportPage onImport={() => setPage("diagnostic")} />
        )}

        {page === "diagnostic" && (
          <DiagnosticPage onComplete={() => { setDiagnosed(true); setPage("path"); }} />
        )}

        {page === "path" && (
          <LearningPathPage onStartLesson={(s) => { setCurrentSection(s); setPage("learn"); }} onBack={() => setPage("dashboard")} />
        )}

        {page === "learn" && (
          <VideoLearningPage section={currentSection} onExercise={() => setPage("exercise")} onBack={() => setPage("path")} />
        )}

        {page === "exercise" && (
          <ExercisePage onComplete={() => setPage("dashboard")} onBack={() => setPage("learn")} />
        )}

        {page === "dashboard" && (
          <DashboardPage onContinue={() => setPage("path")} onImport={() => setPage("import")} />
        )}

        {page === "courses" && (
          <DashboardPage onContinue={() => setPage("path")} onImport={() => setPage("import")} />
        )}

        {page === "explore" && (
          <div className="p-6 text-center text-gray-400 text-sm pt-20">发现页面 — 开发中</div>
        )}

        {page === "progress" && (
          <div className="p-6 text-center text-gray-400 text-sm pt-20">学习统计 — 开发中</div>
        )}

        {page === "settings" && (
          <div className="max-w-3xl mx-auto px-6 py-6">
            <h1 className="text-xl font-bold text-gray-900 mb-6">设置</h1>
            <Card className="p-6 mb-4">
              <h2 className="text-sm font-semibold text-gray-900 mb-4">LLM 模型配置</h2>
              <div className="space-y-4">
                {[
                  { label: "主交互模型", value: "Claude Sonnet 4", desc: "用于导师对话" },
                  { label: "轻量模型", value: "Claude Haiku 4", desc: "用于内容分析" },
                  { label: "Embedding 模型", value: "text-embedding-3-small", desc: "用于向量检索" },
                ].map((item, i) => (
                  <div key={i} className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{item.label}</p>
                      <p className="text-xs text-gray-500">{item.desc}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-gray-700">{item.value}</span>
                      <ChevronRight className="w-4 h-4 text-gray-400" />
                    </div>
                  </div>
                ))}
              </div>
              <Button variant="secondary" size="sm" className="mt-4">
                <Plus className="w-3.5 h-3.5" /> 添加 Provider
              </Button>
            </Card>
          </div>
        )}
      </main>
    </div>
  );
}
