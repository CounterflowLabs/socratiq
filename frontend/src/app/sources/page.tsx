"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { useRouter, useSearchParams } from "next/navigation";

import {
  IcCheck,
  IcDoc,
  IcFilter,
  IcLoader,
  IcMore,
  IcPlus,
  IcRegen,
  IcSearch,
  IcSparkle,
  SourceIcon,
} from "@/components/icons";
import { getSource, retrySource } from "@/lib/api";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageHeader } from "@/components/ui/page-header";
import { listSources, type SourceResponse } from "@/lib/api";
import SourceDetailDrawer from "@/components/materials/source-detail-drawer";
import {
  deriveMaterialEmbed,
  deriveMaterialPresentation,
  isCourseTaskActive,
  isMaterialActive,
  matchesMaterialStatusFilter,
  type MaterialStatusFilter,
} from "@/lib/materials-state";
import { useT } from "@/lib/i18n";

export default function SourcesPage() {
  return (
    <Suspense fallback={<SourcesPageFallback />}>
      <SourcesPageContent />
    </Suspense>
  );
}

function SourcesPageFallback() {
  return (
    <div className="min-h-screen px-8 py-8" style={{ background: "var(--background)" }}>
      <div className="mx-auto max-w-6xl">
        <div className="h-8 w-44 rounded-full" style={{ background: "var(--surface-2)" }} />
        <div className="mt-8 h-32 rounded-2xl" style={{ background: "var(--surface)" }} />
      </div>
    </div>
  );
}

