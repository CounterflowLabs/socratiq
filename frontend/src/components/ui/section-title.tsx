import type { ReactNode } from "react";

interface SectionTitleProps {
  children: ReactNode;
  action?: ReactNode;
  count?: number;
}

export function SectionTitle({ children, action, count }: SectionTitleProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        marginBottom: "var(--gap-md)",
        gap: 12,
      }}
    >
      <h2
        style={{
          fontSize: 13,
          fontWeight: 600,
          margin: 0,
          letterSpacing: "0.02em",
          color: "var(--ink)",
          display: "flex",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        {children}
        {count != null ? (
          <span
            className="mono num"
            style={{ color: "var(--ink-3)", fontWeight: 400, fontSize: 12 }}
          >
            {String(count).padStart(2, "0")}
          </span>
        ) : null}
      </h2>
      {action}
    </div>
  );
}
