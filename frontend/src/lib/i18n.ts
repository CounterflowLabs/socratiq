"use client";

import { create } from "zustand";

export type Lang = "zh" | "en";
export type Density = "spacious" | "balanced" | "dense";

const dict = {
  zh: {
    appTagline: "AI 苏格拉底式学习平台",
    nav: {
      dashboard: "今日",
      import: "导入",
      sources: "资料库",
      graph: "知识图谱",
      settings: "设置",
      system: "设计系统",
      recent: "最近",
    },
    common: {
      new: "新建",
      open: "打开",
      continue: "继续学习",
      review: "今日复习",
      allDone: "今日复习已完成",
      myCourses: "我的课程",
      processing: "处理中",
      tasks: "任务",
      lessons: "课文",
      concepts: "概念",
      exercises: "练习",
      progress: "进度",
      ago: "前",
      enterCourse: "进入课程",
      retry: "重试",
      close: "关闭",
      cancel: "取消",
      save: "保存",
      apply: "应用",
      unit: "单元",
      lesson: "课文",
      lab: "实验",
      mentor: "导师",
      easy: "轻松",
      good: "良好",
      hard: "困难",
      forgot: "忘了",
      askAnything: "提问任何关于这节课的问题…",
      yesterday: "昨天",
      today: "今天",
      thisWeek: "本周",
      back: "返回",
      filter: "筛选",
      search: "搜索",
      loading: "加载中…",
      empty: "暂无内容",
      next: "下一节",
      previous: "上一节",
      doExercise: "做练习",
      due: "到期",
      tapToReveal: "点击显示问题",
      revealAnswer: "查看答案",
      hideAnswer: "收起答案",
      noResults: "没有结果",
    },
    dashboard: {
      title: "今日",
      subtitle: "继续你昨天停下的地方。",
      pickup: "继续上次",
      reviewBlurb: "基于 SM-2 算法 · 长期记忆训练",
      empty: "还没有课程",
      emptyHint: "粘贴一个 B站 / YouTube 视频，或上传 PDF。Socratiq 会分析内容，生成结构化课程与练习。",
      importFirst: "导入第一份资料",
      conceptNeighborhood: "当前概念邻域",
      loadFailed: "课程加载失败",
    },
    import: {
      title: "导入新资料",
      subtitle: "一切学习的起点。从一段视频或一份文档开始。",
      placeholder: "粘贴 B站 / YouTube 链接，或拖入 PDF",
      pasteUrl: "从链接导入",
      uploadFile: "上传文件",
      writeText: "粘贴文本",
      analyze: "开始分析",
      sample: "或试试这些示例",
      supports: "支持",
      pipeline: {
        title: "分析流程",
        s1: "提取字幕",
        s2: "分析内容结构",
        s3: "生成学习路径",
        s4: "组装课程",
      },
      tips: "提示",
      tip1: "我们优先复用已有字幕，无字幕时使用 Whisper。",
      tip2: "PDF 与 Markdown 文档将按章节自动切分。",
      tip3: "导入完成后会做一次 5 分钟的入学诊断。",
      dropHere: "拖入 PDF / Markdown / .txt",
      dropHint: "或点击选择文件 — 单个最大 50 MB",
      textPlaceholder: "粘贴一段文字、笔记或论文摘要…",
      bilibiliBlocked: "导入 B 站视频需要先登录 B 站账号才能抓取字幕。",
      bilibiliConfigure: "前往设置登录 →",
      ready: "准备好了。",
      statusProcessing: "处理中",
      statusFailed: "失败",
      statusDone: "已完成",
      pipelineStartedTitle: "已开始解析",
      pipelineStartedHint: "你可以离开这个页面，处理状态会出现在资料库。",
      pipelineFailedTitle: "导入失败",
      pipelineFailedHint: "下面的阶段标出了出错的位置，重试或前往资料列表查看细节。",
      pipelineDoneTitle: "处理完成",
      pipelineDoneHint: "可以前往课程开始学习。",
      viewSources: "查看资料列表",
      importAnother: "继续导入",
      retryImport: "重试导入",
      openCourse: "打开课程",
      errorUnknown: "导入失败，但后端没有返回具体原因。",
    },
    sources: {
      title: "资料库",
      subtitle: "所有导入过的源材料 — 章节、字幕、嵌入向量、引用都从这里开始。",
      colName: "名称",
      colLength: "长度",
      colImported: "导入日期",
      colCited: "引用",
      empty: "还没有导入资料",
      emptyHint: "导入视频或 PDF 开始学习",
      filterAll: "全部状态",
      filterReady: "已完成",
      filterProcessing: "处理中",
      filterError: "失败",
    },
    path: {
      eyebrow: "课程路径",
      youAreHere: "当前位置",
      readLesson: "阅读课文",
      doExercise: "做练习",
      runLab: "进入 Lab",
      mentorChat: "与导师对话",
      thisWeek: "本周节奏",
      regenerate: "重新生成",
    },
    learn: {
      lesson: "课文",
      mentor: "苏格拉底导师",
      mentorBlurb: "不直接给答案 · 引导你自己思考",
      memory: "5 层记忆",
      lab: "Lab",
      askPlaceholder: "问导师一个问题…",
      thinking: "导师正在思考…",
      sources: "本节引用",
      outline: "本课大纲",
      exercises: "本节练习",
      remembers: "记得",
      shaky: "生疏",
      suggest: "建议提问",
      citeLesson: "引用本节",
      videoSource: "原视频",
      pdfSource: "原 PDF",
      references: "参考资料",
      openTutor: "打开 AI 导师",
      currentLesson: "当前学习",
      backToCourse: "返回课程路径",
      backHome: "返回首页",
      progressLabel: (a: number, b: number) => `进度 ${a}/${b}`,
      preparing: "准备中",
      sectionsCount: (n: number) => `${n} 个章节`,
      knowledgeFragments: (n: number) => `${n} 个知识片段`,
      thisLessonOutline: "本节脉络",
    },
    graph: {
      title: "知识图谱",
      subtitle: "你已经接触过的概念与它们之间的关系。",
      total: "概念总数",
      mastered: "已掌握",
      learning: "学习中",
      seen: "已接触",
      legend: "图例",
      hint: "将鼠标悬停在节点上以查看详细信息。",
      concept: "概念",
    },
    settings: {
      title: "设置",
      sections: {
        account: "账户",
        llm: "LLM 提供商",
        appearance: "外观",
        sources: "数据源",
        privacy: "隐私",
        advanced: "高级",
      },
      llmDesc: "配置一个或多个 LLM 后端。Ollama 完全本地、免费。",
      addProvider: "添加模型",
      themeLabel: "主题",
      langLabel: "界面语言",
      densityLabel: "密度",
      themeLight: "亮",
      themeDark: "暗",
      themeSystem: "系统",
      densitySpacious: "宽松",
      densityBalanced: "平衡",
      densityDense: "紧凑",
    },
    system: {
      title: "设计系统",
      subtitle: "Socratiq UI v2 — 排版、色彩、图标、组件。",
      type: "排版",
      color: "色彩",
      icons: "图标",
      components: "组件",
      mark: "标志",
      markCaption:
        "一个开放的 Q — 圆圈是探询的边界，里面是被持有的思考（点），而尾巴是离开的答案。代表「问」产生「答」的过程。",
    },
  },
  en: {
    appTagline: "AI tutor — by Socratic dialogue",
    nav: {
      dashboard: "Today",
      import: "Import",
      sources: "Library",
      graph: "Graph",
      settings: "Settings",
      system: "Design system",
      recent: "Recent",
    },
    common: {
      new: "New",
      open: "Open",
      continue: "Continue",
      review: "Today's review",
      allDone: "All caught up",
      myCourses: "Your courses",
      processing: "Processing",
      tasks: "Tasks",
      lessons: "lessons",
      concepts: "concepts",
      exercises: "exercises",
      progress: "Progress",
      ago: "ago",
      enterCourse: "Open course",
      retry: "Retry",
      close: "Dismiss",
      cancel: "Cancel",
      save: "Save",
      apply: "Apply",
      unit: "Unit",
      lesson: "Lesson",
      lab: "Lab",
      mentor: "Mentor",
      easy: "Easy",
      good: "Good",
      hard: "Hard",
      forgot: "Forgot",
      askAnything: "Ask anything about this lesson…",
      yesterday: "Yesterday",
      today: "Today",
      thisWeek: "This week",
      back: "Back",
      filter: "Filter",
      search: "Search",
      loading: "Loading…",
      empty: "Nothing here yet",
      next: "Next",
      previous: "Previous",
      doExercise: "Do exercise",
      due: "Due",
      tapToReveal: "Tap to reveal",
      revealAnswer: "Show answer",
      hideAnswer: "Hide answer",
      noResults: "No results",
    },
    dashboard: {
      title: "Today",
      subtitle: "Pick up where you left off yesterday.",
      pickup: "Continue",
      reviewBlurb: "SM-2 spaced repetition · long-term retention",
      empty: "No courses yet",
      emptyHint: "Paste a YouTube or Bilibili link, or upload a PDF. Socratiq analyzes the content and generates a structured course with exercises.",
      importFirst: "Import your first source",
      conceptNeighborhood: "Concept neighborhood",
      loadFailed: "Failed to load courses",
    },
    import: {
      title: "Import a source",
      subtitle: "Where every course begins. From a video or a document.",
      placeholder: "Paste a YouTube / Bilibili link, or drop a PDF",
      pasteUrl: "From URL",
      uploadFile: "Upload",
      writeText: "Paste text",
      analyze: "Analyze",
      sample: "Or try a sample",
      supports: "Supports",
      pipeline: {
        title: "Pipeline",
        s1: "Fetch transcript",
        s2: "Analyze structure",
        s3: "Plan learning path",
        s4: "Assemble course",
      },
      tips: "Notes",
      tip1: "Existing subtitles are reused; otherwise we run Whisper.",
      tip2: "PDFs and Markdown are split by chapter automatically.",
      tip3: "A 5-minute cold-start diagnostic runs before the first lesson.",
      dropHere: "Drop a PDF / Markdown / .txt",
      dropHint: "or click to choose — 50 MB max per file",
      textPlaceholder: "Paste an article, notes, or paper abstract…",
      bilibiliBlocked: "Importing Bilibili videos requires a Bilibili login to fetch subtitles.",
      bilibiliConfigure: "Configure in Settings →",
      ready: "Ready when you are.",
      statusProcessing: "processing",
      statusFailed: "failed",
      statusDone: "done",
      pipelineStartedTitle: "Pipeline started",
      pipelineStartedHint: "You can leave this page — progress shows up in the Library.",
      pipelineFailedTitle: "Import failed",
      pipelineFailedHint: "The failing stage is marked below. Retry or open the library for details.",
      pipelineDoneTitle: "Ready",
      pipelineDoneHint: "Open the course to start learning.",
      viewSources: "View source library",
      importAnother: "Import another",
      retryImport: "Retry",
      openCourse: "Open course",
      errorUnknown: "Import failed, but the backend did not return a reason.",
    },
    sources: {
      title: "Library",
      subtitle: "Every source you've imported — chapters, transcripts, embeddings, citations all start here.",
      colName: "Name",
      colLength: "Length",
      colImported: "Imported",
      colCited: "Cited",
      empty: "No sources imported yet",
      emptyHint: "Import a video or a PDF to get started.",
      filterAll: "All states",
      filterReady: "Ready",
      filterProcessing: "Processing",
      filterError: "Failed",
    },
    path: {
      eyebrow: "Course path",
      youAreHere: "You are here",
      readLesson: "Read lesson",
      doExercise: "Do exercise",
      runLab: "Open lab",
      mentorChat: "Talk to mentor",
      thisWeek: "This week",
      regenerate: "Regenerate",
    },
    learn: {
      lesson: "Lesson",
      mentor: "Socratic mentor",
      mentorBlurb: "Guides your thinking — never gives the answer",
      memory: "5-layer memory",
      lab: "Lab",
      askPlaceholder: "Ask the mentor…",
      thinking: "Mentor is thinking…",
      sources: "Cited in this lesson",
      outline: "Outline",
      exercises: "Exercises",
      remembers: "remembers",
      shaky: "shaky",
      suggest: "Suggest",
      citeLesson: "Cite lesson",
      videoSource: "Source video",
      pdfSource: "Source PDF",
      references: "References",
      openTutor: "Open AI tutor",
      currentLesson: "Current lesson",
      backToCourse: "Back to course path",
      backHome: "Back to home",
      progressLabel: (a: number, b: number) => `${a} / ${b}`,
      preparing: "Preparing",
      sectionsCount: (n: number) => `${n} sections`,
      knowledgeFragments: (n: number) => `${n} fragments`,
      thisLessonOutline: "This lesson",
    },
    graph: {
      title: "Knowledge graph",
      subtitle: "Concepts you've touched and how they relate.",
      total: "Total concepts",
      mastered: "Mastered",
      learning: "Learning",
      seen: "Encountered",
      legend: "Legend",
      hint: "Hover a node to inspect.",
      concept: "Concept",
    },
    settings: {
      title: "Settings",
      sections: {
        account: "Account",
        llm: "LLM providers",
        appearance: "Appearance",
        sources: "Data sources",
        privacy: "Privacy",
        advanced: "Advanced",
      },
      llmDesc: "Configure one or more LLM backends. Ollama runs fully local, no key needed.",
      addProvider: "Add model",
      themeLabel: "Theme",
      langLabel: "Language",
      densityLabel: "Density",
      themeLight: "Light",
      themeDark: "Dark",
      themeSystem: "System",
      densitySpacious: "Spacious",
      densityBalanced: "Balanced",
      densityDense: "Dense",
    },
    system: {
      title: "Design system",
      subtitle: "Socratiq UI v2 — type, color, icons, components.",
      type: "Typography",
      color: "Color",
      icons: "Icons",
      components: "Components",
      mark: "Mark",
      markCaption: "An open Q — the circle is the boundary of inquiry, the dot is the thought held within it, the tail is the answer leaving. The motion of question producing answer.",
    },
  },
} as const;

