import { clsx } from "clsx";

export function ProgressBar({
  value,
  max = 100,
  color = "var(--accent)",
  height = 3,
  className,
}: {
  value: number;
  max?: number;
  color?: string;
  height?: number;
  className?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div
      className={clsx("rounded-full overflow-hidden", className)}
      style={{ height, background: "var(--surface-2)" }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: color,
          transition: "width 0.4s ease",
        }}
      />
    </div>
  );
}

/** Compact alias for the inline progress bar used by lessons / dashboard. */
export function Progress({
  value,
  color = "var(--ink)",
  height = 3,
  className,
}: {
  value: number;
  color?: string;
  height?: number;
  className?: string;
}) {
  return (
    <div
      className={className}
      style={{
        width: "100%",
        height,
        background: "var(--surface-2)",
        borderRadius: 9999,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${Math.min(100, Math.max(0, value))}%`,
          height: "100%",
          background: color,
          transition: "width 0.4s ease",
        }}
      />
    </div>
  );
}
