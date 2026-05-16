"use client";

import { useEffect } from "react";

export type ConfirmDialogTone = "default" | "destructive" | "alert";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ConfirmDialogTone;
  // When true, the confirm button shows a spinner-friendly state and is
  // disabled. Caller is responsible for flipping it back after the action.
  busy?: boolean;
  onConfirm: () => void;
  // Tone "alert" hides the cancel button — onCancel is then only fired via
  // backdrop click or Escape key (and behaves like dismiss).
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  tone = "default",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onCancel]);

  if (!open) return null;

  const confirmBg =
    tone === "destructive"
      ? "var(--error)"
      : tone === "alert"
        ? "var(--ink)"
        : "var(--accent)";
  const confirmHover =
    tone === "destructive"
      ? "#8a3324"
      : tone === "alert"
        ? "var(--ink-2)"
        : "var(--accent-hover)";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <button
        type="button"
        aria-label="关闭"
        onClick={onCancel}
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(26, 22, 17, 0.42)",
          backdropFilter: "blur(2px)",
          border: 0,
          padding: 0,
          cursor: "pointer",
        }}
      />
      <div
        style={{
          position: "relative",
          zIndex: 1,
          width: "100%",
          maxWidth: 420,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-lg)",
          boxShadow: "var(--shadow-lg)",
          padding: "22px 22px 18px",
        }}
      >
        <h3
          id="confirm-dialog-title"
          className="serif"
          style={{
            margin: 0,
            fontSize: 18,
            fontWeight: 500,
            color: "var(--ink)",
            lineHeight: 1.3,
          }}
        >
          {title}
        </h3>
        {description && (
          <p
            style={{
              margin: "10px 0 0",
              fontSize: 14,
              lineHeight: 1.55,
              color: "var(--ink-2)",
              whiteSpace: "pre-line",
            }}
          >
            {description}
          </p>
        )}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 22,
          }}
        >
          {tone !== "alert" && (
            <button
              type="button"
              onClick={onCancel}
              disabled={busy}
              style={{
                appearance: "none",
                padding: "8px 14px",
                fontSize: 13,
                fontFamily: "var(--sans)",
                fontWeight: 500,
                color: "var(--ink-2)",
                background: "transparent",
                border: "1px solid var(--border-strong)",
                borderRadius: "var(--r)",
                cursor: busy ? "not-allowed" : "pointer",
                opacity: busy ? 0.5 : 1,
                transition: `background ${"var(--duration-fast)"} var(--ease-out)`,
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.background = "var(--surface-2)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.background = "transparent";
              }}
            >
              {cancelLabel}
            </button>
          )}
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            style={{
              appearance: "none",
              padding: "8px 16px",
              fontSize: 13,
              fontFamily: "var(--sans)",
              fontWeight: 500,
              color: "#faf6ed",
              background: confirmBg,
              border: 0,
              borderRadius: "var(--r)",
              cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.7 : 1,
              transition: `background ${"var(--duration-fast)"} var(--ease-out)`,
            }}
            onMouseOver={(e) => {
              if (!busy) e.currentTarget.style.background = confirmHover;
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.background = confirmBg;
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConfirmDialog;
