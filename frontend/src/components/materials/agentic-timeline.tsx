"use client";

import type { CSSProperties } from "react";

import {
  IcAlert,
  IcCheck,
  IcGraph,
  IcLoader,
  IcRegen,
  IcSpark,
} from "@/components/icons";
import type {
  ActivityItem,
  AgenticProgress,
  AgenticStep,
  CriticVerdict,
} from "@/lib/use-run-progress";

type Lang = "zh" | "en";

interface AgenticTimelineProps {
  agentic: AgenticProgress;
  /** Whether the run is still streaming — drives the "thinking" affordance. */
  running?: boolean;
  lang?: Lang;
}

/**
 * Live view of the course-generation graph's agentic reasoning, projected from
 * the AG-UI run stream (see {@link AgenticProgress}): outline planning, the
 * critic's verdict, and any backtrack / replan loops. Renders nothing until the
 * stream reports at least one agentic event, so non-agentic runs (or a dropped
 * SSE connection where polling is the only source) stay invisible — the
 * surrounding section-assembly panel remains the authoritative progress UI.
 */
export default function AgenticTimeline({
  agentic,
  running = false,
  lang = "zh",
}: AgenticTimelineProps) {
  if (!agentic.active) return null;

  const zh = lang === "zh";
  const orderedSteps = [...agentic.steps].sort((a, b) => a.order - b.order);
  const orderedActivities = [...agentic.activities].sort((a, b) => a.order - b.order);

  return (
    <section
      className="rounded-2xl p-4"
      style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
      aria-label={zh ? "智能体编排" : "Agentic orchestration"}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span style={{ color: "var(--accent)" }}>
            <IcGraph size={15} />
          </span>
          <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
            {zh ? "智能体编排" : "Agentic steps"}
          </h3>
        </div>
        {running ? (
          <span className="chip chip-accent" style={{ height: 22 }}>
            <IcLoader size={11} className="spin" />
            {zh ? "推理中" : "Thinking"}
          </span>
        ) : null}
      </div>

      {orderedSteps.length > 0 ? (
        <ol className="mt-3 space-y-2">
          {orderedSteps.map((step, idx) => (
            <StepRow
              key={step.name}
              step={step}
              last={idx === orderedSteps.length - 1}
              zh={zh}
            />
          ))}
        </ol>
      ) : null}

      {orderedActivities.length > 0 ? (
        <ol className="mt-3 space-y-1.5">
          {orderedActivities.map((a) => (
            <ActivityRow key={a.id} activity={a} zh={zh} />
          ))}
        </ol>
      ) : null}

      {orderedSteps.length === 0 && orderedActivities.length === 0 ? (
        <p className="mt-3 text-xs" style={{ color: "var(--ink-3)" }}>
          {zh ? "已启动，正在准备…" : "Started — preparing…"}
        </p>
      ) : null}

      {agentic.replans > 0 || agentic.backtracks.length > 0 ? (
        <div className="mt-3 space-y-2">
          {agentic.replans > 0 ? (
            <ReplanBanner count={agentic.replans} zh={zh} />
          ) : null}
          {agentic.backtracks.map((b, i) => (
            <BacktrackBanner key={i} backtrack={b} zh={zh} />
          ))}
        </div>
      ) : null}

      {agentic.critic ? (
        <div className="mt-3">
          <CriticCard verdict={agentic.critic} zh={zh} />
        </div>
      ) : null}
    </section>
  );
}

// --- step labels -----------------------------------------------------------

// Friendly names for the graph node / plan-step ids the backend emits via
// STEP_STARTED / STEP_FINISHED. Unknown ids fall back to the raw name so a new
// topology still renders something readable.
const STEP_LABELS: Record<string, { zh: string; en: string }> = {
  plan_outline: { zh: "规划大纲", en: "Plan outline" },
  outline: { zh: "规划大纲", en: "Plan outline" },
  plan: { zh: "制定计划", en: "Plan" },
  execute: { zh: "执行计划", en: "Execute" },
  explore: { zh: "探索资料", en: "Explore" },
  draft: { zh: "起草内容", en: "Draft" },
  assemble: { zh: "装配课程", en: "Assemble" },
  critic: { zh: "质量评审", en: "Critic" },
};

