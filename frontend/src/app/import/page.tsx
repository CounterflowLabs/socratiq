"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useCourseRunProgress, useRunProgress } from "@/lib/use-run-progress";
import AgenticTimeline from "@/components/materials/agentic-timeline";
import { useRouter } from "next/navigation";

import {
  IcAlert,
  IcArrowRight,
  IcCheck,
  IcDoc,
  IcEdit,
  IcImport,
  IcLink,
  IcLoader,
  IcSpark,
  IcTV,
  IcVideo,
  SourceIcon,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Ornament } from "@/components/ui/ornament";
import { PageHeader } from "@/components/ui/page-header";
import {
  ApiError,
  createCourseFromPrompt,
  createSourceFromURL,
  createSourceFromFile,
  getBilibiliStatus,
  getSourceProgress,
  retrySource,
  type IngestOptions,
  type SourceProgressResponse,
  type SourceResponse,
} from "@/lib/api";
import { useSourcesStore, useTasksStore } from "@/lib/stores";
import { useT } from "@/lib/i18n";

type Tab = "url" | "file" | "text" | "prompt";
type CardStatus = "running" | "failed" | "done";

interface ExistingSourceNotice {
  sourceId: string;
  title: string;
  status: string;
}

// Map worker stage strings to the 4 visible stages on the card.
// Stages live in two task buckets server-side (source_processing then
// course_generation); we collapse them into the same 4-step UI.
const STAGE_INDEX: Record<string, number> = {
  PENDING: 0,
  cloning: 0,
  extracting: 0,
  analyzing: 1,
  generating_lessons: 2,
  generating_labs: 2,
  storing: 3,
  embedding: 3,
  assembling_course: 3,
  generating_course: 3,
  SUCCESS: 4,
  FAILURE: 4,
};

interface CardState {
  status: CardStatus;
  stageIndex: number;
  failedStageIndex: number | null;
  errorMessage: string | null;
  courseId: string | null;
}

function deriveCardState(
  progress: SourceProgressResponse,
): CardState {
  const byType: Record<string, SourceProgressResponse["tasks"][number]> = {};
  for (const t of progress.tasks) byType[t.task_type] = t;
  const proc = byType.source_processing;
  const gen = byType.course_generation;

  if (gen?.status === "success" && (gen.course_id || progress.course_id)) {
    return {
      status: "done",
      stageIndex: 4,
      failedStageIndex: null,
      errorMessage: null,
      courseId: gen.course_id ?? progress.course_id ?? null,
    };
  }

  if (proc?.status === "failure" || gen?.status === "failure") {
    const failingTask = proc?.status === "failure" ? proc : gen;
    const failingStage = failingTask?.stage ?? "extracting";
    return {
      status: "failed",
      stageIndex: STAGE_INDEX[failingStage] ?? 0,
      failedStageIndex: STAGE_INDEX[failingStage] ?? 0,
      errorMessage:
        failingTask?.error_summary ||
        progress.error ||
        null,
      courseId: null,
    };
  }

  // In-flight: prefer the further-along task's stage.
  const activeStage =
    (proc?.status === "success" ? gen?.stage : proc?.stage) ??
    gen?.stage ??
    proc?.stage ??
    progress.source_status ??
    "PENDING";
  return {
    status: "running",
    stageIndex: STAGE_INDEX[activeStage] ?? 0,
    failedStageIndex: null,
    errorMessage: null,
    courseId: null,
  };
}

function isUserExistingSource(source: SourceResponse): boolean {
  return source.duplicate_reason === "user_existing";
}

const SAMPLES: Array<{
  type: "youtube" | "bilibili" | "pdf";
  title: { zh: string; en: string };
  url: string;
  meta: string;
}> = [
  {
    type: "youtube",
    title: {
      zh: "Karpathy — Let's build GPT from scratch",
      en: "Karpathy — Let's build GPT from scratch",
    },
    url: "https://www.youtube.com/watch?v=kCc8FmEb1nY",
    meta: "1h 56m",
  },
  {
    type: "bilibili",
    title: {
      zh: "Attention Is All You Need · 论文解读与 Transformer 架构",
      en: "Attention Is All You Need — paper walkthrough & Transformer architecture",
    },
    url: "https://www.bilibili.com/video/BV1xoJwzDESD",
    meta: "52m",
  },
  {
    type: "pdf",
    title: {
      zh: "Google SRE Book — 监控分布式系统",
      en: "Google SRE Book — Monitoring distributed systems",
    },
    url: "https://sre.google/sre-book/monitoring-distributed-systems/",
    meta: "24p",
  },
];

const PROMPT_SAMPLES_ZH: string[] = [
  "用 30 分钟讲清楚 Transformer 的注意力机制",
  "给完全的新手讲一遍 Git 的核心概念和工作流",
  "从零理解 Rust 的所有权与借用",
];

const PROMPT_SAMPLES_EN: string[] = [
  "Teach me the attention mechanism in Transformers in 30 minutes",
  "Explain Git's core concepts and workflow to a complete beginner",
  "Understand Rust ownership and borrowing from scratch",
];

