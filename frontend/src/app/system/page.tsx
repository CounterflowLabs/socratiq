"use client";

import * as React from "react";
import { useMemo } from "react";

import {
  IcAlert,
  IcArrowLeft,
  IcArrowRight,
  IcArrowUp,
  IcBarChart,
  IcBookmark,
  IcChevronDown,
  IcChevronLeft,
  IcChevronRight,
  IcChevronUp,
  IcCheck,
  IcCheckCircle,
  IcCite,
  IcClock,
  IcClose,
  IcConcept,
  IcDesign,
  IcDiagnostic,
  IcDoc,
  IcEdit,
  IcExercise,
  IcExternal,
  IcFilter,
  IcFolder,
  IcGraph,
  IcHome,
  IcImport,
  IcInfo,
  IcLab,
  IcLang,
  IcLesson,
  IcLink,
  IcLoader,
  IcMemory,
  IcMentor,
  IcMessage,
  IcMenu,
  IcMoon,
  IcMore,
  IcPanelLeftClose,
  IcPanelLeftOpen,
  IcPath,
  IcPlay,
  IcPlus,
  IcRegen,
  IcReview,
  IcSearch,
  IcSend,
  IcSettings,
  IcSources,
  IcSpark,
  IcSparkle,
  IcSun,
  IcTV,
  IcTrash,
  IcUpload,
  IcUser,
  IcVideo,
  SocratiqLogo,
  SocratiqMark,
  SocratiqMarkAccent,
  type IconProps,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Ornament } from "@/components/ui/ornament";
import { PageHeader } from "@/components/ui/page-header";
import { SectionTitle } from "@/components/ui/section-title";
import { useT } from "@/lib/i18n";

interface Swatch {
  name: string;
  hex: string;
  token: string;
  big?: boolean;
}

