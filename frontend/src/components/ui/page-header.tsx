import type { ReactNode } from "react";

import { Eyebrow } from "./eyebrow";

interface PageHeaderProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
}

export function PageHeader({ eyebrow, title, subtitle, action }: PageHeaderProps) {
  return (
    <header
      style={{
        marginBottom: "var(--gap-xl)",
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        gap: 24,
        flexWrap: "wrap",
      }}
    >
      <div style={{ minWidth: 0 }}>
        {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
        <h1
          className="display"
          style={{ fontSize: 40, margin: "6px 0 8px", fontWeight: 400 }}
        >
          {title}
        </h1>
        {subtitle ? (
          <p style={{ fontSize: 15, color: "var(--ink-2)", margin: 0, maxWidth: 560 }}>
            {subtitle}
          </p>
        ) : null}
      </div>
      {action ? <div style={{ display: "flex", gap: 8 }}>{action}</div> : null}
    </header>
  );
}
