import { clsx } from "clsx";

/**
 * Pill-style badge mapped onto the design-system chip tokens.
 * Color names are intentionally semantic: callers say "the warning chip",
 * not "the amber chip", so the palette can shift without code churn.
 */
const colorMap: Record<string, string> = {
  default: "chip",
  accent: "chip chip-accent",
  sage: "chip chip-sage",
  warn: "chip chip-warn",
  error: "chip chip-error",
  mono: "chip chip-mono",
  // Legacy aliases — were mapped to Tailwind palette colors before the redesign.
  blue: "chip chip-accent",
  green: "chip chip-sage",
  orange: "chip chip-warn",
  red: "chip chip-error",
  violet: "chip chip-accent",
  gray: "chip",
};

export function Badge({
  children,
  color = "default",
  className,
}: {
  children: React.ReactNode;
  color?: keyof typeof colorMap | string;
  className?: string;
}) {
  return (
    <span className={clsx(colorMap[color] ?? colorMap.default, className)}>
      {children}
    </span>
  );
}
