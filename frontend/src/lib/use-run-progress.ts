"use client";

import { useCallback, useEffect, useState } from "react";

import {
  streamCourseRunEvents,
  streamRunEvents,
  type AGUIEvent,
} from "./api";

export type RunStatus = "idle" | "running" | "finished" | "error";

export type AgenticStepState = "running" | "done";

/** One graph node / plan step, projected from STEP_STARTED / STEP_FINISHED. */
export interface AgenticStep {
  /** The `stepName` carried by the AG-UI step events (e.g. "plan_outline"). */
  name: string;
  state: AgenticStepState;
  /** Monotonic order in which the step first started (for stable rendering). */
  order: number;
}

/**
 * One narrated tool call — a deterministic pipeline sub-step (extract, analyze,
 * embed, fetch references…), projected from the TOOL_CALL_* event span. Same
 * wire shape a real model-driven tool call uses, so both render identically.
 */
export interface ActivityItem {
  /** The `toolCallId` shared by START / ARGS / RESULT / END. */
  id: string;
  /** Stable technical tag from TOOL_CALL_START (e.g. "extract.bilibili"). */
  name: string;
  /** Short argument preview parsed from TOOL_CALL_ARGS, or null. */
  detail: string | null;
  /** Outcome summary from TOOL_CALL_RESULT, or null. */
  result: string | null;
  state: AgenticStepState;
  /** Monotonic order in which the call first started (stable rendering). */
  order: number;
}

/** Latest critic verdict, projected from a CUSTOM `critic_verdict` event. */
export interface CriticVerdict {
  passed: boolean;
  scores: Record<string, number>;
  feedback: string | null;
}

/** A backtrack hop, projected from a CUSTOM `backtrack` event. */
export interface BacktrackEvent {
  from: string | null;
  to: string | null;
  feedback: string | null;
  budgetLeft: number | null;
}

/**
 * The agentic-graph projection: the live "thinking" of the course-generation
 * graph (outline planning → critic verdict → backtrack/replan), distinct from
 * the section-assembly `snapshot`. All fields are empty until the corresponding
 * events arrive, so a run that emits no agentic events renders nothing.
 */
export interface AgenticProgress {
  steps: AgenticStep[];
  /** Live narrated tool calls (pipeline sub-steps), in start order. */
  activities: ActivityItem[];
  critic: CriticVerdict | null;
  backtracks: BacktrackEvent[];
  /** Count of CUSTOM `replan` events seen so far. */
  replans: number;
  /** True once any agentic step / verdict has been observed on the stream. */
  active: boolean;
}

export interface RunProgress {
  /** Latest STATE_SNAPSHOT payload (the section_progress dict), or null. */
  snapshot: Record<string, unknown> | null;
  /** Live projection of the agentic graph's steps / verdicts. */
  agentic: AgenticProgress;
  runStatus: RunStatus;
  error: string | null;
  /** New course id carried by RUN_FINISHED's `result.course_id`, once seen.
   *  Source-scoped runs don't emit it (the course id arrives via polling), so
   *  this stays null there; the source-less prompt run uses it to navigate. */
  courseId: string | null;
}

const EMPTY_AGENTIC: AgenticProgress = {
  steps: [],
  activities: [],
  critic: null,
  backtracks: [],
  replans: 0,
  active: false,
};

/** Builds the AG-UI event stream for a run, or null when the hook is idle. */
type StreamFactory = ((signal: AbortSignal) => AsyncGenerator<AGUIEvent>) | null;

/**
 * Shared core: subscribe to a run's live AG-UI event stream (built by
 * `streamFactory`) and project it into kept state: STATE_SNAPSHOT / STATE_DELTA
 * → `snapshot` (section-assembly progress), STEP_STARTED / STEP_FINISHED /
 * CUSTOM(critic_verdict|backtrack|replan) → `agentic` (the graph's live
 * reasoning), and RUN_FINISHED's `result.course_id` → `courseId`. A null
 * factory stays idle — the caller's existing polling remains the fallback when
 * no live stream is running. The worker currently emits full snapshots; delta
 * handling is here for forward-compat with StateProjector.
 *
 * `streamFactory` must be stable for the run (wrap it in `useCallback` keyed on
 * the run identifiers); it is the effect's only dependency.
 */
