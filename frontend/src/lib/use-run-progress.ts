"use client";

import { useEffect, useState } from "react";

import { streamRunEvents, type AGUIEvent } from "./api";

export type RunStatus = "idle" | "running" | "finished" | "error";

export interface RunProgress {
  /** Latest STATE_SNAPSHOT payload (the section_progress dict), or null. */
  snapshot: Record<string, unknown> | null;
  runStatus: RunStatus;
  error: string | null;
}

/**
 * Subscribe to a task run's live AG-UI event stream and project STATE_SNAPSHOT /
 * STATE_DELTA into a kept state object. Pass `active=false` (or null ids) to
 * stay idle — the caller's existing polling remains the fallback when no live
 * stream is running. The worker currently emits full snapshots; delta handling
 * is here for forward-compat with StateProjector.
 */
export function useRunProgress(
  sourceId: string | null | undefined,
  runId: string | null | undefined,
  active: boolean
): RunProgress {
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active || !sourceId || !runId) {
      setSnapshot(null);
      setRunStatus("idle");
      setError(null);
      return;
    }

    const ac = new AbortController();
    let cancelled = false;
    setRunStatus("running");
    setError(null);

    (async () => {
      try {
        for await (const evt of streamRunEvents(sourceId, runId, ac.signal)) {
          if (cancelled) break;
          applyEvent(evt, { setSnapshot, setRunStatus, setError });
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
  }, [sourceId, runId, active]);

  return { snapshot, runStatus, error };
}

function applyEvent(
  evt: AGUIEvent,
  setters: {
    setSnapshot: (fn: (prev: Record<string, unknown> | null) => Record<string, unknown> | null) => void;
    setRunStatus: (s: RunStatus) => void;
    setError: (e: string | null) => void;
  }
): void {
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
    case "RUN_FINISHED":
      setters.setRunStatus("finished");
      break;
    case "RUN_ERROR":
      setters.setRunStatus("error");
      setters.setError(typeof evt.message === "string" ? evt.message : "运行出错");
      break;
    default:
      break;
  }
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