type Dict = typeof dict.zh;
type DotKeys<T, P extends string = ""> = T extends object
  ? { [K in keyof T & string]: T[K] extends (...args: never[]) => unknown
      ? `${P}${K}`
      : T[K] extends object
        ? DotKeys<T[K], `${P}${K}.`>
        : `${P}${K}` }[keyof T & string]
  : never;

export type TranslationKey = DotKeys<Dict>;

function readPath(obj: unknown, parts: string[]): unknown {
  let value: unknown = obj;
  for (const part of parts) {
    if (value && typeof value === "object" && part in (value as Record<string, unknown>)) {
      value = (value as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return value;
}

export function tr(lang: Lang, key: TranslationKey, ...args: unknown[]): string {
  const parts = key.split(".");
  const value = readPath(dict[lang], parts) ?? readPath(dict.zh, parts);
  if (typeof value === "function") {
    return (value as (...a: unknown[]) => string)(...args);
  }
  return typeof value === "string" ? value : key;
}

/** Pick a localized field from a `{ zh, en }` object, falling back to the raw value. */
export function L<T>(value: T | { zh?: T; en?: T } | undefined, lang: Lang): T | undefined {
  if (value == null) return undefined;
  if (typeof value === "object" && ("zh" in (value as object) || "en" in (value as object))) {
    const localized = value as { zh?: T; en?: T };
    return localized[lang] ?? localized.zh ?? localized.en;
  }
  return value as T;
}

interface LocaleState {
  lang: Lang;
  density: Density;
  theme: "light" | "dark" | "system";
  setLang: (lang: Lang) => void;
  setDensity: (density: Density) => void;
  setTheme: (theme: "light" | "dark" | "system") => void;
}

function readPersisted<T extends string>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const stored = window.localStorage?.getItem(key);
    return (stored as T) ?? fallback;
  } catch {
    return fallback;
  }
}

function safeWrite(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage?.setItem(key, value);
  } catch {
    // localStorage may be unavailable (e.g. private browsing, sandboxed iframe)
  }
}

