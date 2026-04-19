"use client";

import dynamic from "next/dynamic";

import { type LessonBlock, type LessonContent } from "@/lib/api";

import CodeBlock from "./code-block";
import TimestampLink from "./timestamp-link";
import { ConceptRelationCard } from "./blocks/concept-relation-card";
import { PracticeTriggerCard } from "./blocks/practice-trigger-card";

const MermaidDiagram = dynamic(() => import("./mermaid-diagram"), { ssr: false });

function readStringMetadata(block: LessonBlock, key: string): string | null {
  const value = block.metadata?.[key];
  return typeof value === "string" ? value : null;
}

function readNumberMetadata(block: LessonBlock, key: string): number | null {
  const value = block.metadata?.[key];
  return typeof value === "number" ? value : null;
}

function interactiveStepsToBody(
  interactiveSteps: NonNullable<LessonContent["sections"][number]["interactive_steps"]>
) {
  return interactiveSteps.steps
    .map((step, index) =>
      [`${index + 1}. ${step.label}`, step.detail, step.code ? step.code : null]
        .filter(Boolean)
        .join("\n")
    )
    .join("\n\n");
}

export function blocksFromLegacy(lesson: LessonContent): LessonBlock[] {
  if (lesson.blocks?.length) return lesson.blocks;

  const blocks: LessonBlock[] = [];

  if (lesson.title || lesson.summary) {
    blocks.push({ type: "intro_card", title: lesson.title, body: lesson.summary });
  }

  lesson.sections.forEach((section) => {
    blocks.push({
      type: "prose",
      title: section.heading,
      body: section.content,
      metadata: section.timestamp > 0 ? { timestamp: section.timestamp } : undefined,
    });

    section.diagrams.forEach((diagram) => {
      blocks.push({
        type: "diagram",
        title: diagram.title || section.heading,
        body: diagram.content,
        metadata: { diagramType: diagram.type },
      });
    });

    section.code_snippets.forEach((snippet) => {
      blocks.push({
        type: "code_example",
        title: snippet.context || section.heading,
        body: snippet.code,
        metadata: { language: snippet.language },
      });
    });

    if (section.interactive_steps) {
      blocks.push({
        type: "next_step",
        title: section.interactive_steps.title,
        body: interactiveStepsToBody(section.interactive_steps),
      });
    }

    if (section.key_concepts.length > 0) {
      blocks.push({
        type: "concept_relation",
        title: section.heading,
        concepts: section.key_concepts.map((label) => ({ label })),
      });
    }
  });

  if (lesson.summary) {
    blocks.push({ type: "recap", title: "本节小结", body: lesson.summary });
  }

  return blocks;
}

function TextBlock({
  title,
  body,
  tone = "default",
  timestamp,
  onTimestampClick,
}: {
  title?: string | null;
  body?: string | null;
  tone?: "default" | "intro" | "recap";
  timestamp?: number | null;
  onTimestampClick?: (seconds: number) => void;
}) {
  const cardClassName =
    tone === "intro"
      ? "border-sky-200 bg-sky-50/70"
      : tone === "recap"
        ? "border-emerald-200 bg-emerald-50/70"
        : "border-slate-200 bg-white";

  return (
    <section className={`rounded-2xl border px-5 py-4 shadow-sm ${cardClassName}`}>
      {title || timestamp ? (
        <div className="flex flex-wrap items-center gap-2">
          {title ? <h3 className="text-base font-semibold text-slate-900">{title}</h3> : null}
          {timestamp && onTimestampClick ? (
            <TimestampLink seconds={timestamp} onClick={() => onTimestampClick(timestamp)} />
          ) : null}
        </div>
      ) : null}
      {body ? (
        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-600">{body}</p>
      ) : null}
    </section>
  );
}

export default function LessonBlockRenderer({
  lesson,
  onTimestampClick,
}: {
  lesson: LessonContent;
  onTimestampClick?: (seconds: number) => void;
}) {
  const blocks = blocksFromLegacy(lesson);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
      {blocks.map((block, index) => {
        const blockKey = `${block.type}-${block.title ?? "untitled"}-${index}`;

        switch (block.type) {
          case "intro_card":
            return <TextBlock key={blockKey} title={block.title} body={block.body} tone="intro" />;
          case "prose":
            return (
              <TextBlock
                key={blockKey}
                title={block.title}
                body={block.body}
                timestamp={readNumberMetadata(block, "timestamp")}
                onTimestampClick={onTimestampClick}
              />
            );
          case "diagram": {
            const diagramType = readStringMetadata(block, "diagramType");
            if (!block.body) return null;
            return diagramType === "mermaid" ? (
              <MermaidDiagram key={blockKey} content={block.body} title={block.title ?? undefined} />
            ) : (
              <section key={blockKey} className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4">
                {block.title ? <h3 className="text-base font-semibold text-slate-900">{block.title}</h3> : null}
                <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-900 p-4 text-xs text-slate-100">
                  {block.body}
                </pre>
              </section>
            );
          }
          case "code_example":
            return block.body ? (
              <section key={blockKey} className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
                <CodeBlock
                  language={readStringMetadata(block, "language") ?? "plaintext"}
                  code={block.body}
                  context={block.title ?? undefined}
                />
              </section>
            ) : null;
          case "concept_relation":
            return <ConceptRelationCard key={blockKey} title={block.title} concepts={block.concepts} />;
          case "practice_trigger": {
            const sectionId = readStringMetadata(block, "sectionId");
            return sectionId ? (
              <PracticeTriggerCard
                key={blockKey}
                title={block.title ?? "动手练习"}
                body={block.body ?? "打开练习，边学边做。"}
                sectionId={sectionId}
                enabled
              />
            ) : null;
          }
          case "recap":
            return <TextBlock key={blockKey} title={block.title} body={block.body} tone="recap" />;
          case "next_step":
            return <TextBlock key={blockKey} title={block.title} body={block.body} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