function useRunProgressCore(streamFactory: StreamFactory): RunProgress {
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [agentic, setAgentic] = useState<AgenticProgress>(EMPTY_AGENTIC);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [courseId, setCourseId] = useState<string | null>(null);

  useEffect(() => {
    if (!streamFactory) {
      setSnapshot(null);
      setAgentic(EMPTY_AGENTIC);
      setRunStatus("idle");
      setError(null);
      setCourseId(null);
      return;
    }

    const ac = new AbortController();
    let cancelled = false;
    setRunStatus("running");
    setError(null);

    (async () => {
      try {
        for await (const evt of streamFactory(ac.signal)) {
          if (cancelled) break;
          applyEvent(evt, { setSnapshot, setAgentic, setRunStatus, setError, setCourseId });
        }
      } catch (err) {
        // A dropped stream is non-fatal: polling still surfaces progress.
        if (!cancelled && !ac.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    })();

    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [streamFactory]);

  return { snapshot, agentic, runStatus, error, courseId };
}

/**
 * Subscribe to a *source-scoped* task run's live AG-UI event stream. See
 * {@link useRunProgressCore} for the projection. Pass `active=false` (or null
 * ids) to stay idle.
 */
export function useRunProgress(
  sourceId: string | null | undefined,
  runId: string | null | undefined,
  active: boolean
): RunProgress {
  const factory = useCallback<NonNullable<StreamFactory>>(
    (signal) => streamRunEvents(sourceId as string, runId as string, signal),
    [sourceId, runId],
  );
  return useRunProgressCore(active && Boolean(sourceId) && Boolean(runId) ? factory : null);
}

/**
 * Subscribe to a *source-less* course run's live AG-UI event stream (the
 * one-sentence → course flow). Same projection as {@link useRunProgress};
 * `runId` is the task id from `createCourseFromPrompt`, and the new course id
 * surfaces on {@link RunProgress.courseId} when RUN_FINISHED arrives.
 */
export function useCourseRunProgress(
  runId: string | null | undefined,
  active: boolean
): RunProgress {
  const factory = useCallback<NonNullable<StreamFactory>>(
    (signal) => streamCourseRunEvents(runId as string, signal),
    [runId],
  );
  return useRunProgressCore(active && Boolean(runId) ? factory : null);
}

interface EventSetters {
  setSnapshot: (fn: (prev: Record<string, unknown> | null) => Record<string, unknown> | null) => void;
  setAgentic: (fn: (prev: AgenticProgress) => AgenticProgress) => void;
  setRunStatus: (s: RunStatus) => void;
  setError: (e: string | null) => void;
  setCourseId: (id: string | null) => void;
}

function applyEvent(evt: AGUIEvent, setters: EventSetters): void {
  switch (evt.type) {
    case "STATE_SNAPSHOT":
      if (evt.snapshot && typeof evt.snapshot === "object") {
        const snap = evt.snapshot as Record<string, unknown>;
        setters.setSnapshot(() => snap);
      }
      break;
    case "STATE_DELTA": {
      const ops = (evt as { delta?: unknown }).delta;
      if (Array.isArray(ops)) {
        setters.setSnapshot((prev) => applyJsonPatch(prev ?? {}, ops as JsonPatchOp[]));
      }
      break;
    }
    case "RUN_STARTED":
      // Mark the agentic projection active so the timeline can render its
      // "run started" affordance even before the first step arrives.
      setters.setAgentic((prev) => (prev.active ? prev : { ...prev, active: true }));
      break;
    case "STEP_STARTED":
      setters.setAgentic((prev) => upsertStep(prev, stepName(evt), "running"));
      break;
    case "STEP_FINISHED":
      setters.setAgentic((prev) => upsertStep(prev, stepName(evt), "done"));
      break;
    case "CUSTOM":
      setters.setAgentic((prev) => applyCustom(prev, evt));
      break;
    case "TOOL_CALL_START":
      setters.setAgentic((prev) => startActivity(prev, evt));
      break;
    case "TOOL_CALL_ARGS":
      setters.setAgentic((prev) => updateActivity(prev, evt, { detail: argsDetail(evt.delta) }));
      break;
    case "TOOL_CALL_RESULT":
      setters.setAgentic((prev) =>
        updateActivity(prev, evt, {
          result: typeof evt.content === "string" ? evt.content : null,
        }),
      );
      break;
    case "TOOL_CALL_END":
      setters.setAgentic((prev) => updateActivity(prev, evt, { state: "done" }));
      break;
    case "RUN_FINISHED": {
      setters.setRunStatus("finished");
      // Any step still flagged running never received its STEP_FINISHED (the
      // worker closes the stream first); settle them so the UI doesn't spin.
      setters.setAgentic((prev) => settleSteps(prev));
      // Source-less course runs carry the new course id here (snake_case, it
      // rides inside the Any-typed `result` dict the backend serializes
      // verbatim); the prompt flow reads it to navigate to the course.
      const cid = evt.result?.course_id;
      if (typeof cid === "string" && cid.length > 0) {
        setters.setCourseId(cid);
      }
      break;
    }
    case "RUN_ERROR":
      setters.setRunStatus("error");
      setters.setError(typeof evt.message === "string" ? evt.message : "运行出错");
      break;
    default:
      break;
  }
}

/** The AG-UI step events carry the node name under `stepName` (camelCase wire). */
function stepName(evt: AGUIEvent): string {
  const raw = (evt as { stepName?: unknown }).stepName ?? (evt as { name?: unknown }).name;
  return typeof raw === "string" && raw.length > 0 ? raw : "step";
}

function upsertStep(
  prev: AgenticProgress,
  name: string,
  state: AgenticStepState,
): AgenticProgress {
  const steps = [...prev.steps];
  const idx = steps.findIndex((s) => s.name === name);
  if (idx >= 0) {
    // A backtrack re-enters an already-finished node, so the latest event wins
    // (re-started ⇒ running again, then done). Keep the original order.
    steps[idx] = { ...steps[idx], state };
  } else {
    steps.push({ name, state, order: steps.length });
  }
  return { ...prev, steps, active: true };
}

function settleSteps(prev: AgenticProgress): AgenticProgress {
  const stepsRunning = prev.steps.some((s) => s.state === "running");
  const actsRunning = prev.activities.some((a) => a.state === "running");
  if (!stepsRunning && !actsRunning) return prev;
  return {
    ...prev,
    steps: prev.steps.map((s) => (s.state === "running" ? { ...s, state: "done" } : s)),
    activities: prev.activities.map((a) =>
      a.state === "running" ? { ...a, state: "done" } : a,
    ),
  };
}

/** TOOL_CALL_START → append a running activity (idempotent on toolCallId). */
function startActivity(prev: AgenticProgress, evt: AGUIEvent): AgenticProgress {
  const id = typeof evt.toolCallId === "string" ? evt.toolCallId : "";
  if (!id) return prev;
  if (prev.activities.some((a) => a.id === id)) return { ...prev, active: true };
  const name =
    typeof evt.toolCallName === "string" && evt.toolCallName.length > 0
      ? evt.toolCallName
      : "tool";
  return {
    ...prev,
    active: true,
    activities: [
      ...prev.activities,
      { id, name, detail: null, result: null, state: "running", order: prev.activities.length },
    ],
  };
}

/** Merge a partial update into the activity addressed by `toolCallId`. */
function updateActivity(
  prev: AgenticProgress,
  evt: AGUIEvent,
  patch: Partial<Pick<ActivityItem, "detail" | "result" | "state">>,
): AgenticProgress {
  const id = typeof evt.toolCallId === "string" ? evt.toolCallId : "";
  if (!id) return prev;
  const idx = prev.activities.findIndex((a) => a.id === id);
  if (idx < 0) return prev;
  const activities = [...prev.activities];
  activities[idx] = { ...activities[idx], ...patch };
  return { ...prev, activities };
}

/** Distill a TOOL_CALL_ARGS JSON payload into a one-line detail, or null. */
function argsDetail(delta: unknown): string | null {
  if (typeof delta !== "string" || delta.length === 0) return null;
  try {
    const obj = JSON.parse(delta);
    if (!isRecord(obj)) return null;
    const parts: string[] = [];
    for (const [k, v] of Object.entries(obj)) {
      if (v == null) continue;
      let s = Array.isArray(v) ? v.slice(0, 3).join(", ") : String(v);
      if (k === "url" && s.length > 48) s = s.slice(0, 48) + "…";
      if (s.length > 0) parts.push(s);
    }
    return parts.length ? parts.join(" · ") : null;
  } catch {
    return null;
  }
}

function applyCustom(prev: AgenticProgress, evt: AGUIEvent): AgenticProgress {
  const name = typeof evt.name === "string" ? evt.name : "";
  const value = evt.value;
  switch (name) {
    case "critic_verdict": {
      const v = isRecord(value) ? value : {};
      return {
        ...prev,
        active: true,
        critic: {
          passed: v.passed === true,
          scores: isRecord(v.scores) ? (v.scores as Record<string, number>) : {},
          feedback: typeof v.feedback === "string" ? v.feedback : null,
        },
      };
    }
    case "backtrack": {
      const v = isRecord(value) ? value : {};
      return {
        ...prev,
        active: true,
        backtracks: [
          ...prev.backtracks,
          {
            from: typeof v.from === "string" ? v.from : null,
            to: typeof v.to === "string" ? v.to : null,
            feedback: typeof v.feedback === "string" ? v.feedback : null,
            budgetLeft: typeof v.budget_left === "number" ? v.budget_left : null,
          },
        ],
      };
    }
    case "replan":
      return { ...prev, active: true, replans: prev.replans + 1 };
    default:
      return prev;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// --- minimal RFC 6901 / 6902 (mirrors backend StateProjector._apply_ops) ----

export interface JsonPatchOp {
  op: "add" | "replace" | "remove" | "move";
  path: string;
  value?: unknown;
  from?: string;
}

function unescape(token: string): string {
  return token.replace(/~1/g, "/").replace(/~0/g, "~");
}

function splitPointer(path: string): string[] {
  if (path === "") return [];
  if (!path.startsWith("/")) throw new Error(`invalid JSON Pointer: ${path}`);
  return path.split("/").slice(1).map(unescape);
}

type Container = Record<string, unknown> | unknown[];

function resolveParent(doc: Container, tokens: string[]): [Container, string | number] {
  let cur: unknown = doc;
  for (const tok of tokens.slice(0, -1)) {
    cur = Array.isArray(cur) ? cur[Number(tok)] : (cur as Record<string, unknown>)[tok];
  }
  const last = tokens[tokens.length - 1];
  if (Array.isArray(cur)) {
    return [cur, last === "-" ? cur.length : Number(last)];
  }
  return [cur as Record<string, unknown>, last];
}

/** Apply RFC 6902 ops, returning a new document (input is not mutated). */
export function applyJsonPatch(
  doc: Record<string, unknown>,
  ops: JsonPatchOp[]
): Record<string, unknown> {
  let next = structuredClone(doc) as Container;
  for (const op of ops) {
    const tokens = splitPointer(op.path);
    if (tokens.length === 0) {
      if (op.op === "replace" || op.op === "add") {
        next = structuredClone(op.value) as Container;
        continue;
      }
      throw new Error(`op ${op.op} not supported on root path`);
    }
    const [container, key] = resolveParent(next, tokens);
    if (op.op === "add" || op.op === "replace") {
      const value = structuredClone(op.value);
      if (Array.isArray(container) && op.op === "add") {
        container.splice(key as number, 0, value);
      } else if (Array.isArray(container)) {
        container[key as number] = value;
      } else {
        container[key as string] = value;
      }
    } else if (op.op === "remove") {
      if (Array.isArray(container)) container.splice(key as number, 1);
      else delete container[key as string];
    } else if (op.op === "move") {
      const fromTokens = splitPointer(op.from ?? "");
      const [src, srcKey] = resolveParent(next, fromTokens);
      const moved = Array.isArray(src) ? src[srcKey as number] : src[srcKey as string];
      if (Array.isArray(src)) src.splice(srcKey as number, 1);
      else delete src[srcKey as string];
      if (Array.isArray(container)) container.splice(key as number, 0, moved);
      else container[key as string] = moved;
    }
  }
  return next as Record<string, unknown>;
}
