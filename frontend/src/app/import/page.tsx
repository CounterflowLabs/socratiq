"use client";

import { useEffect, useRef, useState } from "react";
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
  IcTV,
  IcVideo,
  SourceIcon,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Ornament } from "@/components/ui/ornament";
import { PageHeader } from "@/components/ui/page-header";
import {
  ApiError,
  createSourceFromURL,
  createSourceFromFile,
  getBilibiliStatus,
} from "@/lib/api";
import { useSourcesStore, useTasksStore } from "@/lib/stores";
import { useT } from "@/lib/i18n";

type Tab = "url" | "file" | "text";

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
      zh: "3Blue1Brown · 深度学习之数学原理",
      en: "3Blue1Brown · The math behind deep learning",
    },
    url: "https://www.bilibili.com/video/BV1gZ4y1F7hS",
    meta: "26m",
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

export default function ImportPage() {
  const router = useRouter();
  const { t, lang } = useT();
  const addSource = useSourcesStore((s) => s.addSource);
  const addTask = useTasksStore((s) => s.addTask);

  const [tab, setTab] = useState<Tab>("url");
  const [url, setUrl] = useState("");
  const [textContent, setTextContent] = useState("");
  const [pdfName, setPdfName] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [stage, setStage] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [biliLoggedIn, setBiliLoggedIn] = useState<boolean | null>(null);

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
        : Boolean(textContent.trim());

  // Fake-progress through pipeline stages while the backend works.
  useEffect(() => {
    if (!analyzing || stage >= stages.length) return;
    const handle = setTimeout(() => setStage((s) => s + 1), 1100);
    return () => clearTimeout(handle);
  }, [analyzing, stage, stages.length]);

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
    setStage(0);
    setAnalyzing(true);

    try {
      let source;
      if (tab === "url") {
        source = await createSourceFromURL(url.trim());
      } else if (tab === "file" && pdfFile) {
        source = await createSourceFromFile(pdfFile);
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

      // Brief delay so the user sees the final pipeline tick.
      setTimeout(() => router.push("/sources"), 600);
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

  return (
    <div style={{ padding: "32px 40px 80px", maxWidth: 720, margin: "0 auto", width: "100%" }}>
      <PageHeader eyebrow="01" title={t("import.title")} subtitle={t("import.subtitle")} />

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
              onClick={() => router.push("/settings")}
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
        <div className="card" style={{ padding: 32 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
            <SourceIcon type={tab === "url" ? "youtube" : "pdf"} size={20} />
            <div
              className="mono"
              style={{
                fontSize: 13,
                color: "var(--ink-2)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                flex: 1,
              }}
            >
              {tab === "url" ? url : pdfName}
            </div>
            <span className="chip chip-accent">{lang === "zh" ? "处理中" : "processing"}</span>
          </div>
          <h2
            className="display"
            style={{ fontSize: 22, margin: "12px 0 4px", fontWeight: 400 }}
          >
            {lang === "zh" ? "已开始解析" : "Pipeline started"}
          </h2>
          <div style={{ fontSize: 12, color: "var(--ink-3)", marginBottom: 32 }}>
            {lang === "zh"
              ? "你可以离开这个页面，处理状态会出现在资料库。"
              : "You can leave this page — progress shows up in the Library."}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {stages.map((s, i) => {
              const active = i === stage;
              const done = i < stage;
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
                      border: `1.5px solid ${
                        done
                          ? "var(--sage)"
                          : active
                            ? "var(--accent)"
                            : "var(--border-strong)"
                      }`,
                      background: done
                        ? "var(--sage)"
                        : active
                          ? "var(--accent-soft)"
                          : "transparent",
                      color: done ? "#fff" : "var(--accent)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {done ? (
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
                      color: done ? "var(--ink-3)" : "var(--ink)",
                      fontWeight: active ? 500 : 400,
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
        </div>
      )}
    </div>
  );
}
