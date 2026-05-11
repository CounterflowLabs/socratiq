/**
 * Tiny `— • —` divider used between sections to add scholarly rhythm.
 * Replaces the heavier `<hr/>` we used in the legacy build.
 */
export function Ornament({
  width = 48,
  color,
  className,
}: {
  width?: number;
  color?: string;
  className?: string;
}) {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        color: color ?? "var(--ink-4)",
        margin: "8px 0",
      }}
    >
      <span style={{ width, height: 1, background: "currentColor", opacity: 0.4 }} />
      <span style={{ width: 4, height: 4, borderRadius: 50, background: "currentColor" }} />
      <span style={{ width, height: 1, background: "currentColor", opacity: 0.4 }} />
    </div>
  );
}
