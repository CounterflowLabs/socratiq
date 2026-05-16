"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  IcArrowRight,
  IcCheck,
  IcImport,
  IcLoader,
  IcSparkle,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageHeader } from "@/components/ui/page-header";
import { useT } from "@/lib/i18n";
import {
  generateCourse,
  listSources,
  type SourceResponse,
} from "@/lib/api";

interface GenConfig {
  brief: string;
  depth: number;
  audience: "intro" | "mid" | "adv";
  tier: "fast" | "smart";
  lang: "source" | "zh" | "en";
  includes: { exercises: boolean; lab: boolean; review: boolean };
}

const DEFAULT_CFG: GenConfig = {
  brief: "",
  depth: 12,
  audience: "mid",
  tier: "smart",
  lang: "source",
  includes: { exercises: true, lab: true, review: true },
};

export default function GeneratePage() {
  const { t } = useT();
  const router = useRouter();

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  // PRD §10 v2 — per-source weight (1 = baseline, ± shifts emphasis when
  // the backend later weights chunks). Persisted only inside the task
  // metadata for now so the weighting algorithm can land separately.
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [cfg, setCfg] = useState<GenConfig>(DEFAULT_CFG);
  const [sources, setSources] = useState<SourceResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dispatched, setDispatched] = useState<
    { taskId: string; sourceIds: string[] } | null
  >(null);

  const adjustWeight = (id: string, delta: number) =>
    setWeights((prev) => {
      const current = prev[id] ?? 1;
      const next = Math.max(0, Math.min(3, current + delta));
      if (next === 1) {
        const copy = { ...prev };
        delete copy[id];
        return copy;
      }
      return { ...prev, [id]: next };
    });

  // Initial source list. Honor any pre-pick passed via sessionStorage from
  // the Sources page "Generate from selection" CTA.
  useEffect(() => {
    listSources()
      .then((res) => {
        setSources(res.items);
        try {
          const raw = sessionStorage.getItem("pendingGenerateSources");
          if (raw) {
            sessionStorage.removeItem("pendingGenerateSources");
            const ids = JSON.parse(raw) as string[];
            setPicked(new Set(ids));
          }
        } catch {
          /* sessionStorage unavailable — fine */
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const ready = useMemo(
    () => (sources ?? []).filter((s) => s.status === "ready"),
    [sources],
  );
  const pendingCount = useMemo(
    () => (sources ?? []).filter((s) => s.status !== "ready").length,
    [sources],
  );
  const pickedList = useMemo(
    () => ready.filter((s) => picked.has(s.id)),
    [ready, picked],
  );

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const startGeneration = useCallback(async () => {
    setError(null);
    setStep(3);
    try {
      const res = await generateCourse({
        source_ids: pickedList.map((s) => s.id),
        title: cfg.brief.slice(0, 80) || undefined,
        brief: cfg.brief || undefined,
        depth: cfg.depth,
        audience: cfg.audience,
        tier: cfg.tier,
        language: cfg.lang,
        includes: cfg.includes,
        source_weights: pickedList
          .filter((s) => (weights[s.id] ?? 1) !== 1)
          .reduce<Record<string, number>>((acc, s) => {
            acc[s.id] = weights[s.id];
            return acc;
          }, {}),
      });
      setDispatched({
        taskId: res.task_id,
        sourceIds: pickedList.map((s) => s.id),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [pickedList, cfg]);

  return (
    <div className="page page-narrow">
      <PageHeader
        eyebrow={t("tasks.typeGenerate")}
        title={t("generate.title")}
        subtitle={t("generate.subtitle")}
      />

      <Stepper
        step={step}
        labels={[t("generate.step1"), t("generate.step2"), t("generate.step3")]}
        onJump={(n) => {
          if (n < step) setStep(n as 1 | 2 | 3);
        }}
      />

      {error && (
        <div
          className="card-soft"
          style={{
            borderColor: "var(--error)",
            color: "var(--error)",
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      )}

      {step === 1 && (
        <StepPick
          ready={ready}
          picked={picked}
          toggle={toggle}
          weights={weights}
          adjustWeight={adjustWeight}
          pendingCount={pendingCount}
          loaded={sources !== null}
          onNext={() => setStep(2)}
        />
      )}
      {step === 2 && (
        <StepConfigure
          cfg={cfg}
          setCfg={setCfg}
          pickedList={pickedList}
          onBack={() => setStep(1)}
          onRun={startGeneration}
        />
      )}
      {step === 3 && (
        <StepRun
          dispatched={dispatched}
          pickedList={pickedList}
          onOpenTasks={() => router.push("/tasks")}
        />
      )}
    </div>
  );
}

/* ─── Stepper ─── */
function Stepper({
  step,
  labels,
  onJump,
}: {
  step: number;
  labels: string[];
  onJump: (n: number) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: "var(--gap-xl)",
      }}
    >
      {labels.map((label, i) => {
        const n = i + 1;
        const active = n === step;
        const done = n < step;
        return (
          <div key={n} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              onClick={() => onJump(n)}
              disabled={n > step}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 10px",
                borderRadius: 100,
                border: "1px solid " + (active ? "var(--ink)" : "var(--border)"),
                background: active ? "var(--surface-2)" : "transparent",
                cursor: n < step ? "pointer" : "default",
                font: "inherit",
                color: active
                  ? "var(--ink)"
                  : done
                    ? "var(--ink-2)"
                    : "var(--ink-3)",
              }}
            >
              <span
                className="mono num"
                style={{ fontSize: 11, color: "var(--ink-3)" }}
              >
                {n}
              </span>
              <span style={{ fontSize: 13 }}>{label}</span>
            </button>
            {n < labels.length && (
              <span style={{ color: "var(--ink-3)" }}>·</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Step 1: pick sources ─── */
function StepPick({
  ready,
  picked,
  toggle,
  weights,
  adjustWeight,
  pendingCount,
  loaded,
  onNext,
}: {
  ready: SourceResponse[];
  picked: Set<string>;
  toggle: (id: string) => void;
  weights: Record<string, number>;
  adjustWeight: (id: string, delta: number) => void;
  pendingCount: number;
  loaded: boolean;
  onNext: () => void;
}) {
  const { t } = useT();
  if (!loaded) return null;

  return (
    <div>
      <p style={{ color: "var(--ink-2)", marginBottom: 16 }}>
        {t("generate.pickSubtitle")}
      </p>

      {ready.length === 0 ? (
        <div
          className="hatched"
          style={{
            padding: "48px 24px",
            borderRadius: "var(--r-lg)",
            border: "1px solid var(--border)",
            textAlign: "center",
          }}
        >
          <p
            className="serif"
            style={{ fontSize: 18, color: "var(--ink-2)", margin: "0 0 20px" }}
          >
            {t("generate.pickEmpty")}
          </p>
          <Link href="/import" className="btn btn-primary btn-lg">
            <IcImport size={14} /> {t("nav.import")}
          </Link>
        </div>
      ) : (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: "var(--r-lg)",
            background: "var(--surface)",
            overflow: "hidden",
            marginBottom: 16,
          }}
        >
          {ready.map((s, idx) => (
            <SourcePickRow
              key={s.id}
              source={s}
              picked={picked.has(s.id)}
              weight={weights[s.id] ?? 1}
              onAdjustWeight={(delta) => adjustWeight(s.id, delta)}
              isLast={idx === ready.length - 1}
              onToggle={() => toggle(s.id)}
            />
          ))}
        </div>
      )}

      {pendingCount > 0 ? (
        <p style={{ fontSize: 12, color: "var(--ink-3)", marginBottom: 16 }}>
          {t("generate.pickPending").replace("{n}", String(pendingCount))}
        </p>
      ) : null}

      <div
        style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}
      >
        <button
          className="btn btn-primary btn-lg"
          disabled={picked.size === 0}
          onClick={onNext}
        >
          {t("generate.btnNext")} <IcArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}

function SourcePickRow({
  source,
  picked,
  weight,
  onAdjustWeight,
  isLast,
  onToggle,
}: {
  source: SourceResponse;
  picked: boolean;
  weight: number;
  onAdjustWeight: (delta: number) => void;
  isLast: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 16px",
        width: "100%",
        background: picked ? "var(--accent-soft)" : "transparent",
        border: "none",
        borderBottom: isLast ? "none" : "1px solid var(--border-2)",
        textAlign: "left",
        cursor: "pointer",
      }}
    >
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: 4,
          border: "1.5px solid " + (picked ? "var(--accent)" : "var(--border-strong)"),
          background: picked ? "var(--accent)" : "transparent",
          color: "white",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {picked ? <IcCheck size={12} /> : null}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span
          className="serif"
          style={{
            color: "var(--ink)",
            fontSize: 15,
            display: "block",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {source.title || source.url || source.id.slice(0, 8)}
        </span>
        <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{source.type}</span>
      </span>
      {picked ? <WeightChip weight={weight} onAdjust={onAdjustWeight} /> : null}
    </div>
  );
}

function WeightChip({
  weight,
  onAdjust,
}: {
  weight: number;
  onAdjust: (delta: number) => void;
}) {
  const isDefault = weight === 1;
  return (
    <span
      onClick={(e) => e.stopPropagation()}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: isDefault ? "var(--surface-2)" : "var(--accent-soft)",
        color: isDefault ? "var(--ink-2)" : "var(--accent-ink)",
        padding: "2px 4px",
        borderRadius: 999,
        fontSize: 11,
        flexShrink: 0,
      }}
      title="Generate-time weight for this source"
    >
      <button
        type="button"
        onClick={() => onAdjust(-0.5)}
        disabled={weight <= 0}
        aria-label="decrease weight"
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          border: "none",
          background: "transparent",
          color: "inherit",
          cursor: weight <= 0 ? "default" : "pointer",
          opacity: weight <= 0 ? 0.4 : 1,
        }}
      >
        −
      </button>
      <span className="mono num" style={{ fontVariantNumeric: "tabular-nums", minWidth: 18, textAlign: "center" }}>
        ×{weight.toFixed(1)}
      </span>
      <button
        type="button"
        onClick={() => onAdjust(0.5)}
        disabled={weight >= 3}
        aria-label="increase weight"
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          border: "none",
          background: "transparent",
          color: "inherit",
          cursor: weight >= 3 ? "default" : "pointer",
          opacity: weight >= 3 ? 0.4 : 1,
        }}
      >
        +
      </button>
    </span>
  );
}

/* ─── Step 2: configure ─── */
function StepConfigure({
  cfg,
  setCfg,
  pickedList,
  onBack,
  onRun,
}: {
  cfg: GenConfig;
  setCfg: (c: GenConfig) => void;
  pickedList: SourceResponse[];
  onBack: () => void;
  onRun: () => void;
}) {
  const { t } = useT();
  return (
    <div>
      {/* Sticky summary of picked sources */}
      <div
        className="card-soft"
        style={{ marginBottom: 24, padding: 12, fontSize: 13, color: "var(--ink-2)" }}
      >
        {pickedList.length}：{pickedList.map((s) => s.title || s.id.slice(0, 6)).join("、")}
      </div>

      <Field label={t("generate.configTitle")}>
        <textarea
          className="input"
          style={{ height: 88, padding: 12, resize: "vertical" }}
          value={cfg.brief}
          placeholder={t("generate.configTitlePlaceholder")}
          onChange={(e) => setCfg({ ...cfg, brief: e.target.value })}
        />
      </Field>

      <Field label={`${t("generate.configDepth")} · ${cfg.depth}`}>
        <input
          type="range"
          min={6}
          max={24}
          step={1}
          value={cfg.depth}
          onChange={(e) => setCfg({ ...cfg, depth: Number(e.target.value) })}
          style={{ width: "100%" }}
        />
      </Field>

      <Field label={t("generate.configAudience")}>
        <Segments
          value={cfg.audience}
          options={[
            { v: "intro", label: t("generate.configAudienceIntro") },
            { v: "mid", label: t("generate.configAudienceMid") },
            { v: "adv", label: t("generate.configAudienceAdv") },
          ]}
          onChange={(v) => setCfg({ ...cfg, audience: v })}
        />
      </Field>

      <Field label={t("generate.configTier")}>
        <Segments
          value={cfg.tier}
          options={[
            { v: "fast", label: t("generate.configTierFast") },
            { v: "smart", label: t("generate.configTierSmart") },
          ]}
          onChange={(v) => setCfg({ ...cfg, tier: v })}
        />
      </Field>

      <Field label={t("generate.configLang")}>
        <Segments
          value={cfg.lang}
          options={[
            { v: "source", label: t("generate.configLangSource") },
            { v: "zh", label: t("generate.configLangZh") },
            { v: "en", label: t("generate.configLangEn") },
          ]}
          onChange={(v) => setCfg({ ...cfg, lang: v })}
        />
      </Field>

      <Field label={t("generate.configIncludes")}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Toggle
            label={t("generate.configExercises")}
            on={cfg.includes.exercises}
            onChange={(v) =>
              setCfg({ ...cfg, includes: { ...cfg.includes, exercises: v } })
            }
          />
          <Toggle
            label={t("generate.configLab")}
            on={cfg.includes.lab}
            onChange={(v) =>
              setCfg({ ...cfg, includes: { ...cfg.includes, lab: v } })
            }
          />
          <Toggle
            label={t("generate.configReview")}
            on={cfg.includes.review}
            onChange={(v) =>
              setCfg({ ...cfg, includes: { ...cfg.includes, review: v } })
            }
          />
        </div>
      </Field>

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 32 }}>
        <button className="btn btn-outline btn-lg" onClick={onBack}>
          {t("generate.btnBack")}
        </button>
        <button className="btn btn-accent btn-lg" onClick={onRun}>
          <IcSparkle size={14} /> {t("generate.btnRun")}
        </button>
      </div>
    </div>
  );
}

/* ─── Step 3: run ─── */
function StepRun({
  dispatched,
  pickedList,
  onOpenTasks,
}: {
  dispatched: { taskId: string; sourceIds: string[] } | null;
  pickedList: SourceResponse[];
  onOpenTasks: () => void;
}) {
  const { t } = useT();
  if (dispatched === null) {
    return (
      <div style={{ textAlign: "center", padding: 64 }}>
        <IcLoader size={20} className="spin" />
        <p style={{ marginTop: 12, color: "var(--ink-2)" }}>
          {t("generate.runEyebrow")}…
        </p>
      </div>
    );
  }
  return (
    <div className="card" style={{ textAlign: "center" }}>
      <Eyebrow>{t("generate.runEyebrow")}</Eyebrow>
      <p
        className="mono"
        style={{ fontSize: 12, color: "var(--ink-3)", margin: "8px 0 4px" }}
      >
        task {dispatched.taskId.slice(0, 8)}
      </p>
      <h2 className="serif" style={{ fontSize: 22, margin: "8px 0 4px" }}>
        {pickedList.length === 1
          ? pickedList[0].title
          : `${pickedList.length} sources → 1 course`}
      </h2>
      <p style={{ color: "var(--ink-2)", margin: "0 0 16px", fontSize: 13 }}>
        {t("generate.runHint")}
      </p>
      <div
        style={{
          display: "inline-flex",
          gap: 8,
          flexWrap: "wrap",
          justifyContent: "center",
        }}
      >
        <button className="btn btn-outline" onClick={onOpenTasks}>
          {t("generate.runViewTasks")}
        </button>
      </div>
      <ul
        style={{
          textAlign: "left",
          fontSize: 12,
          color: "var(--ink-3)",
          marginTop: 16,
          listStyle: "none",
          paddingLeft: 0,
        }}
      >
        {pickedList.map((s) => (
          <li key={s.id}>· {s.title}</li>
        ))}
      </ul>
    </div>
  );
}

/* ─── helpers ─── */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <label
        style={{
          display: "block",
          fontSize: 12,
          color: "var(--ink-2)",
          marginBottom: 6,
          fontWeight: 500,
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

function Segments<V extends string>({
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
        background: "var(--surface-2)",
        borderRadius: "var(--r)",
        padding: 2,
        gap: 2,
      }}
    >
      {options.map((opt) => (
        <button
          key={opt.v}
          onClick={() => onChange(opt.v)}
          style={{
            padding: "6px 12px",
            borderRadius: "var(--r-sm)",
            border: "none",
            background: value === opt.v ? "var(--surface)" : "transparent",
            color: value === opt.v ? "var(--ink)" : "var(--ink-2)",
            cursor: "pointer",
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Toggle({
  label,
  on,
  onChange,
}: {
  label: string;
  on: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!on)}
      style={{
        padding: "8px 14px",
        borderRadius: "var(--r)",
        border: "1px solid " + (on ? "var(--accent)" : "var(--border)"),
        background: on ? "var(--accent-soft)" : "var(--surface)",
        color: on ? "var(--accent-ink)" : "var(--ink-2)",
        cursor: "pointer",
        fontSize: 13,
        display: "inline-flex",
        gap: 6,
        alignItems: "center",
      }}
    >
      {on ? <IcCheck size={12} /> : null}
      {label}
    </button>
  );
}