export default function ImportPage() {
  const router = useRouter();
  const { t, lang } = useT();
  const addSource = useSourcesStore((s) => s.addSource);
  const addTask = useTasksStore((s) => s.addTask);

  const [tab, setTab] = useState<Tab>("url");
  const [url, setUrl] = useState("");
  const [textContent, setTextContent] = useState("");
  const [promptText, setPromptText] = useState("");
  const [pdfName, setPdfName] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);

  // One-sentence → course flow. `promptTaskId` is the AG-UI run id we follow;
  // `promptCourseNavigated` guards against a double navigation if both the
  // RUN_FINISHED event's course id and the runStatus effect fire.
  const [promptTaskId, setPromptTaskId] = useState<string | null>(null);
  const [promptCourseNavigated, setPromptCourseNavigated] = useState(false);

  // PRD §5.2 ingest config panel — defaults match the global pipeline.
  // The values get serialized into ingest_options_json and stamped onto
  // source.metadata at creation; the ingestion pipeline reads them when
  // present, otherwise it falls back to the route-level model.
  const [chunkSize, setChunkSize] = useState<256 | 512 | 1024>(512);
  const [transcriptSource, setTranscriptSource] =
    useState<"reuse" | "force_whisper">("reuse");
  const [ocrMode, setOcrMode] = useState<"auto" | "force" | "off">("auto");
  const [embedModelLabel, setEmbedModelLabel] = useState<string | null>(null);
  const [showIngestPanel, setShowIngestPanel] = useState(false);

  useEffect(() => {
    void Promise.all([
      fetch("/api/v1/model-routes").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/v1/models").then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([routes, models]) => {
        const route = Array.isArray(routes)
          ? routes.find((r: { tier?: string; task_type?: string }) => (r.tier ?? r.task_type) === "embedding")
          : null;
        if (!route) return;
        const model = Array.isArray(models)
          ? models.find((m: { name: string }) => m.name === route.model_name)
          : null;
        setEmbedModelLabel(
          model?.model_id ? `${model.provider_type ?? ""} · ${model.model_id}`.trim() : route.model_name,
        );
      })
      .catch(() => setEmbedModelLabel(null));
  }, []);

  const buildIngestOptions = (): IngestOptions => {
    const opts: IngestOptions = {};
    if (chunkSize !== 512) opts.chunk_size = chunkSize;
    if (transcriptSource !== "reuse") opts.transcript = transcriptSource;
    if (ocrMode !== "auto") opts.ocr = ocrMode;
    return opts;
  };

  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [biliLoggedIn, setBiliLoggedIn] = useState<boolean | null>(null);
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeSourceLabel, setActiveSourceLabel] = useState<string>("");
  const [activeSourceType, setActiveSourceType] = useState<"youtube" | "bilibili" | "pdf" | "markdown" | "url">("url");
  const [existingSourceNotice, setExistingSourceNotice] =
    useState<ExistingSourceNotice | null>(null);
  const [card, setCard] = useState<CardState>({
    status: "running",
    stageIndex: 0,
    failedStageIndex: null,
    errorMessage: null,
    courseId: null,
  });
  const [retrying, setRetrying] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);

  const stages = [
    { label: t("import.pipeline.s1"), tag: "fetch_transcript" },
    { label: t("import.pipeline.s2"), tag: "analyze_content" },
    { label: t("import.pipeline.s3"), tag: "plan_path" },
    { label: t("import.pipeline.s4"), tag: "assemble_course" },
  ];

  const isBilibiliUrl = url.toLowerCase().includes("bilibili.com");
  const bilibiliBlocked = tab === "url" && isBilibiliUrl && biliLoggedIn === false;

  useEffect(() => {
    if (tab !== "url" || !isBilibiliUrl) return;
    let cancelled = false;
    getBilibiliStatus()
      .then((status) => {
        if (!cancelled) setBiliLoggedIn(status.logged_in);
      })
      .catch(() => {
        if (!cancelled) setBiliLoggedIn(true);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, isBilibiliUrl]);

  const canSubmit =
    tab === "url"
      ? Boolean(url.trim())
      : tab === "file"
        ? Boolean(pdfFile)
        : tab === "prompt"
          ? Boolean(promptText.trim())
          : Boolean(textContent.trim());

  // Refetch the DB-authoritative pipeline state and re-derive the card. Also
  // tracks the active task's run id (= celery_task_id = the AG-UI run id) so the
  // SSE subscription below can follow the live run across the ingestion ->
  // course-generation handoff.
  const progressActive = analyzing && card.status === "running";
  const refreshProgress = useCallback(async () => {
    if (!activeSourceId) return;
    try {
      const progress = await getSourceProgress(activeSourceId);
      setCard(deriveCardState(progress));
      const live = progress.tasks.find(
        (t) => t.status === "running" || t.status === "pending" || t.status === "progress",
      );
      setActiveRunId(live?.celery_task_id ?? null);
    } catch {
      // transient — the safety poll / next event will retry
    }
  }, [activeSourceId]);

  // Live progress over AG-UI SSE: each emitted event triggers a refetch, so the
  // card updates the instant the worker advances a stage instead of on a timer.
  const liveRun = useRunProgress(activeSourceId, activeRunId, progressActive);
  useEffect(() => {
    if (!progressActive) return;
    if (liveRun.snapshot !== null || liveRun.runStatus === "finished" || liveRun.runStatus === "error") {
      void refreshProgress();
    }
  }, [liveRun.snapshot, liveRun.runStatus, progressActive, refreshProgress]);

  // Initial fetch + a slow safety poll (the SSE stream drives live updates; this
  // only backstops a dropped connection or a missed run handoff).
  useEffect(() => {
    if (!progressActive) return;
    let cancelled = false;
    void refreshProgress();
    const handle = setInterval(() => {
      if (!cancelled) void refreshProgress();
    }, 8000);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [progressActive, refreshProgress]);

  // One-sentence → course: subscribe to the source-less run and project its
  // agentic timeline (same component the URL/source flow uses). Active only
  // while the prompt task is in flight and the card hasn't settled.
  const promptRunActive =
    promptTaskId !== null && analyzing && card.status === "running";
  const promptRun = useCourseRunProgress(promptTaskId, promptRunActive);

  // On finish, the run carries the new course id at result.course_id (projected
  // onto promptRun.courseId). Navigate to it the same way the rest of the app
  // opens a course: router.push(/learn?courseId=…).
  useEffect(() => {
    if (promptTaskId === null || promptCourseNavigated) return;
    if (promptRun.runStatus === "finished" && promptRun.courseId) {
      setPromptCourseNavigated(true);
      router.push(`/learn?courseId=${promptRun.courseId}`);
    }
  }, [
    promptTaskId,
    promptCourseNavigated,
    promptRun.runStatus,
    promptRun.courseId,
    router,
  ]);

  // Reflect the prompt run's lifecycle onto the shared status card: a stream
  // error or a finish-without-course-id settles the card so it stops spinning.
  useEffect(() => {
    if (promptTaskId === null) return;
    if (promptRun.runStatus === "error") {
      setCard((prev) => ({
        ...prev,
        status: "failed",
        failedStageIndex: prev.stageIndex,
        errorMessage: promptRun.error ?? t("import.errorUnknown"),
      }));
    } else if (promptRun.runStatus === "finished" && !promptRun.courseId) {
      // Finished but no course id (shouldn't happen) — mark done so the card
      // doesn't spin forever; the user can retry via "import another".
      setCard((prev) => ({ ...prev, status: "done", stageIndex: 4 }));
    }
  }, [promptTaskId, promptRun.runStatus, promptRun.courseId, promptRun.error, t]);

  function handleFileSelect(file: File | undefined) {
    if (!file) return;
    if (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) {
      setPdfFile(file);
      setPdfName(file.name);
    }
  }

  async function handleImport() {
    if (!canSubmit || bilibiliBlocked) return;
    setLoading(true);
    setErrorMsg(null);
    setExistingSourceNotice(null);
    setCard({
      status: "running",
      stageIndex: 0,
      failedStageIndex: null,
      errorMessage: null,
      courseId: null,
    });
    setAnalyzing(true);

    try {
      let source: SourceResponse;
      const ingestOpts = buildIngestOptions();
      if (tab === "url") {
        source = await createSourceFromURL(url.trim(), undefined, undefined, ingestOpts);
      } else if (tab === "file" && pdfFile) {
        source = await createSourceFromFile(pdfFile, undefined, ingestOpts);
      } else {
        // Pasted text isn't yet supported by the backend — surface a helpful
        // hint so the user knows it's a near-term feature, not a silent fail.
        setErrorMsg(
          lang === "zh"
            ? "粘贴文本暂未启用，请先用链接或上传 PDF。"
            : "Pasting raw text is not yet supported. Please use a URL or upload a PDF.",
        );
        setLoading(false);
        setAnalyzing(false);
        return;
      }

      setActiveSourceId(source.id);
      setActiveSourceLabel(source.title || url.trim() || pdfName || source.id);
      setActiveSourceType(
        (source.type as typeof activeSourceType) ?? (tab === "url" ? "url" : "pdf"),
      );

      if (isUserExistingSource(source)) {
        setExistingSourceNotice({
          sourceId: source.id,
          title: source.title || url.trim() || pdfName || source.id,
          status: source.status,
        });
        setCard({
          status: "done",
          stageIndex: 4,
          failedStageIndex: null,
          errorMessage: null,
          courseId: source.latest_course_id ?? null,
        });
        setLoading(false);
        return;
      }

      addSource(source);

      if (source.task_id) {
        addTask({
          taskId: source.task_id,
          sourceId: source.id,
          title: source.title || url.trim() || pdfName || (lang === "zh" ? "导入中…" : "Importing…"),
          sourceType: source.type,
          state: "PENDING",
        });
      }

      setLoading(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 412 && err.code === "bilibili_credential_required") {
        setBiliLoggedIn(false);
        setErrorMsg(null);
      } else {
        setErrorMsg(
          err instanceof Error
            ? err.message
            : lang === "zh"
              ? "导入失败，请检查链接或文件后重试"
              : "Import failed. Check the URL or file and try again.",
        );
      }
      setLoading(false);
      setAnalyzing(false);
    }
  }

  async function handleGenerateFromPrompt() {
    if (!promptText.trim() || loading) return;
    setLoading(true);
    setErrorMsg(null);
    setExistingSourceNotice(null);
    setPromptTaskId(null);
    setPromptCourseNavigated(false);
    setActiveSourceId(null);
    setActiveSourceLabel(promptText.trim());
    setActiveSourceType("url");
    setCard({
      status: "running",
      stageIndex: 0,
      failedStageIndex: null,
      errorMessage: null,
      courseId: null,
    });
    setAnalyzing(true);

    try {
      const { task_id } = await createCourseFromPrompt(
        promptText.trim(),
        lang === "zh" ? "zh" : "en",
      );
      setPromptTaskId(task_id);
      setLoading(false);
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : lang === "zh"
            ? "生成失败，请稍后重试"
            : "Generation failed. Please try again.",
      );
      setLoading(false);
      setAnalyzing(false);
    }
  }

  async function handleRetry() {
    if (!activeSourceId || retrying) return;
    setRetrying(true);
    setCard({
      status: "running",
      stageIndex: 0,
      failedStageIndex: null,
      errorMessage: null,
      courseId: null,
    });
    try {
      await retrySource(activeSourceId);
    } catch (err) {
      setCard({
        status: "failed",
        stageIndex: 0,
        failedStageIndex: 0,
        errorMessage:
          err instanceof Error ? err.message : t("import.errorUnknown"),
        courseId: null,
      });
    } finally {
      setRetrying(false);
    }
  }

  function handleImportAnother() {
    setAnalyzing(false);
    setActiveSourceId(null);
    setActiveSourceLabel("");
    setExistingSourceNotice(null);
    setPromptTaskId(null);
    setPromptCourseNavigated(false);
    setCard({
      status: "running",
      stageIndex: 0,
      failedStageIndex: null,
      errorMessage: null,
      courseId: null,
    });
    setUrl("");
    setPdfFile(null);
    setPdfName("");
    setTextContent("");
    setPromptText("");
    setErrorMsg(null);
  }

  return (
    <div style={{ padding: "32px 40px 80px", maxWidth: 720, margin: "0 auto", width: "100%" }}>
      <PageHeader
        eyebrow={t("tasks.typeEmbed")}
        title={t("import.title")}
        subtitle={t("import.subtitle")}
      />

      {bilibiliBlocked ? (
        <div
          role="alert"
          className="card-quiet"
          style={{
            display: "flex",
            gap: 10,
            padding: 14,
            marginBottom: 20,
            borderColor: "rgba(179, 66, 47, 0.3)",
            background: "var(--error-soft)",
            color: "var(--error)",
          }}
        >
          <IcAlert size={16} style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ flex: 1, fontSize: 13, lineHeight: 1.6 }}>
            <div>{t("import.bilibiliBlocked")}</div>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ marginTop: 8, color: "var(--error)" }}
              onClick={() => router.push("/settings?section=sources")}
            >
              {t("import.bilibiliConfigure")}
            </button>
          </div>
        </div>
      ) : null}

      {errorMsg ? (
        <div
          role="alert"
          className="card-quiet"
          style={{
            display: "flex",
            gap: 10,
            padding: 12,
            marginBottom: 20,
            borderColor: "rgba(179, 66, 47, 0.3)",
            background: "var(--error-soft)",
            color: "var(--error)",
            fontSize: 13,
          }}
        >
          <IcAlert size={14} style={{ flexShrink: 0, marginTop: 2 }} />
          <span>{errorMsg}</span>
        </div>
      ) : null}

      {!analyzing ? (
        <>
          {/* Tabs */}
          <div
            style={{
              display: "flex",
              gap: 4,
              marginBottom: "var(--gap-md)",
              borderBottom: "1px solid var(--border)",
            }}
          >
            {(
              [
                { key: "url" as const, label: t("import.pasteUrl"), Icon: IcLink },
                { key: "file" as const, label: t("import.uploadFile"), Icon: IcDoc },
                { key: "text" as const, label: t("import.writeText"), Icon: IcEdit },
                { key: "prompt" as const, label: t("import.fromPrompt"), Icon: IcSpark },
              ]
            ).map(({ key, label, Icon }) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className="btn btn-ghost"
                style={{
                  height: 36,
                  borderRadius: 0,
                  borderBottom: `2px solid ${tab === key ? "var(--ink)" : "transparent"}`,
                  color: tab === key ? "var(--ink)" : "var(--ink-3)",
                  fontWeight: tab === key ? 500 : 400,
                  marginBottom: -1,
                }}
              >
                <Icon size={14} />
                <span>{label}</span>
              </button>
            ))}
          </div>

          <div style={{ marginBottom: "var(--gap-lg)" }}>
            {tab === "url" ? (
              <div>
                <div style={{ position: "relative" }}>
                  <input
                    id="import-url"
                    aria-label={t("import.placeholder")}
                    className="input input-lg"
                    placeholder={t("import.placeholder")}
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    style={{
                      paddingRight: 110,
                      fontFamily: "var(--mono)",
                      fontSize: 13,
                    }}
                  />
                  <button
                    type="button"
                    onClick={handleImport}
                    disabled={!canSubmit || loading || bilibiliBlocked}
                    className="btn btn-accent"
                    style={{ position: "absolute", right: 6, top: 6, height: 32 }}
                  >
                    <span>{t("import.analyze")}</span>
                    <IcArrowRight size={12} />
                  </button>
                </div>
                <div
                  style={{
                    marginTop: 10,
                    display: "flex",
                    gap: 6,
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <span className="eyebrow">{t("import.supports")}</span>
                  {[
                    { Icon: IcVideo, label: "YouTube" },
                    { Icon: IcTV, label: "Bilibili" },
                    { Icon: IcDoc, label: "PDF" },
                    { Icon: IcDoc, label: "Markdown" },
                  ].map(({ Icon, label }) => (
                    <span key={label} className="chip">
                      <Icon size={11} />
                      {label}
                    </span>
                  ))}
                </div>

                <details
                  open={showIngestPanel}
                  onToggle={(e) =>
                    setShowIngestPanel((e.currentTarget as HTMLDetailsElement).open)
                  }
                  style={{
                    marginTop: 18,
                    padding: 14,
                    borderRadius: "var(--r-lg)",
                    border: "1px solid var(--border)",
                    background: "var(--surface-2)",
                  }}
                >
                  <summary
                    style={{
                      cursor: "pointer",
                      listStyle: "none",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      fontSize: 13,
                      color: "var(--ink-2)",
                      fontWeight: 500,
                    }}
                  >
                    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                      <IcImport size={14} />
                      {lang === "zh" ? "处理参数" : "Ingest options"}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--ink-3)" }}>
                      {showIngestPanel
                        ? lang === "zh"
                          ? "收起"
                          : "Collapse"
                        : lang === "zh"
                          ? "展开"
                          : "Expand"}
                    </span>
                  </summary>

                  <div
                    style={{
                      marginTop: 12,
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: 14,
                    }}
                  >
                    <Field
                      label={lang === "zh" ? "向量模型（当前路由）" : "Embedding model (routed)"}
                    >
                      <div
                        className="mono"
                        style={{
                          fontSize: 12,
                          padding: "8px 10px",
                          borderRadius: "var(--r)",
                          background: "var(--surface)",
                          color: "var(--ink-2)",
                          border: "1px solid var(--border)",
                        }}
                      >
                        {embedModelLabel ?? "—"}
                      </div>
                    </Field>
                    <Field label={lang === "zh" ? "切片大小" : "Chunk size"}>
                      <Segments<256 | 512 | 1024>
                        value={chunkSize}
                        options={[
                          { v: 256, label: "256" },
                          { v: 512, label: "512" },
                          { v: 1024, label: "1024" },
                        ]}
                        onChange={setChunkSize}
                      />
                    </Field>
                    <Field label={lang === "zh" ? "转录源" : "Transcript"}>
                      <Segments<"reuse" | "force_whisper">
                        value={transcriptSource}
                        options={[
                          { v: "reuse", label: lang === "zh" ? "复用已有" : "Reuse existing" },
                          { v: "force_whisper", label: lang === "zh" ? "强制 Whisper" : "Force Whisper" },
                        ]}
                        onChange={setTranscriptSource}
                      />
                    </Field>
                    <Field label={lang === "zh" ? "OCR 扫描件" : "OCR"}>
                      <Segments<"auto" | "force" | "off">
                        value={ocrMode}
                        options={[
                          { v: "auto", label: lang === "zh" ? "自动" : "Auto" },
                          { v: "force", label: lang === "zh" ? "强制" : "Force" },
                          { v: "off", label: lang === "zh" ? "关闭" : "Off" },
                        ]}
                        onChange={setOcrMode}
                      />
                    </Field>
                  </div>
                </details>

                <div style={{ marginTop: 28 }}>
                  <Eyebrow>{t("import.sample")}</Eyebrow>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      marginTop: 10,
                    }}
                  >
                    {SAMPLES.map((sample) => (
                      <button
                        key={sample.url}
                        type="button"
                        onClick={() => setUrl(sample.url)}
                        className="card-quiet"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 12,
                          cursor: "pointer",
                          textAlign: "left",
                          padding: 12,
                          background: "transparent",
                          font: "inherit",
                          color: "var(--ink)",
                          width: "100%",
                          border: "1px solid var(--border)",
                        }}
                      >
                        <SourceIcon type={sample.type} size={16} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="serif" style={{ fontSize: 15, fontWeight: 500 }}>
                            {sample.title[lang]}
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--ink-3)",
                              fontFamily: "var(--mono)",
                              marginTop: 2,
                            }}
                          >
                            {sample.url} · {sample.meta}
                          </div>
                        </div>
                        <IcArrowRight size={14} style={{ color: "var(--ink-3)" }} />
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}

            {tab === "file" ? (
              <div>
                <div
                  className="hatched"
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOver(false);
                    handleFileSelect(e.dataTransfer.files[0]);
                  }}
                  onClick={() => fileRef.current?.click()}
                  style={{
                    border: `1.5px dashed ${dragOver ? "var(--accent)" : "var(--border-strong)"}`,
                    borderRadius: "var(--r-lg)",
                    padding: "64px 24px",
                    textAlign: "center",
                    color: "var(--ink-3)",
                    cursor: "pointer",
                  }}
                >
                  {pdfName ? (
                    <div
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 8,
                        color: "var(--sage)",
                      }}
                    >
                      <IcCheck size={16} />
                      <span className="serif" style={{ fontSize: 16 }}>
                        {pdfName}
                      </span>
                    </div>
                  ) : (
                    <>
                      <IcImport size={28} />
                      <div
                        className="serif"
                        style={{ fontSize: 18, color: "var(--ink)", margin: "12px 0 4px" }}
                      >
                        {t("import.dropHere")}
                      </div>
                      <div style={{ fontSize: 12 }}>{t("import.dropHint")}</div>
                    </>
                  )}
                </div>
                <input
                  id="import-file"
                  aria-label={t("import.dropHere")}
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.md,.txt,.markdown"
                  onChange={(e) => handleFileSelect(e.target.files?.[0] ?? undefined)}
                  style={{ display: "none" }}
                />
                <div style={{ marginTop: 12, textAlign: "right" }}>
                  <button
                    type="button"
                    onClick={handleImport}
                    disabled={!canSubmit || loading}
                    className="btn btn-accent"
                  >
                    <span>{t("import.analyze")}</span>
                    <IcArrowRight size={12} />
                  </button>
                </div>
              </div>
            ) : null}

            {tab === "text" ? (
              <div>
                <textarea
                  id="import-text"
                  aria-label={t("import.textPlaceholder")}
                  className="input"
                  value={textContent}
                  onChange={(e) => setTextContent(e.target.value)}
                  placeholder={t("import.textPlaceholder")}
                  style={{
                    height: 220,
                    padding: 12,
                    resize: "vertical",
                    fontFamily: "var(--mono)",
                    fontSize: 13,
                  }}
                />
                <div style={{ marginTop: 12, textAlign: "right" }}>
                  <button
                    type="button"
                    onClick={handleImport}
                    disabled={!canSubmit || loading}
                    className="btn btn-accent"
                  >
                    <span>{t("import.analyze")}</span>
                    <IcArrowRight size={12} />
                  </button>
                </div>
              </div>
            ) : null}

            {tab === "prompt" ? (
              <div>
                <textarea
                  id="import-prompt"
                  aria-label={t("import.promptPlaceholder")}
                  className="input"
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                  placeholder={t("import.promptPlaceholder")}
                  style={{
                    height: 140,
                    padding: 12,
                    resize: "vertical",
                    fontSize: 14,
                    lineHeight: 1.6,
                  }}
                />
                <div
                  style={{
                    marginTop: 10,
                    fontSize: 12,
                    color: "var(--ink-3)",
                    lineHeight: 1.6,
                  }}
                >
                  {t("import.promptHint")}
                </div>
                <div style={{ marginTop: 12, textAlign: "right" }}>
                  <button
                    type="button"
                    onClick={handleGenerateFromPrompt}
                    disabled={!canSubmit || loading}
                    className="btn btn-accent"
                  >
                    {loading ? <IcLoader size={12} className="spin" /> : <IcSpark size={12} />}
                    <span>{t("import.generateCourse")}</span>
                  </button>
                </div>

                <div style={{ marginTop: 24 }}>
                  <Eyebrow>{t("import.promptSamples")}</Eyebrow>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      marginTop: 10,
                    }}
                  >
                    {(lang === "zh" ? PROMPT_SAMPLES_ZH : PROMPT_SAMPLES_EN).map(
                      (sample) => (
                        <button
                          key={sample}
                          type="button"
                          onClick={() => setPromptText(sample)}
                          className="card-quiet"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 12,
                            cursor: "pointer",
                            textAlign: "left",
                            padding: 12,
                            background: "transparent",
                            font: "inherit",
                            color: "var(--ink)",
                            width: "100%",
                            border: "1px solid var(--border)",
                          }}
                        >
                          <IcSpark size={14} style={{ color: "var(--accent)", flexShrink: 0 }} />
                          <span className="serif" style={{ fontSize: 15, flex: 1, minWidth: 0 }}>
                            {sample}
                          </span>
                          <IcArrowRight size={14} style={{ color: "var(--ink-3)" }} />
                        </button>
                      ),
                    )}
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          {/* Tips */}
          <Ornament />
          <div style={{ marginTop: 20 }}>
            <Eyebrow>{t("import.tips")}</Eyebrow>
            <ul
              style={{
                marginTop: 12,
                padding: 0,
                listStyle: "none",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              {[t("import.tip1"), t("import.tip2"), t("import.tip3")].map((tip, i) => (
                <li
                  key={i}
                  style={{
                    display: "flex",
                    gap: 10,
                    fontSize: 13,
                    color: "var(--ink-2)",
                    lineHeight: 1.6,
                  }}
                >
                  <span className="mono num" style={{ color: "var(--ink-4)", flexShrink: 0 }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span>{tip}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : (
        (() => {
          const isFailed = card.status === "failed";
          const isDone = card.status === "done";
          const isExisting = existingSourceNotice !== null;
          // The one-sentence flow has no source-ingestion pipeline: it shows the
          // agentic timeline (its real progress) instead of the 4 source stages,
          // and follows the prompt run rather than the source run.
          const isPrompt = promptTaskId !== null;
          const liveAgentic = isPrompt ? promptRun : liveRun;
          const chipClass = isFailed
            ? "chip"
            : isDone
              ? "chip"
              : "chip chip-accent";
          const chipStyle = isFailed
            ? {
                background: "var(--error-soft)",
                color: "var(--error)",
                borderColor: "rgba(179, 66, 47, 0.3)",
              }
            : isDone
              ? {
                  background: "var(--sage-soft, rgba(120, 140, 90, 0.18))",
                  color: "var(--sage)",
                }
              : undefined;
          const heading = isFailed
            ? t("import.pipelineFailedTitle")
            : isExisting
              ? "已存在资料"
              : isDone
              ? t("import.pipelineDoneTitle")
              : isPrompt
                ? t("import.promptStartedTitle")
                : t("import.pipelineStartedTitle");
          const hint = isFailed
            ? t("import.pipelineFailedHint")
            : isExisting
              ? "这份资料已经在你的资料库中，没有重复创建新资料。"
              : isDone
              ? t("import.pipelineDoneHint")
              : isPrompt
                ? t("import.promptStartedHint")
                : t("import.pipelineStartedHint");
          const chipLabel = isFailed
            ? t("import.statusFailed")
            : isExisting
              ? "已存在"
              : isDone
              ? t("import.statusDone")
              : t("import.statusProcessing");

          return (
            <div className="card" style={{ padding: 32 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
                {isPrompt ? (
                  <span style={{ color: "var(--accent)" }}>
                    <IcSpark size={20} />
                  </span>
                ) : (
                  <SourceIcon type={activeSourceType} size={20} />
                )}
                <div
                  className={isPrompt ? undefined : "mono"}
                  style={{
                    fontSize: 13,
                    color: "var(--ink-2)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    flex: 1,
                  }}
                >
                  {activeSourceLabel}
                </div>
                <span className={chipClass} style={chipStyle}>
                  {chipLabel}
                </span>
              </div>
              <h2
                className="display"
                style={{ fontSize: 22, margin: "12px 0 4px", fontWeight: 400 }}
              >
                {heading}
              </h2>
              <div style={{ fontSize: 12, color: "var(--ink-3)", marginBottom: isFailed && card.errorMessage ? 16 : 32 }}>
                {hint}
              </div>

              {isFailed && card.errorMessage ? (
                <div
                  role="alert"
                  className="card-quiet"
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: 12,
                    marginBottom: 24,
                    borderColor: "rgba(179, 66, 47, 0.3)",
                    background: "var(--error-soft)",
                    color: "var(--error)",
                    fontSize: 13,
                    lineHeight: 1.6,
                  }}
                >
                  <IcAlert size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                  <span style={{ wordBreak: "break-word" }}>
                    {card.errorMessage}
                  </span>
                </div>
              ) : null}

              {isExisting && existingSourceNotice ? (
                <div
                  role="status"
                  className="card-quiet"
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: 12,
                    marginBottom: 24,
                    borderColor: "var(--border)",
                    background: "var(--surface-2)",
                    color: "var(--ink-2)",
                    fontSize: 13,
                    lineHeight: 1.6,
                  }}
                >
                  <IcCheck size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                  <span style={{ minWidth: 0, wordBreak: "break-word" }}>
                    已找到已有资料：{existingSourceNotice.title}
                  </span>
                </div>
              ) : null}

              <div
                style={{
                  display: "flex",
                  gap: 10,
                  marginBottom: 24,
                  flexWrap: "wrap",
                }}
              >
                {isExisting && existingSourceNotice ? (
                  <button
                    type="button"
                    className="btn btn-accent"
                    onClick={() => router.push(`/sources?sourceId=${existingSourceNotice.sourceId}`)}
                  >
                    <span>打开已有资料</span>
                    <IcArrowRight size={12} />
                  </button>
                ) : null}
                {isDone && card.courseId && !isExisting ? (
                  <button
                    type="button"
                    className="btn btn-accent"
                    onClick={() => router.push(`/learn?courseId=${card.courseId}`)}
                  >
                    <span>{t("import.openCourse")}</span>
                    <IcArrowRight size={12} />
                  </button>
                ) : null}
                {isPrompt && promptRun.courseId ? (
                  // Fallback CTA: the finish effect normally auto-navigates, but
                  // if that was blocked (e.g. the user navigated away and back)
                  // keep an explicit way into the new course.
                  <button
                    type="button"
                    className="btn btn-accent"
                    onClick={() => router.push(`/learn?courseId=${promptRun.courseId}`)}
                  >
                    <span>{t("import.openCourse")}</span>
                    <IcArrowRight size={12} />
                  </button>
                ) : null}
                {isDone && !card.courseId && activeSourceId && !isExisting ? (
                  // PRD §5.2: don't auto-jump to course generation. Surface
                  // it as a primary CTA on the success card instead.
                  <button
                    type="button"
                    className="btn btn-accent"
                    onClick={() => {
                      try {
                        sessionStorage.setItem(
                          "pendingGenerateSources",
                          JSON.stringify([activeSourceId]),
                        );
                      } catch {
                        /* sessionStorage unavailable — fine */
                      }
                      router.push("/generate");
                    }}
                  >
                    <span>✨ {t("newPopover.generateTitle")}</span>
                    <IcArrowRight size={12} />
                  </button>
                ) : null}
                {isFailed && !isPrompt ? (
                  <button
                    type="button"
                    className="btn btn-accent"
                    onClick={handleRetry}
                    disabled={retrying || !activeSourceId}
                  >
                    {retrying ? (
                      <IcLoader size={12} className="spin" />
                    ) : null}
                    <span>{t("import.retryImport")}</span>
                  </button>
                ) : null}
                {!isPrompt ? (
                  <button
                    type="button"
                    className={isDone || isFailed ? "btn btn-outline" : "btn btn-accent"}
                    onClick={() => router.push("/sources")}
                  >
                    <span>{t("import.viewSources")}</span>
                    <IcArrowRight size={12} />
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={handleImportAnother}
                >
                  <span>{t("import.importAnother")}</span>
                </button>
              </div>

              {!isExisting && !isPrompt ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {stages.map((s, i) => {
                  const isThisFailed = card.failedStageIndex === i;
                  const active = !isFailed && !isDone && i === card.stageIndex;
                  const done = isDone || i < card.stageIndex;
                  const dotBorder = isThisFailed
                    ? "var(--error)"
                    : done
                      ? "var(--sage)"
                      : active
                        ? "var(--accent)"
                        : "var(--border-strong)";
                  const dotBg = isThisFailed
                    ? "var(--error-soft)"
                    : done
                      ? "var(--sage)"
                      : active
                        ? "var(--accent-soft)"
                        : "transparent";
                  const dotColor = isThisFailed
                    ? "var(--error)"
                    : done
                      ? "#fff"
                      : "var(--accent)";
                  return (
                    <div
                      key={s.tag}
                      style={{ display: "flex", alignItems: "center", gap: 14 }}
                    >
                      <div
                        style={{
                          width: 22,
                          height: 22,
                          borderRadius: "50%",
                          border: `1.5px solid ${dotBorder}`,
                          background: dotBg,
                          color: dotColor,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        {isThisFailed ? (
                          <IcAlert size={12} />
                        ) : done ? (
                          <IcCheck size={12} />
                        ) : active ? (
                          <IcLoader size={12} className="spin" />
                        ) : (
                          <span
                            className="mono num"
                            style={{ fontSize: 11, color: "var(--ink-3)" }}
                          >
                            {i + 1}
                          </span>
                        )}
                      </div>
                      <div
                        style={{
                          flex: 1,
                          fontSize: 14,
                          color: isThisFailed
                            ? "var(--error)"
                            : done
                              ? "var(--ink-3)"
                              : "var(--ink)",
                          fontWeight: active || isThisFailed ? 500 : 400,
                        }}
                      >
                        {s.label}
                      </div>
                      <span className="mono" style={{ fontSize: 11, color: "var(--ink-4)" }}>
                        {s.tag}
                      </span>
                    </div>
                  );
                })}
              </div>
              ) : null}

              {liveAgentic.agentic.active ? (
                <div style={{ marginTop: 18 }}>
                  <AgenticTimeline
                    agentic={liveAgentic.agentic}
                    running={liveAgentic.runStatus === "running"}
                    lang={lang}
                  />
                </div>
              ) : isPrompt && !isFailed && !isDone ? (
                // Prompt run dispatched but no agentic event yet — give an
                // immediate "starting" affordance in place of the source stages.
                <div
                  style={{
                    marginTop: 18,
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    fontSize: 13,
                    color: "var(--ink-3)",
                  }}
                >
                  <IcLoader size={14} className="spin" />
                  <span>{t("import.promptStarting")}</span>
                </div>
              ) : null}
            </div>
          );
        })()
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: "block" }}>
      <span
        style={{
          display: "block",
          fontSize: 11,
          color: "var(--ink-3)",
          marginBottom: 6,
          fontWeight: 500,
        }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

function Segments<V extends string | number>({
  value,
  options,
  onChange,
}: {
  value: V;
  options: { v: V; label: string }[];
  onChange: (v: V) => void;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        background: "var(--surface)",
        borderRadius: "var(--r)",
        padding: 2,
        gap: 2,
        border: "1px solid var(--border)",
      }}
    >
      {options.map((opt) => (
        <button
          key={String(opt.v)}
          type="button"
          onClick={() => onChange(opt.v)}
          style={{
            padding: "6px 10px",
            borderRadius: "var(--r-sm)",
            border: "none",
            background: value === opt.v ? "var(--surface-2)" : "transparent",
            color: value === opt.v ? "var(--ink)" : "var(--ink-2)",
            cursor: "pointer",
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
