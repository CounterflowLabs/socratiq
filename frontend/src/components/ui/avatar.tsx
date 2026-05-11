/**
 * Initial-style avatar — serif glyph centered on a paper-toned chip.
 * Used in sidebar (`Y` for the local learner), settings (provider initials),
 * and any future user/agent affordance.
 */
export function Avatar({
  name,
  size = 28,
  accent = "ink",
}: {
  name?: string | null;
  size?: number;
  accent?: "ink" | "accent" | "sage";
}) {
  const bg =
    accent === "accent"
      ? "var(--accent-soft)"
      : accent === "sage"
        ? "var(--sage-soft)"
        : "var(--surface-2)";
  const fg =
    accent === "accent"
      ? "var(--accent-ink)"
      : accent === "sage"
        ? "var(--sage-ink)"
        : "var(--ink)";

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: bg,
        color: fg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--serif)",
        fontSize: size * 0.4,
        fontWeight: 500,
        flexShrink: 0,
        border: "1px solid var(--border)",
      }}
    >
      {name?.slice(0, 1).toUpperCase() || "·"}
    </div>
  );
}
