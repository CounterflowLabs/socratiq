import type { CSSProperties, ReactNode } from "react";

export function Eyebrow({
  children,
  color,
  className,
  style,
}: {
  children: ReactNode;
  color?: string;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      className={`eyebrow ${className ?? ""}`.trim()}
      style={{ color: color ?? "var(--ink-3)", ...style }}
    >
      {children}
    </div>
  );
}