function stepLabel(name: string, zh: boolean): string {
  const entry = STEP_LABELS[name];
  if (entry) return zh ? entry.zh : entry.en;
  return name;
}

// Friendly names for the narrated tool-call tags the pipeline emits via
// TOOL_CALL_START (e.g. "extract.bilibili"). Exact match first, then a
// verb-prefix fallback so a new "verb.target" tag still reads sensibly.
const ACTIVITY_LABELS: Record<string, { zh: string; en: string }> = {
  "extract.bilibili": { zh: "抓取 B站字幕", en: "Fetch Bilibili subtitles" },
  "extract.youtube": { zh: "抓取 YouTube 字幕", en: "Fetch YouTube transcript" },
  "extract.pdf": { zh: "解析 PDF", en: "Parse PDF" },
  "extract.url": { zh: "抓取网页", en: "Fetch web page" },
  "extract.markdown": { zh: "解析 Markdown", en: "Parse Markdown" },
  "extract.text": { zh: "读取文本", en: "Read text" },
  "analyze.content": { zh: "分析内容结构", en: "Analyze content" },
  "embed.vectors": { zh: "向量化", en: "Embed vectors" },
  "plan.sections": { zh: "规划章节", en: "Plan sections" },
  "references.search": { zh: "检索参考文献", en: "Search references" },
};

const ACTIVITY_VERBS: Record<string, { zh: string; en: string }> = {
  extract: { zh: "提取", en: "Extract" },
  analyze: { zh: "分析", en: "Analyze" },
  embed: { zh: "向量化", en: "Embed" },
  plan: { zh: "规划", en: "Plan" },
  references: { zh: "检索文献", en: "References" },
};

function activityLabel(name: string, zh: boolean): string {
  const entry = ACTIVITY_LABELS[name];
  if (entry) return zh ? entry.zh : entry.en;
  const [verb, rest] = name.split(".");
  const v = ACTIVITY_VERBS[verb];
  if (v) return `${zh ? v.zh : v.en}${rest ? ` ${rest}` : ""}`;
  return name;
}

function ActivityRow({ activity, zh }: { activity: ActivityItem; zh: boolean }) {
  const running = activity.state === "running";
  const sub = activity.result || activity.detail;
  return (
    <li className="flex items-center gap-3">
      <span
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
        style={{
          background: running ? "var(--accent-soft)" : "var(--sage-soft)",
          color: running ? "var(--accent-ink)" : "var(--sage-ink)",
          border: "1px solid var(--border)",
        }}
      >
        {running ? <IcLoader size={11} className="spin" /> : <IcCheck size={11} />}
      </span>
      <div className="flex min-w-0 flex-1 items-baseline gap-2">
        <span
          className="text-[13px]"
          style={{
            color: running ? "var(--ink)" : "var(--ink-2)",
            fontWeight: running ? 500 : 400,
          }}
        >
          {activityLabel(activity.name, zh)}
        </span>
        {sub ? (
          <span className="truncate text-xs" style={{ color: "var(--ink-3)" }}>
            {sub}
          </span>
        ) : null}
      </div>
      <span className="mono shrink-0 text-[11px]" style={{ color: "var(--ink-4)" }}>
        {activity.name}
      </span>
    </li>
  );
}

