"use client";
import { useState } from "react";

interface ReviewCardProps {
  conceptName: string;
  question: string | null;
  answer: string | null;
  onRate: (quality: number) => void;
  disabled?: boolean;
}

export default function ReviewCard({ conceptName, question, answer, onRate, disabled }: ReviewCardProps) {
  const [flipped, setFlipped] = useState(false);

  return (
    <div
      className="w-[280px] h-[200px] shrink-0 cursor-pointer"
      style={{ perspective: "1000px" }}
      onClick={() => !flipped && setFlipped(true)}
    >
      <div
        className="relative w-full h-full transition-transform duration-500"
        style={{
          transformStyle: "preserve-3d",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0)",
        }}
      >
        {/* Front */}
        <div className="absolute inset-0 card flex flex-col items-center justify-center text-center p-6" style={{ backfaceVisibility: "hidden" }}>
          <p className="text-xs text-[var(--text-tertiary)] mb-2">点击翻转</p>
          <p className="font-semibold text-lg mb-2">{conceptName}</p>
          <p className="text-sm text-[var(--text-secondary)]">{question ?? conceptName}</p>
        </div>
        {/* Back */}
        <div
          className="absolute inset-0 card flex flex-col items-center justify-between p-6 overflow-hidden"
          style={{ backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}
        >
          <div className="flex-1 overflow-y-auto flex items-center w-full">
            <p className="text-sm text-[var(--text)] text-center w-full">{answer ?? "暂无解析"}</p>
          </div>
          <div className="flex gap-2 mt-3">
            {[
              { label: "忘了", quality: 1, color: "var(--error)" },
              { label: "模糊", quality: 3, color: "var(--warning)" },
              { label: "记得", quality: 4, color: "var(--success)" },
              { label: "简单", quality: 5, color: "var(--primary)" },
            ].map((btn) => (
              <button
                key={btn.quality}
                onClick={(e) => { e.stopPropagation(); onRate(btn.quality); }}
                disabled={disabled}
                className="px-3 py-1.5 rounded-full text-xs font-medium text-white transition-opacity"
                style={{ background: btn.color, opacity: disabled ? 0.5 : 1 }}
              >
                {btn.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
