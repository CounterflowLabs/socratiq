"use client";

import { useEffect, useState, type ComponentType } from "react";

import type { IconProps } from "@/components/icons";

/**
 * Segmented control — three or four mutually-exclusive options sitting in a
 * `surface-2` track with a sliding `surface` pill for the active item.
 * Used by Settings (theme, language, density) and the live Tweaks panel.
 *
 * Hydration: the `value` prop usually comes from a Zustand store that reads
 * localStorage on the client, so SSR sees the default (`"system"`) while the
 * client may see `"dark"`. Until the component has mounted, we render every
 * option with the same neutral state and `suppressHydrationWarning` on the
 * mismatched attributes. After mount we render the real active option.
 */

interface SegmentedOption<T extends string> {
  v: T;
  label: string;
  icon?: ComponentType<IconProps>;
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T;
  options: ReadonlyArray<SegmentedOption<T>>;
  onChange: (next: T) => void;
  ariaLabel?: string;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      style={{
        display: "inline-flex",
        background: "var(--surface-2)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        padding: 2,
        gap: 2,
      }}
    >
      {options.map((option) => {
        const Icon = option.icon;
        const active = mounted && option.v === value;
        return (
          <button
            key={option.v}
            type="button"
            role="radio"
            aria-checked={active}
            suppressHydrationWarning
            onClick={() => onChange(option.v)}
            style={{
              height: 26,
              padding: "0 10px",
              borderRadius: 6,
              border: "none",
              background: active ? "var(--surface)" : "transparent",
              boxShadow: active ? "var(--shadow-sm)" : "none",
              color: active ? "var(--ink)" : "var(--ink-2)",
              fontSize: 12,
              fontWeight: active ? 500 : 400,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 5,
              fontFamily: "inherit",
              whiteSpace: "nowrap",
            }}
          >
            {Icon ? <Icon size={12} /> : null}
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