function StepRow({
  step,
  last,
  zh,
}: {
  step: AgenticStep;
  last: boolean;
  zh: boolean;
}) {
  const running = step.state === "running";
  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <span
          className="inline-flex h-6 w-6 items-center justify-center rounded-full"
          style={{
            background: running ? "var(--accent-soft)" : "var(--sage-soft)",
            color: running ? "var(--accent-ink)" : "var(--sage-ink)",
            border: "1px solid var(--border)",
          }}
        >
          {running ? (
            <IcLoader size={13} className="spin" />
          ) : (
            <IcCheck size={13} />
          )}
        </span>
        {!last ? (
          <span
            className="mt-1 h-full min-h-4 w-px"
            style={{ background: "var(--border)" }}
          />
        ) : null}
      </div>
      <div className="min-w-0 flex-1 pb-1">
        <div className="flex items-center justify-between gap-2">
          <span
            className="text-sm"
            style={{
              color: running ? "var(--ink)" : "var(--ink-2)",
              fontWeight: running ? 500 : 400,
            }}
          >
            {stepLabel(step.name, zh)}
          </span>
          <span className="mono text-[11px]" style={{ color: "var(--ink-4)" }}>
            {step.name}
          </span>
        </div>
        {running ? (
          <p className="mt-0.5 text-xs" style={{ color: "var(--ink-3)" }}>
            {zh ? "进行中…" : "In progress…"}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function CriticCard({ verdict, zh }: { verdict: CriticVerdict; zh: boolean }) {
  const tone: CSSProperties = verdict.passed
    ? { background: "var(--sage-soft)", borderColor: "transparent", color: "var(--sage-ink)" }
    : { background: "var(--warn-soft)", borderColor: "transparent", color: "var(--warn)" };
  const scoreEntries = Object.entries(verdict.scores);

  return (
    <div className="rounded-xl border p-3" style={tone}>
      <div className="flex items-center gap-2">
        {verdict.passed ? <IcCheck size={14} /> : <IcAlert size={14} />}
        <span className="text-sm font-medium">
          {zh
            ? verdict.passed
              ? "质量评审通过"
              : "质量评审未通过"
            : verdict.passed
              ? "Critic passed"
              : "Critic flagged issues"}
        </span>
      </div>
      {verdict.feedback ? (
        <p className="mt-1.5 text-xs leading-relaxed" style={{ color: "var(--ink-2)" }}>
          {verdict.feedback}
        </p>
      ) : null}
      {scoreEntries.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {scoreEntries.map(([key, val]) => (
            <span
              key={key}
              className="rounded-full px-2 py-0.5 text-[11px] mono"
              style={{ background: "var(--surface)", color: "var(--ink-2)" }}
            >
              {key}: {typeof val === "number" ? val.toFixed(2) : String(val)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function BacktrackBanner({
  backtrack,
  zh,
}: {
  backtrack: AgenticProgress["backtracks"][number];
  zh: boolean;
}) {
  const target = backtrack.to ? stepLabel(backtrack.to, zh) : null;
  return (
    <div
      className="flex items-start gap-2 rounded-xl border px-3 py-2"
      style={{ background: "var(--accent-soft)", borderColor: "transparent" }}
    >
      <span style={{ color: "var(--accent-ink)" }} className="mt-0.5 shrink-0">
        <IcRegen size={14} />
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium" style={{ color: "var(--accent-ink)" }}>
          {zh
            ? `正在重新规划${target ? `（回到「${target}」）` : ""}`
            : `Backtracking${target ? ` to “${target}”` : ""}`}
          {backtrack.budgetLeft !== null ? (
            <span className="ml-1 font-normal" style={{ opacity: 0.8 }}>
              {zh ? `· 剩余 ${backtrack.budgetLeft} 次` : `· ${backtrack.budgetLeft} left`}
            </span>
          ) : null}
        </p>
        {backtrack.feedback ? (
          <p className="mt-0.5 text-xs" style={{ color: "var(--ink-2)" }}>
            {backtrack.feedback}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ReplanBanner({ count, zh }: { count: number; zh: boolean }) {
  return (
    <div
      className="flex items-center gap-2 rounded-xl border px-3 py-2"
      style={{ background: "var(--accent-soft)", borderColor: "transparent" }}
    >
      <span style={{ color: "var(--accent-ink)" }} className="shrink-0">
        <IcSpark size={14} />
      </span>
      <p className="text-xs font-medium" style={{ color: "var(--accent-ink)" }}>
        {zh
          ? `正在重新规划…${count > 1 ? `（第 ${count} 次）` : ""}`
          : `Re-planning…${count > 1 ? ` (attempt ${count})` : ""}`}
      </p>
    </div>
  );
}