export default function SystemPage() {
  const { t, lang } = useT();

  const allIcons: Array<[string, (p: IconProps) => React.ReactElement]> = useMemo(
    () => [
      ["Home", IcHome],
      ["Spark", IcSpark],
      ["Import", IcImport],
      ["Graph", IcGraph],
      ["Sources", IcSources],
      ["Settings", IcSettings],
      ["Design", IcDesign],
      ["Plus", IcPlus],
      ["Search", IcSearch],
      ["ArrowR", IcArrowRight],
      ["ArrowL", IcArrowLeft],
      ["ChevR", IcChevronRight],
      ["ChevL", IcChevronLeft],
      ["ChevD", IcChevronDown],
      ["ChevU", IcChevronUp],
      ["Close", IcClose],
      ["Menu", IcMenu],
      ["More", IcMore],
      ["Check", IcCheck],
      ["CheckCircle", IcCheckCircle],
      ["Alert", IcAlert],
      ["Info", IcInfo],
      ["Loader", IcLoader],
      ["Lesson", IcLesson],
      ["Concept", IcConcept],
      ["Mentor", IcMentor],
      ["Exercise", IcExercise],
      ["Lab", IcLab],
      ["Review", IcReview],
      ["Diagnostic", IcDiagnostic],
      ["Cite", IcCite],
      ["Path", IcPath],
      ["Video", IcVideo],
      ["Doc", IcDoc],
      ["Bookmark", IcBookmark],
      ["TV", IcTV],
      ["Folder", IcFolder],
      ["Send", IcSend],
      ["Trash", IcTrash],
      ["Edit", IcEdit],
      ["Filter", IcFilter],
      ["Clock", IcClock],
      ["Memory", IcMemory],
      ["Sun", IcSun],
      ["Moon", IcMoon],
      ["Lang", IcLang],
      ["Link", IcLink],
      ["ArrowUp", IcArrowUp],
      ["Sparkle", IcSparkle],
      ["User", IcUser],
      ["Regen", IcRegen],
      ["External", IcExternal],
      ["Upload", IcUpload],
      ["Message", IcMessage],
      ["Play", IcPlay],
      ["BarChart", IcBarChart],
      ["PanelL-Close", IcPanelLeftClose],
      ["PanelL-Open", IcPanelLeftOpen],
    ],
    [],
  );

  const swatches: Swatch[] = [
    { name: "bg", hex: "#f3ede1", token: "--bg" },
    { name: "surface", hex: "#faf6ed", token: "--surface" },
    { name: "surface-2", hex: "#ebe2d0", token: "--surface-2" },
    { name: "ink", hex: "#1a1611", token: "--ink" },
    { name: "ink-2", hex: "#5c5448", token: "--ink-2" },
    { name: "ink-3", hex: "#8b8270", token: "--ink-3" },
    { name: "accent", hex: "#c96442", token: "--accent", big: true },
    { name: "accent-soft", hex: "#f0e0d2", token: "--accent-soft" },
    { name: "sage", hex: "#6b7d5b", token: "--sage" },
    { name: "sage-soft", hex: "#dde2d4", token: "--sage-soft" },
    { name: "warn", hex: "#b8842a", token: "--warn" },
    { name: "error", hex: "#b3422f", token: "--error" },
  ];

  return (
    <div style={{ padding: "32px 40px 80px", maxWidth: 1100, margin: "0 auto", width: "100%" }}>
      <PageHeader eyebrow="v2.0" title={t("system.title")} subtitle={t("system.subtitle")} />

      {/* Mark */}
      <section style={{ marginBottom: "var(--gap-xl)" }}>
        <SectionTitle>{t("system.mark")}</SectionTitle>
        <div
          className="card"
          style={{
            padding: 0,
            overflow: "hidden",
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
          }}
        >
          <div
            style={{
              padding: 32,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRight: "1px solid var(--border)",
              background: "var(--surface)",
            }}
          >
            <SocratiqMark size={84} stroke={1.4} />
          </div>
          <div
            style={{
              padding: 32,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRight: "1px solid var(--border)",
              background: "var(--surface-2)",
            }}
          >
            <SocratiqMarkAccent size={84} />
          </div>
          <div
            style={{
              padding: 32,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "var(--ink)",
              color: "var(--surface)",
            }}
          >
            <SocratiqLogo size={36} color="var(--surface)" />
          </div>
        </div>
        <div
          style={{
            marginTop: 24,
            fontSize: 14,
            color: "var(--ink-2)",
            maxWidth: 580,
            lineHeight: 1.6,
            fontFamily: "var(--serif)",
          }}
        >
          {t("system.markCaption")}
        </div>
      </section>

      {/* Color */}
      <section style={{ marginBottom: "var(--gap-xl)" }}>
        <SectionTitle>{t("system.color")}</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 8 }}>
          {swatches.map((swatch) => (
            <SwatchCard key={swatch.token} swatch={swatch} />
          ))}
        </div>
      </section>

      {/* Type */}
      <section style={{ marginBottom: "var(--gap-xl)" }}>
        <SectionTitle>{t("system.type")}</SectionTitle>
        <div className="card" style={{ padding: 32 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr",
              gap: 20,
              alignItems: "baseline",
            }}
          >
            <span className="eyebrow">Display · Serif</span>
            <div>
              <div className="display" style={{ fontSize: 56, lineHeight: 1, marginBottom: 8 }}>
                Source Serif 4
              </div>
              <div
                className="mono"
                style={{ fontSize: 11, color: "var(--ink-3)" }}
              >
                headlines · lesson titles · marks
              </div>
            </div>

            <span className="eyebrow">Body · Sans</span>
            <div>
              <div
                style={{
                  fontSize: 28,
                  fontFamily: "var(--sans)",
                  fontWeight: 500,
                  marginBottom: 4,
                }}
              >
                Geist
              </div>
              <div style={{ fontSize: 14, color: "var(--ink-2)" }}>
                Aa Bb 12345 — interface chrome, controls, body copy.
              </div>
            </div>

            <span className="eyebrow">Mono</span>
            <div>
              <div style={{ fontSize: 22, fontFamily: "var(--mono)", marginBottom: 4 }}>
                Geist Mono
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: "var(--ink-3)",
                  fontFamily: "var(--mono)",
                }}
              >
                L07 · 14:23 · rate(http_requests_total[5m])
              </div>
            </div>

            <span className="eyebrow">CJK</span>
            <div>
              <div
                style={{
                  fontSize: 22,
                  fontFamily: "var(--serif)",
                  marginBottom: 4,
                }}
              >
                {lang === "zh" ? "思源宋体 / Noto Serif SC" : "Noto Serif SC"}
              </div>
              <div style={{ fontSize: 14, color: "var(--ink-2)" }}>
                {lang === "zh"
                  ? "正文采用 Noto Sans SC — 与 Geist 的字重梯度匹配，避免中英文混排时的视觉断层。"
                  : "Body copy uses Noto Sans SC — matched in weight to Geist, so mixed CJK/Latin runs read evenly."}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Icons */}
      <section style={{ marginBottom: "var(--gap-xl)" }}>
        <SectionTitle
          count={allIcons.length}
          action={
            <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
              1.5px stroke · 24×24
            </span>
          }
        >
          {t("system.icons")}
        </SectionTitle>
        <div className="card" style={{ padding: 0 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(108px, 1fr))",
              gap: 0,
            }}
          >
            {allIcons.map(([name, Icon], i) => (
              <div
                key={name}
                style={{
                  padding: "20px 12px",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 10,
                  borderRight: (i + 1) % 8 !== 0 ? "1px solid var(--border-2)" : "none",
                  borderBottom: i < allIcons.length - 8 ? "1px solid var(--border-2)" : "none",
                  color: "var(--ink)",
                }}
              >
                <Icon size={22} stroke={1.5} />
                <span
                  className="mono"
                  style={{ fontSize: 10, color: "var(--ink-3)", textAlign: "center" }}
                >
                  {name}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Components */}
      <section style={{ marginBottom: "var(--gap-xl)" }}>
        <SectionTitle>{t("system.components")}</SectionTitle>
        <div
          className="card"
          style={{
            padding: 28,
            display: "flex",
            flexDirection: "column",
            gap: 24,
          }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <Eyebrow>buttons</Eyebrow>
            <button type="button" className="btn btn-primary">
              <IcArrowRight size={14} />
              Primary
            </button>
            <button type="button" className="btn btn-accent">
              <IcSparkle size={14} />
              Accent
            </button>
            <button type="button" className="btn btn-outline">
              Outline
            </button>
            <button type="button" className="btn btn-ghost">
              Ghost
            </button>
            <button type="button" className="btn btn-primary btn-lg">
              Large
            </button>
            <button type="button" className="btn btn-outline btn-sm">
              Small
            </button>
          </div>
          <hr className="divider" />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <Eyebrow>chips</Eyebrow>
            <span className="chip">Default</span>
            <span className="chip chip-accent">Accent</span>
            <span className="chip chip-sage">Sage</span>
            <span className="chip chip-warn">Warn</span>
            <span className="chip chip-error">Error</span>
            <span className="chip chip-mono">L07 · 14:23</span>
          </div>
          <hr className="divider" />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <Eyebrow>input</Eyebrow>
            <input className="input" placeholder="Default input" style={{ width: 240 }} />
            <input className="input input-lg" placeholder="Large" style={{ width: 240 }} />
          </div>
          <hr className="divider" />
          <div>
            <Eyebrow>ornament</Eyebrow>
            <Ornament />
          </div>
        </div>
      </section>
    </div>
  );
}

function SwatchCard({ swatch }: { swatch: Swatch }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        overflow: "hidden",
        gridColumn: swatch.big ? "span 2" : "auto",
      }}
    >
      <div style={{ background: swatch.hex, height: swatch.big ? 88 : 64 }} />
      <div style={{ padding: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 500 }}>{swatch.name}</div>
        <div className="mono" style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 2 }}>
          {swatch.hex}
        </div>
        <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>
          {swatch.token}
        </div>
      </div>
    </div>
  );
}
