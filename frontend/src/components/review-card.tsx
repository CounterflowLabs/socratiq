"use client";

import { useState } from "react";

import { Eyebrow } from "@/components/ui/eyebrow";
import { useT } from "@/lib/i18n";

interface ReviewCardProps {
  conceptName: string;
  question: string | null;
  answer: string | null;
  onRate: (quality: number) => void;
  disabled?: boolean;
  course?: string;
}

/**
 * Review card — tap-to-reveal pattern from the prototype, replacing the
 * legacy 3D flip. SM-2 ratings map to four buttons coded by SM-2 quality:
 * 忘了 / 困难 / 良好 / 轻松 (or en equivalents) with semantic colors.
 */
export default function ReviewCard({
  conceptName,
  question,
  answer,
  onRate,
  disabled,
  course,
}: ReviewCardProps) {
  const { t, lang } = useT();
  const [revealed, setRevealed] = useState(false);

  const buttons = [
    { key: "forgot", quality: 1, label: t("common.forgot"), color: "var(--error)" },
    { key: "hard", quality: 3, label: t("common.hard"), color: "var(--warn)" },
    { key: "good", quality: 4, label: t("common.good"), color: "var(--ink-2)" },
    { key: "easy", quality: 5, label: t("common.easy"), color: "var(--sage)" },
  ];

  return (
    <div
      className="card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: 18,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <Eyebrow>{course ?? (lang === "zh" ? "复习" : "Review")}</Eyebrow>
        <span className="chip chip-mono chip-warn">{t("common.due")}</span>
      </div>
      <div
        style={{
          fontFamily: "var(--serif)",
          fontSize: 17,
          lineHeight: 1.4,
          fontWeight: 500,
          color: "var(--ink)",
        }}
      >
        {conceptName}
      </div>
      <div
        style={{
          fontSize: 13,
          color: "var(--ink-2)",
          lineHeight: 1.5,
          minHeight: 60,
        }}
      >
        {revealed ? (
          (answer ?? question ?? (lang === "zh" ? "暂无解析" : "No answer recorded yet."))
        ) : (
          <button
            type="button"
            onClick={() => setRevealed(true)}
            style={{
              background: "transparent",
              border: "1px dashed var(--border-strong)",
              color: "var(--ink-3)",
              padding: "8px 12px",
              borderRadius: 6,
              fontSize: 12,
              cursor: "pointer",
              width: "100%",
              fontFamily: "inherit",
            }}
          >
            {question ?? t("common.tapToReveal")}
          </button>
        )}
      </div>
      {revealed ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4 }}>
          {buttons.map((btn) => (
            <button
              key={btn.key}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRate(btn.quality);
              }}
              disabled={disabled}
              className="btn btn-outline btn-sm"
              style={{
                justifyContent: "center",
                color: btn.color,
                fontWeight: 500,
              }}
            >
              {btn.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
