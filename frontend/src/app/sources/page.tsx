"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import {
  IcDoc,
  IcFilter,
  IcLoader,
  IcMore,
  IcPlus,
  IcSearch,
  SourceIcon,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageHeader } from "@/components/ui/page-header";
import { listSources, type SourceResponse } from "@/lib/api";
import SourceDetailDrawer from "@/components/materials/source-detail-drawer";
import {
  deriveMaterialPresentation,
  isMaterialActive,
  matchesMaterialStatusFilter,
  type MaterialStatusFilter,
} from "@/lib/materials-state";
import { useT } from "@/lib/i18n";

export default function SourcesPage() {
  const { t, lang } = useT();
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<MaterialStatusFilter>("all");
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);

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

            return (
              <button
                key={source.id}
                type="button"
                onClick={() => setSelectedSourceId(source.id)}
                style={{
                  display: "grid",
                  gridTemplateColumns: "36px 1fr 110px 120px 90px 40px",
                  padding: "14px 16px",
                  borderBottom: isLast ? "none" : "1px solid var(--border-2)",
                  alignItems: "center",
                  gap: 12,
                  cursor: "pointer",
                  background: "transparent",
                  border: "none",
                  width: "100%",
                  textAlign: "left",
                  color: "inherit",
                  fontFamily: "inherit",
                  transition: "background var(--duration-fast) ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--surface-2)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              >
                <SourceIcon type={source.type} size={18} />
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
                    <span
                      className={`chip chip-mono ${
                        presentation.category === "error"
                          ? "chip-error"
                          : presentation.category === "processing"
                            ? "chip-warn"
                            : "chip-sage"
                      }`}
                    >
                      {presentation.badge}
                    </span>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {presentation.supportingText}
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
                <span className="btn btn-ghost btn-icon btn-sm" aria-hidden>
                  <IcMore size={14} />
                </span>
              </button>
            );
          })}
        </div>
      )}

      <SourceDetailDrawer
        onClose={() => setSelectedSourceId(null)}
        open={selectedSource !== null}
        source={selectedSource}
      />
    </div>
  );
}