function SourcesPageContent() {
  const { t, lang } = useT();
  const router = useRouter();
  const searchParams = useSearchParams();
  const sourceIdFromUrl = searchParams.get("sourceId");
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<MaterialStatusFilter>("all");
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const togglePicked = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const startGenerateFromSelection = () => {
    if (picked.size === 0) return;
    try {
      sessionStorage.setItem(
        "pendingGenerateSources",
        JSON.stringify(Array.from(picked)),
      );
    } catch {
      /* SSR / storage disabled — fine, the page will load empty */
    }
    router.push("/generate");
  };

  const loadSources = useCallback(async (options?: { background?: boolean }) => {
    if (!options?.background) setLoading(true);
    try {
      const res = await listSources();
      setSources(res.items);
      setTotal(res.total);
    } catch (e) {
      console.error("Failed to load sources:", e);
    } finally {
      if (!options?.background) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    const hasActive = sources.some((source) => isMaterialActive(source));
    if (!hasActive) return;
    const interval = window.setInterval(() => {
      void loadSources({ background: true });
    }, 3000);
    return () => window.clearInterval(interval);
  }, [loadSources, sources]);

  useEffect(() => {
    if (selectedSourceId && !sources.some((source) => source.id === selectedSourceId)) {
      setSelectedSourceId(null);
    }
  }, [selectedSourceId, sources]);

  useEffect(() => {
    if (!sourceIdFromUrl) return;
    if (sources.some((source) => source.id === sourceIdFromUrl)) {
      setSelectedSourceId(sourceIdFromUrl);
      return;
    }
    if (loading) return;

    let cancelled = false;
    getSource(sourceIdFromUrl)
      .then((source) => {
        if (cancelled) return;
        setSources((prev) =>
          prev.some((item) => item.id === source.id) ? prev : [source, ...prev],
        );
        setSelectedSourceId(source.id);
      })
      .catch((e) => {
        console.error("Failed to load linked source:", e);
      });
    return () => {
      cancelled = true;
    };
  }, [loading, sourceIdFromUrl, sources]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredSources = sources.filter((source) => {
    const title = (source.title || source.url || "").toLowerCase();
    const matchesQuery = normalizedQuery.length === 0 || title.includes(normalizedQuery);
    return matchesQuery && matchesMaterialStatusFilter(source, statusFilter);
  });

  const selectedSource = selectedSourceId
    ? sources.find((source) => source.id === selectedSourceId) ?? null
    : null;

  const STATUS_LABELS: Record<MaterialStatusFilter, string> = {
    all: t("sources.filterAll"),
    ready: t("sources.filterReady"),
    processing: t("sources.filterProcessing"),
    error: t("sources.filterError"),
  };

  return (
    <div style={{ padding: "32px 40px 80px", maxWidth: 1100, margin: "0 auto", width: "100%" }}>
      <PageHeader
        eyebrow={t("nav.sources")}
        title={t("sources.title")}
        subtitle={t("sources.subtitle")}
        action={
          <Link href="/import" className="btn btn-outline">
            <IcPlus size={14} />
            <span>{t("common.new")}</span>
          </Link>
        }
      />

      {sources.length > 0 ? <StatsStrip sources={sources} /> : null}

      {picked.size > 0 ? (
        <div
          style={{
            position: "sticky",
            top: 0,
            zIndex: 5,
            background: "var(--ink)",
            color: "var(--surface)",
            padding: "10px 16px",
            borderRadius: "var(--r-lg)",
            margin: "0 0 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <span style={{ fontSize: 13 }}>
            {t("sources.batchSelected").replace("{n}", String(picked.size))}
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="btn btn-sm"
              onClick={() => setPicked(new Set())}
              style={{ color: "var(--surface)" }}
            >
              {t("common.cancel")}
            </button>
            <button
              className="btn btn-accent btn-sm"
              onClick={startGenerateFromSelection}
            >
              <IcSparkle size={12} /> {t("sources.batchGenerate")}
            </button>
          </div>
        </div>
      ) : null}

      {/* Filter strip */}
      <div
        className="card-quiet"
        style={{
          padding: 12,
          marginBottom: 16,
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <label style={{ position: "relative", flex: 1, minWidth: 220 }}>
          <span className="sr-only">{t("common.search")}</span>
          <IcSearch
            size={14}
            style={{
              position: "absolute",
              left: 12,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--ink-3)",
              pointerEvents: "none",
            }}
          />
          <input
            className="input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={lang === "zh" ? "搜索资料标题" : "Search source titles"}
            style={{ paddingLeft: 32 }}
          />
        </label>

        <label style={{ position: "relative", minWidth: 180 }}>
          <span className="sr-only">状态筛选</span>
          <IcFilter
            size={14}
            style={{
              position: "absolute",
              left: 12,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--ink-3)",
              pointerEvents: "none",
            }}
          />
          <select
            aria-label="状态筛选"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as MaterialStatusFilter)}
            className="input"
            style={{ paddingLeft: 32, appearance: "none", cursor: "pointer" }}
          >
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <span style={{ fontSize: 12, color: "var(--ink-3)" }}>
          {lang === "zh"
            ? `当前显示 ${filteredSources.length} / ${total} 份资料`
            : `Showing ${filteredSources.length} / ${total} sources`}
        </span>
      </div>

      {loading ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "64px 0",
            gap: 8,
            color: "var(--ink-3)",
            fontSize: 13,
          }}
        >
          <IcLoader size={16} className="spin" />
          <span>{t("common.loading")}</span>
        </div>
      ) : sources.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 40 }}>
          <IcDoc size={28} style={{ color: "var(--ink-4)", margin: "0 auto 12px" }} />
          <h3 className="serif" style={{ fontSize: 17, margin: "0 0 6px" }}>
            {t("sources.empty")}
          </h3>
          <p style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 18 }}>
            {t("sources.emptyHint")}
          </p>
          <Link href="/import" className="btn btn-accent">
            <IcPlus size={14} />
            <span>{t("dashboard.importFirst")}</span>
          </Link>
        </div>
      ) : filteredSources.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 40 }}>
          <h3 className="serif" style={{ fontSize: 16 }}>{t("common.noResults")}</h3>
          <p style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 8 }}>
            {lang === "zh" ? "试试更换关键词，或切换状态筛选。" : "Try a different keyword or filter."}
          </p>
        </div>
      ) : (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: "var(--r-lg)",
            overflow: "hidden",
            background: "var(--surface)",
          }}
        >
          {/* Header row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "36px 1fr 110px 120px 90px 40px",
              padding: "10px 16px",
              borderBottom: "1px solid var(--border)",
              background: "var(--surface-2)",
              alignItems: "center",
              gap: 12,
            }}
          >
            <span />
            <Eyebrow>{t("sources.colName")}</Eyebrow>
            <Eyebrow>{t("sources.colLength")}</Eyebrow>
            <Eyebrow>{t("sources.colImported")}</Eyebrow>
            <Eyebrow>{t("sources.colCited")}</Eyebrow>
            <span />
          </div>

          {filteredSources.map((source, index) => {
            const presentation = deriveMaterialPresentation(source);
            const displayEmbed = deriveMaterialEmbed(source);
            const courseTaskActive = isCourseTaskActive(source);
            const isLast = index === filteredSources.length - 1;
            const meta = source.metadata_ as Record<string, unknown> | undefined;
            const lengthText =
              typeof meta?.duration === "string"
                ? meta.duration
                : typeof meta?.pages === "number"
                  ? `${meta.pages}p`
                  : typeof meta?.word_count === "number"
                    ? `${Math.round((meta.word_count as number) / 1000)}k`
                    : "—";
            const updated = new Date(source.updated_at).toLocaleDateString(
              lang === "zh" ? "zh-CN" : "en-US",
              { month: "short", day: "numeric" },
            );
            const isReady = source.status === "ready";
            const isPicked = picked.has(source.id);

            return (
              <div
                key={source.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "36px 1fr 110px 120px 90px 40px",
                  padding: "14px 16px",
                  borderBottom: isLast ? "none" : "1px solid var(--border-2)",
                  alignItems: "center",
                  gap: 12,
                  background: isPicked ? "var(--accent-soft)" : "transparent",
                  cursor: "pointer",
                  transition: "background var(--duration-fast) ease",
                }}
                onClick={() => setSelectedSourceId(source.id)}
                onMouseEnter={(e) => {
                  if (!isPicked) {
                    (e.currentTarget as HTMLDivElement).style.background =
                      "var(--surface-2)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isPicked) {
                    (e.currentTarget as HTMLDivElement).style.background =
                      "transparent";
                  }
                }}
              >
                {isReady ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      togglePicked(source.id);
                    }}
                    aria-label={isPicked ? "deselect" : "select"}
                    style={{
                      width: 18,
                      height: 18,
                      borderRadius: 4,
                      border:
                        "1.5px solid " +
                        (isPicked ? "var(--accent)" : "var(--border-strong)"),
                      background: isPicked ? "var(--accent)" : "transparent",
                      color: "white",
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    {isPicked ? <IcCheck size={12} /> : null}
                  </button>
                ) : (
                  <SourceIcon type={source.type} size={18} />
                )}
                <div style={{ minWidth: 0 }}>
                  <div
                    className="serif"
                    style={{
                      fontSize: 15,
                      fontWeight: 500,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {source.title || source.url || (lang === "zh" ? "未命名资料" : "Untitled source")}
                  </div>
                  <div
                    style={{
                      marginTop: 4,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      fontSize: 11,
                      color: "var(--ink-3)",
                    }}
                  >
                    {courseTaskActive ? (
                      <span className="chip chip-accent">
                        <span
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: "50%",
                            background: "var(--accent)",
                            boxShadow: "0 0 0 3px var(--accent-soft)",
                          }}
                        />
                        {presentation.badge}
                      </span>
                    ) : (
                      <EmbedChip embed={displayEmbed} />
                    )}
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {courseTaskActive
                        ? presentation.supportingText
                        : displayEmbed?.reason ?? displayEmbed?.error ?? presentation.supportingText}
                    </span>
                  </div>
                </div>
                <span className="mono num" style={{ fontSize: 12, color: "var(--ink-3)" }}>
                  {lengthText}
                </span>
                <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{updated}</span>
                <span
                  className="mono num"
                  style={{
                    fontSize: 12,
                    color: source.course_count > 0 ? "var(--accent)" : "var(--ink-2)",
                    fontWeight: source.course_count > 0 ? 500 : 400,
                  }}
                >
                  {source.course_count}×
                </span>
                <RowAction
                  source={source}
                  onGenerate={() => {
                    sessionStorage.setItem(
                      "pendingGenerateSources",
                      JSON.stringify([source.id]),
                    );
                    router.push("/generate");
                  }}
                  onReprocess={async () => {
                    await retrySource(source.id);
                    void loadSources({ background: true });
                  }}
                />
              </div>
            );
          })}
        </div>
      )}

      <SourceDetailDrawer
        onClose={() => setSelectedSourceId(null)}
        open={selectedSource !== null}
        source={selectedSource}
        onDeleted={(deletedId) => {
          setSources((prev) => prev.filter((s) => s.id !== deletedId));
          setTotal((prev) => Math.max(0, prev - 1));
        }}
        onChanged={() => {
          void loadSources({ background: true });
        }}
      />
    </div>
  );
}

/* PRD §5.3 — top-of-page stats strip. No card frame, just four big
   numbers with hairline dividers, derived from whatever the current
   /sources page returned. */
function StatsStrip({ sources }: { sources: SourceResponse[] }) {
  const { t } = useT();
  let ready = 0;
  let running = 0;
  let failed = 0;
  let stale = 0;
  for (const s of sources) {
    const presentation = deriveMaterialPresentation(s);
    const st = deriveMaterialEmbed(s)?.status;
    if (presentation.isActive) running++;
    else if (st === "ready") ready++;
    else if (st === "running" || st === "queued") running++;
    else if (st === "failed" || st === "cancelled") failed++;
    else if (st === "stale") stale++;
  }
  const cells = [
    { label: t("sources.statTotal"), value: sources.length, accent: "var(--ink)" },
    { label: t("sources.statReady"), value: ready, accent: "var(--sage)" },
    { label: t("sources.statRunning"), value: running, accent: "var(--accent)" },
    { label: t("sources.statFailed"), value: failed + stale, accent: "var(--error)" },
  ];
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        borderTop: "1px solid var(--border)",
        borderBottom: "1px solid var(--border)",
        margin: "0 0 24px",
      }}
    >
      {cells.map((c, i) => (
        <div
          key={c.label}
          style={{
            padding: "16px 12px",
            borderLeft: i === 0 ? "none" : "1px solid var(--border-2)",
          }}
        >
          <div className="eyebrow" style={{ marginBottom: 4 }}>
            {c.label}
          </div>
          <div
            className="display num"
            style={{
              fontSize: 28,
              color: c.accent,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}

/* 5-state embed chip. The badge color reflects the PRD §3 taxonomy. */
function EmbedChip({ embed }: { embed: import("@/lib/api").SourceEmbed | null | undefined }) {
  const { t } = useT();
  if (!embed) return null;
  const { status } = embed;
  const map = {
    ready: { label: t("sources.embedReady"), cls: "chip-sage", dot: "var(--sage)" },
    running: { label: t("sources.embedRunning"), cls: "chip-accent", dot: "var(--accent)" },
    queued: { label: t("sources.embedQueued"), cls: "", dot: "var(--ink-4)" },
    failed: {
      label: t("sources.embedFailed"),
      cls: "",
      dot: "var(--error)",
    },
    cancelled: {
      label: t("sources.embedCancelled"),
      cls: "",
      dot: "var(--error)",
    },
    stale: { label: t("sources.embedStale"), cls: "chip-warn", dot: "var(--warn)" },
  } as const;
  const m = map[status];
  return (
    <span
      className={`chip ${m.cls}`}
      style={
        status === "failed" || status === "cancelled"
          ? { background: "var(--error-soft)", color: "var(--error)" }
          : undefined
      }
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: m.dot,
          boxShadow:
            status === "running" ? "0 0 0 3px var(--accent-soft)" : undefined,
        }}
      />
      {m.label}
    </span>
  );
}

/* Right-most action button per row. The action depends on embed.status:
   ready → Generate course; failed/stale/cancelled → Re-process; running → spinner;
   else → no-op. */
function RowAction({
  source,
  onGenerate,
  onReprocess,
}: {
  source: SourceResponse;
  onGenerate: () => void;
  onReprocess: () => Promise<void>;
}) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const status = deriveMaterialEmbed(source)?.status ?? "queued";
  const courseTaskActive = isCourseTaskActive(source);

  if (courseTaskActive) {
    return (
      <span className="btn btn-ghost btn-icon btn-sm" aria-hidden>
        <IcLoader size={14} className="spin" />
      </span>
    );
  }

  if (status === "running") {
    return (
      <span className="btn btn-ghost btn-icon btn-sm" aria-hidden>
        <IcLoader size={14} className="spin" />
      </span>
    );
  }
  if (source.latest_course_id && status === "ready") {
    return (
      <span className="btn btn-ghost btn-icon btn-sm" aria-hidden>
        <IcMore size={14} />
      </span>
    );
  }
  if (status === "ready") {
    return (
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        style={{ color: "var(--accent)" }}
        title={t("sources.rowGenerate")}
        onClick={(e) => {
          e.stopPropagation();
          onGenerate();
        }}
      >
        <IcSparkle size={14} />
      </button>
    );
  }
  if (status === "failed" || status === "stale" || status === "cancelled") {
    return (
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        style={{ color: status === "stale" ? "var(--warn)" : "var(--error)" }}
        title={t("sources.rowReprocess")}
        disabled={busy}
        onClick={async (e) => {
          e.stopPropagation();
          setBusy(true);
          try {
            await onReprocess();
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? <IcLoader size={14} className="spin" /> : <IcRegen size={14} />}
      </button>
    );
  }
  return (
    <span className="btn btn-ghost btn-icon btn-sm" aria-hidden>
      <IcMore size={14} />
    </span>
  );
}
