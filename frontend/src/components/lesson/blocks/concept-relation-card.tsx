import type { LessonConcept } from "@/lib/api";

interface ConceptRelationCardProps {
  title?: string | null;
  concepts?: LessonConcept[];
}

// Group concepts by their description (which corresponds to relationship type)
function groupConcepts(concepts: LessonConcept[]) {
  const groups = new Map<string, LessonConcept[]>();
  const ungrouped: LessonConcept[] = [];

  concepts.forEach((c) => {
    if (c.description) {
      const key = c.description;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(c);
    } else {
      ungrouped.push(c);
    }
  });

  return { groups, ungrouped };
}

export function ConceptRelationCard({ title, concepts = [] }: ConceptRelationCardProps) {
  if (concepts.length === 0) return null;

  const { groups, ungrouped } = groupConcepts(concepts);
  const hasGroups = groups.size > 0;

  return (
    <section
      className="rounded-lg border px-5 py-4"
      style={{ borderColor: "var(--border)", background: "var(--surface-alt)" }}
    >
      {title ? (
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text)" }}>
          {title}
        </h3>
      ) : null}

      {hasGroups ? (
        <div className="space-y-3">
          {[...groups.entries()].map(([groupName, items]) => (
            <div key={groupName} className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
              <span
                className="text-[11px] font-semibold uppercase tracking-wide shrink-0"
                style={{ color: "var(--text-tertiary)" }}
              >
                {groupName}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {items.map((c, i) => (
                  <span
                    key={`${c.label}-${i}`}
                    className="rounded-md border px-2.5 py-1 text-xs font-medium"
                    style={{
                      borderColor: "var(--border)",
                      background: "var(--surface)",
                      color: "var(--text)",
                    }}
                  >
                    {c.label}
                  </span>
                ))}
              </div>
            </div>
          ))}
          {ungrouped.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-2 border-t" style={{ borderColor: "var(--border)" }}>
              {ungrouped.map((c, i) => (
                <span
                  key={`${c.label}-ung-${i}`}
                  className="rounded-md border px-2.5 py-1 text-xs font-medium"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                    color: "var(--text)",
                  }}
                >
                  {c.label}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {concepts.map((c, i) => (
            <span
              key={`${c.label}-${i}`}
              className="rounded-md border px-2.5 py-1 text-xs font-medium"
              style={{
                borderColor: "var(--border)",
                background: "var(--surface)",
                color: "var(--text)",
              }}
            >
              {c.label}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
