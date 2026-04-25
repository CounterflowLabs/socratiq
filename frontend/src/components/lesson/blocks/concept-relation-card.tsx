import type { LessonConcept } from "@/lib/api";

interface ConceptRelationCardProps {
  title?: string | null;
  concepts?: LessonConcept[];
}

export function ConceptRelationCard({ title, concepts = [] }: ConceptRelationCardProps) {
  if (concepts.length === 0) return null;

  return (
    <section className="rounded-lg border border-slate-200 bg-slate-50 px-5 py-4">
      {title ? <h3 className="text-base font-semibold text-slate-900">{title}</h3> : null}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {concepts.map((concept, index) => (
          <div key={`${concept.label}-${index}`} className="flex items-center gap-3">
            <div className="rounded-md border border-sky-200 bg-white px-3 py-1.5 text-sm font-medium text-sky-700 shadow-sm">
              {concept.label}
            </div>
            {index < concepts.length - 1 ? (
              <span className="text-xs font-medium uppercase text-slate-300">
                connects
              </span>
            ) : null}
          </div>
        ))}
      </div>
      {concepts.some((concept) => concept.description) ? (
        <div className="mt-4 space-y-2">
          {concepts.map((concept) =>
            concept.description ? (
              <p key={`${concept.label}-description`} className="text-sm leading-6 text-slate-600">
                <span className="font-medium text-slate-800">{concept.label}:</span> {concept.description}
              </p>
            ) : null
          )}
        </div>
      ) : null}
    </section>
  );
}
