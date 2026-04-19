"use client";
import dynamic from "next/dynamic";
import CodeBlock from "./code-block";
import StepByStep from "./step-by-step";
import TimestampLink from "./timestamp-link";

const MermaidDiagram = dynamic(() => import("./mermaid-diagram"), { ssr: false });

interface LessonSection {
  heading: string;
  content: string;
  timestamp: number;
  code_snippets: { language: string; code: string; context: string }[];
  key_concepts: string[];
  diagrams: { type: string; title: string; content: string }[];
  interactive_steps: { title: string; steps: { label: string; detail: string; code?: string | null }[] } | null;
}

interface LessonContent {
  title: string;
  summary: string;
  sections: LessonSection[];
}

export default function LessonRenderer({
  lesson, onTimestampClick,
}: {
  lesson: LessonContent;
  onTimestampClick?: (seconds: number) => void;
}) {
  const canOpenTimestamp = typeof onTimestampClick === "function";

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-gray-900 mb-2">{lesson.title}</h1>
      {lesson.summary && <p className="text-sm text-gray-500 mb-6">{lesson.summary}</p>}

      {lesson.sections.map((section, i) => (
        <div key={i} className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-lg font-semibold text-gray-800">{section.heading}</h2>
            {section.timestamp > 0 && canOpenTimestamp && (
              <TimestampLink seconds={section.timestamp} onClick={() => onTimestampClick?.(section.timestamp)} />
            )}
          </div>

          <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{section.content}</div>

          {section.diagrams.map((d, j) => (
            d.type === "mermaid"
              ? <MermaidDiagram key={j} content={d.content} title={d.title} />
              : <pre key={j} className="my-3 p-3 bg-gray-50 rounded text-xs">{d.content}</pre>
          ))}

          {section.code_snippets.map((snippet, j) => (
            <CodeBlock key={j} language={snippet.language} code={snippet.code} context={snippet.context} />
          ))}

          {section.interactive_steps && (
            <StepByStep title={section.interactive_steps.title} steps={section.interactive_steps.steps} />
          )}

          {section.key_concepts.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {section.key_concepts.map((c) => (
                <span key={c} className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{c}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
