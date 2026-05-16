"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  IcAlert,
  IcArrowRight,
  IcCheck,
  IcClose,
  IcImport,
  IcLoader,
  IcPlus,
  IcSparkle,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageHeader } from "@/components/ui/page-header";
import { useT } from "@/lib/i18n";
import {
  cancelTask,
  listTasks,
  retryTask,
  type TaskListItem,
  type TaskListResponse,
  type TaskStatusUi,
  type TaskTypeUi,
} from "@/lib/api";

const POLL_MS = 4000;

export default function TasksPage() {
  const { t } = useT();
  const router = useRouter();
  const [data, setData] = useState<TaskListResponse | null>(null);
  const [typeFilter, setTypeFilter] = useState<"all" | TaskTypeUi>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | TaskStatusUi>("all");
  const [error, setError] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await listTasks({ type: typeFilter, status: statusFilter, limit: 100 });
      setData(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [typeFilter, statusFilter]);

  useEffect(() => {
    fetchTasks();
    const id = setInterval(fetchTasks, POLL_MS);
    return () => clearInterval(id);
  }, [fetchTasks]);

  const counts = data?.counts_by_type ?? {};
  const statusCounts = data?.counts_by_status ?? {};

  const typeOptions: { v: "all" | TaskTypeUi; label: string; count: number }[] = [
    { v: "all", label: t("tasks.typeAll"), count: counts.all ?? 0 },
    { v: "embed", label: t("tasks.typeEmbed"), count: counts.embed ?? 0 },
    { v: "generate", label: t("tasks.typeGenerate"), count: counts.generate ?? 0 },
  ];

  const statusOptions: { v: "all" | TaskStatusUi; label: string; count: number; dot?: string }[] = [
    { v: "all", label: t("tasks.statusAll"), count: statusCounts.all ?? 0 },
    { v: "running", label: t("tasks.statusRunning"), count: statusCounts.running ?? 0, dot: "var(--accent)" },
    { v: "queued", label: t("tasks.statusQueued"), count: statusCounts.queued ?? 0, dot: "var(--ink-4)" },
    { v: "done", label: t("tasks.statusDone"), count: statusCounts.done ?? 0, dot: "var(--sage)" },
    { v: "failed", label: t("tasks.statusFailed"), count: statusCounts.failed ?? 0, dot: "var(--error)" },
  ];

  return (
    <div className="page">
      <PageHeader
        eyebrow={t("nav.tasks")}
        title={t("tasks.title")}
        subtitle={t("tasks.subtitle")}
      />

      {/* Type tabs */}
      <div
        style={{
          display: "flex",
          gap: 4,
          borderBottom: "1px solid var(--border)",
          marginTop: "var(--gap-lg)",
          marginBottom: "var(--gap)",
        }}
      >
        {typeOptions.map((opt) => (
          <TabButton
            key={opt.v}
            active={typeFilter === opt.v}
            onClick={() => setTypeFilter(opt.v)}
          >
            {opt.label}
            <span
              className="num"
              style={{
                color: "var(--ink-3)",
                fontSize: 12,
                fontVariantNumeric: "tabular-nums",
                marginLeft: 4,
              }}
            >
              {opt.count}
            </span>
          </TabButton>
        ))}
      </div>

      {/* Status chips */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: "var(--gap-lg)" }}>
        {statusOptions.map((opt) => (
          <StatusChip
            key={opt.v}
            active={statusFilter === opt.v}
            dot={opt.dot}
            onClick={() => setStatusFilter(opt.v)}
          >
            {opt.label}
            <span
              className="num"
              style={{ fontVariantNumeric: "tabular-nums", marginLeft: 4 }}
            >
              {opt.count}
            </span>
          </StatusChip>
        ))}
      </div>

      {error && (
        <div
          className="card-soft"
          style={{ borderColor: "var(--error)", color: "var(--error)", marginBottom: 16 }}
        >
          {error}
        </div>
      )}

      {/* Tasks list */}
      {data === null ? null : data.items.length === 0 ? (
        <EmptyState t={t} />
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-lg)",
            background: "var(--surface)",
            overflow: "hidden",
          }}
        >
          {data.items.map((task, i) => (
            <TaskRow
              key={task.id}
              task={task}
              isLast={i === data.items.length - 1}
              onActionDone={fetchTasks}
              onOpenCourse={(courseId) => router.push(`/learn?courseId=${courseId}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "transparent",
        border: "none",
        cursor: "pointer",
        padding: "10px 14px",
        font: "500 13px var(--sans)",
        color: active ? "var(--ink)" : "var(--ink-2)",
        borderBottom: active ? "2px solid var(--ink)" : "2px solid transparent",
        marginBottom: -1,
      }}
    >
      {children}
    </button>
  );
}

function StatusChip({
  active,
  dot,
  onClick,
  children,
}: {
  active: boolean;
  dot?: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="chip"
      style={{
        cursor: "pointer",
        background: active ? "var(--ink)" : "var(--surface-2)",
        color: active ? "var(--surface)" : "var(--ink-2)",
        borderColor: active ? "var(--ink)" : "var(--border)",
        height: 24,
      }}
    >
      {dot && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: active ? "var(--surface)" : dot,
          }}
        />
      )}
      {children}
    </button>
  );
}

function EmptyState({ t }: { t: ReturnType<typeof useT>["t"] }) {
  return (
    <div
      className="hatched"
      style={{
        textAlign: "center",
        padding: "64px 24px",
        borderRadius: "var(--r-lg)",
        border: "1px solid var(--border)",
      }}
    >
      <p className="serif" style={{ fontSize: 20, color: "var(--ink-2)", margin: "0 0 24px" }}>
        {t("tasks.empty")}
      </p>
      <div style={{ display: "inline-flex", gap: 12 }}>
        <Link href="/import" className="btn btn-outline btn-lg">
          <IcPlus size={14} /> {t("tasks.emptyAddSource")}
        </Link>
        <Link href="/generate" className="btn btn-primary btn-lg">
          <IcSparkle size={14} /> {t("tasks.emptyGenerate")}
        </Link>
      </div>
    </div>
  );
}

function TaskRow({
  task,
  isLast,
  onActionDone,
  onOpenCourse,
}: {
  task: TaskListItem;
  isLast: boolean;
  onActionDone: () => void;
  onOpenCourse: (courseId: string) => void;
}) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);

  const handleCancel = async () => {
    setBusy(true);
    try {
      await cancelTask(task.id);
      onActionDone();
    } finally {
      setBusy(false);
    }
  };
  const handleRetry = async () => {
    setBusy(true);
    try {
      await retryTask(task.id);
      onActionDone();
    } finally {
      setBusy(false);
    }
  };

  const typeLabel = task.type === "embed" ? t("tasks.typeEmbed") : t("tasks.typeGenerate");
  const typeChipClass = task.type === "embed" ? "chip-accent" : "chip-sage";
  const startedAgo = useMemo(() => relativeTime(task.started_at), [task.started_at]);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto auto auto",
        gap: 16,
        padding: "14px 20px",
        alignItems: "center",
        borderBottom: isLast ? "none" : "1px solid var(--border-2)",
      }}
    >
      <span className={`chip ${typeChipClass}`}>{typeLabel}</span>

      <div style={{ minWidth: 0 }}>
        <div
          className="serif"
          style={{
            fontSize: 15,
            color: "var(--ink)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {task.course_title ?? task.source_title ?? task.id.slice(0, 8)}
        </div>
        {task.error ? (
          <div style={{ fontSize: 12, color: "var(--error)", marginTop: 2 }}>{task.error}</div>
        ) : task.cancel_requested ? (
          <div style={{ fontSize: 12, color: "var(--warn)", marginTop: 2 }}>
            {t("tasks.cancelRequested")}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 2 }}>
            {task.raw_task_type}
          </div>
        )}
      </div>

      <span
        className="mono"
        style={{
          fontSize: 12,
          color: "var(--ink-3)",
          display: "inline-flex",
          flexDirection: "column",
          gap: 4,
          minWidth: 160,
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <StatusDot status={task.status} />
          {task.stage ?? task.status}
          {task.eta_seconds != null && task.status === "running" ? (
            <span style={{ color: "var(--ink-4)" }}>
              · ~{formatEta(task.eta_seconds)}
            </span>
          ) : null}
        </span>
        {task.status === "running" ? (
          <StageProgressBar type={task.type} stage={task.stage} />
        ) : null}
      </span>

      <span
        className="mono"
        style={{ fontSize: 12, color: "var(--ink-3)", whiteSpace: "nowrap" }}
      >
        {startedAgo}
      </span>

      <RowAction
        task={task}
        busy={busy}
        onCancel={handleCancel}
        onRetry={handleRetry}
        onOpenCourse={onOpenCourse}
      />
    </div>
  );
}

function RowAction({
  task,
  busy,
  onCancel,
  onRetry,
  onOpenCourse,
}: {
  task: TaskListItem;
  busy: boolean;
  onCancel: () => void;
  onRetry: () => void;
  onOpenCourse: (id: string) => void;
}) {
  if (busy) return <IcLoader size={14} className="spin" />;
  if (task.status === "running" || task.status === "queued") {
    return (
      <button onClick={onCancel} className="btn btn-icon btn-sm btn-ghost" aria-label="cancel">
        <IcClose size={14} />
      </button>
    );
  }
  if (task.status === "failed") {
    return (
      <button
        onClick={onRetry}
        className="btn btn-sm"
        style={{ background: "var(--warn-soft)", color: "var(--warn)" }}
      >
        <IcAlert size={12} /> 重试
      </button>
    );
  }
  if (task.status === "done" && task.course_id) {
    return (
      <button
        onClick={() => onOpenCourse(task.course_id!)}
        className="btn btn-sm btn-ghost"
      >
        <IcArrowRight size={14} />
      </button>
    );
  }
  return <span style={{ width: 26 }} />;
}

const STAGE_PERCENT: Record<string, Record<string, number>> = {
  embed: {
    pending: 0,
    fetch_extract: 12,
    extracting: 20,
    analyzing: 45,
    chunking: 55,
    embedding: 75,
    storing: 90,
    generating_lessons: 70,
    generating_labs: 80,
    ready: 100,
  },
  generate: {
    pending: 0,
    planning: 15,
    analyzing: 30,
    drafting: 50,
    assembling_course: 75,
    ready: 100,
    generating: 50,
  },
};

export function stageToPercent(type: TaskTypeUi, stage?: string | null): number {
  if (!stage) return 5;
  const table = STAGE_PERCENT[type] ?? {};
  return table[stage] ?? 35;
}

function StageProgressBar({
  type,
  stage,
}: {
  type: TaskTypeUi;
  stage?: string | null;
}) {
  const pct = stageToPercent(type, stage);
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 100,
        height: 3,
        borderRadius: 999,
        background: "var(--surface-2)",
        overflow: "hidden",
      }}
    >
      <span
        style={{
          display: "block",
          width: `${pct}%`,
          height: "100%",
          background: type === "embed" ? "var(--accent)" : "var(--sage)",
          transition: "width 240ms ease",
        }}
      />
    </span>
  );
}

function StatusDot({ status }: { status: TaskStatusUi }) {
  const color =
    status === "running"
      ? "var(--accent)"
      : status === "queued"
        ? "var(--ink-4)"
        : status === "done"
          ? "var(--sage)"
          : "var(--error)";
  return (
    <span
      style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: color,
        display: "inline-block",
        boxShadow:
          status === "running" ? "0 0 0 3px var(--accent-soft)" : undefined,
      }}
    />
  );
}

function formatEta(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}min`;
  return `${Math.round(seconds / 3600)}h`;
}

function relativeTime(iso: string): string {
  try {
    const then = new Date(iso).getTime();
    const diff = Date.now() - then;
    const s = Math.floor(diff / 1000);
    if (s < 60) return `${s}s 前`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}min 前`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h 前`;
    const d = Math.floor(h / 24);
    return `${d}d 前`;
  } catch {
    return iso;
  }
}