function defaultLang(): Lang {
  if (typeof navigator === "undefined") return "zh";
  return navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export const useLocaleStore = create<LocaleState>((set) => ({
  lang: typeof window === "undefined" ? "zh" : (readPersisted<Lang>("locale.lang", defaultLang())),
  density: typeof window === "undefined" ? "balanced" : readPersisted<Density>("locale.density", "balanced"),
  theme: typeof window === "undefined" ? "system" : readPersisted<"light" | "dark" | "system">("locale.theme", "system"),
  setLang(lang) {
    safeWrite("locale.lang", lang);
    set({ lang });
  },
  setDensity(density) {
    safeWrite("locale.density", density);
    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-density", density);
    }
    set({ density });
  },
  setTheme(theme) {
    safeWrite("locale.theme", theme);
    if (typeof document !== "undefined") {
      const attr = theme === "system" ? "" : theme;
      if (attr) document.documentElement.setAttribute("data-theme", attr);
      else document.documentElement.removeAttribute("data-theme");
    }
    set({ theme });
  },
}));

export function useT(): { lang: Lang; t: (key: TranslationKey, ...args: unknown[]) => string } {
  const lang = useLocaleStore((s) => s.lang);
  return { lang, t: (key, ...args) => tr(lang, key, ...args) };
}
