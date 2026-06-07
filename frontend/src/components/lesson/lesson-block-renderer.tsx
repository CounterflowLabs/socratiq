"use client";

import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";

import { type GraphCard, type LabMode, type LessonBlock, type LessonConcept, type LessonContent, type LessonReference } from "@/lib/api";

import CodeBlock from "./code-block";
import TimestampLink from "./timestamp-link";
import { ConceptRelationCard } from "./blocks/concept-relation-card";
import { ExerciseTriggerCard } from "./blocks/exercise-trigger-card";
import { PracticeTriggerCard } from "./blocks/practice-trigger-card";

const MermaidDiagram = dynamic(() => import("./mermaid-diagram"), { ssr: false });

const GRAPH_BUCKET_LABELS = {
  prerequisites: "先修概念",
  current: "当前聚焦",
  unlocks: "继续深入",
} as const;

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

function buildLegacyBaseBlocks(lesson: LessonContent): LessonBlock[] {
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
        diagram_type: diagram.type,
        diagram_content: diagram.content,
      });
    });

    section.code_snippets.forEach((snippet) => {
      blocks.push({
        type: "code_example",
        title: section.heading,
        body: snippet.context || section.content,
        code: snippet.code,
        language: snippet.language,
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

function hasEquivalentNextStepBlock(
  blocks: LessonBlock[],
  candidate: LessonBlock
) {
  return blocks.some((block) => {
    if (block.type !== "next_step") return false;
    return block.title === candidate.title && block.body === candidate.body;
  });
}

function mergeSectionInteractiveStepFallbacks(
  blocks: LessonBlock[],
  lesson: LessonContent
): LessonBlock[] {
  const mergedBlocks = [...blocks];

  lesson.sections.forEach((section) => {
    if (!section.interactive_steps) return;

    const candidate: LessonBlock = {
      type: "next_step",
      title: section.interactive_steps.title,
      body: interactiveStepsToBody(section.interactive_steps),
    };

    if (hasEquivalentNextStepBlock(mergedBlocks, candidate)) {
      return;
    }

    const recapIndex = mergedBlocks.findIndex((block) => block.type === "recap");
    const insertIndex = recapIndex >= 0 ? recapIndex : mergedBlocks.length;
    mergedBlocks.splice(insertIndex, 0, candidate);
  });

  return mergedBlocks;
}

export function blocksFromLegacy(lesson: LessonContent): LessonBlock[] {
  const baseBlocks = lesson.blocks?.length ? [...lesson.blocks] : buildLegacyBaseBlocks(lesson);
  return mergeSectionInteractiveStepFallbacks(baseBlocks, lesson);
}

function readBlockSectionId(block: LessonBlock): string | null {
  const direct = block.metadata?.sectionId;
  if (typeof direct === "string") return direct;

  const snakeCase = block.metadata?.section_id;
  return typeof snakeCase === "string" ? snakeCase : null;
}

function graphCardToConcepts(graphCard: GraphCard | null | undefined): LessonConcept[] {
  if (!graphCard) return [];

  const seen = new Set<string>();
  const concepts: LessonConcept[] = [];

  (["prerequisites", "current", "unlocks"] as const).forEach((bucket) => {
    graphCard[bucket].forEach((label) => {
      if (!label || seen.has(label)) return;
      seen.add(label);
      concepts.push({
        label,
        description: GRAPH_BUCKET_LABELS[bucket],
      });
    });
  });

  return concepts;
}

function withRuntimeFallbacks(
  baseBlocks: LessonBlock[],
  runtime: {
    sectionId?: string | null;
    courseId?: string | null;
    labMode?: LabMode | null;
    graphCard?: GraphCard | null;
  }
): LessonBlock[] {
  const blocks = [...baseBlocks];
  const recapIndex = blocks.findIndex((block) => block.type === "recap");
  const insertIndex = recapIndex >= 0 ? recapIndex : blocks.length;

  const hasPracticeTrigger = blocks.some((block) => block.type === "practice_trigger");
  if (!hasPracticeTrigger && runtime.labMode === "inline" && runtime.sectionId) {
    blocks.splice(insertIndex, 0, {
      type: "practice_trigger",
      title: "动手试一试",
      body: "打开本节 Lab，把刚学到的内容马上跑起来。",
      metadata: { sectionId: runtime.sectionId },
    });
  }

  const hasExerciseTrigger = blocks.some((block) => block.type === "exercise_trigger");
  if (!hasExerciseTrigger && runtime.sectionId) {
    blocks.splice(insertIndex, 0, {
      type: "exercise_trigger",
      title: "检验掌握程度",
      body: "做几道练习，巩固本节要点。",
      metadata: {
        sectionId: runtime.sectionId,
        ...(runtime.courseId ? { courseId: runtime.courseId } : {}),
      },
    });
  }

  const hasConceptRelation = blocks.some(
    (block) => block.type === "concept_relation" && (block.concepts?.length ?? 0) > 0
  );
  const graphConcepts = graphCardToConcepts(runtime.graphCard);
  if (!hasConceptRelation && graphConcepts.length > 0) {
    blocks.splice(insertIndex, 0, {
      type: "concept_relation",
      title: "知识关系",
      concepts: graphConcepts,
      metadata: runtime.sectionId ? { sectionId: runtime.sectionId } : undefined,
    });
  }

  return blocks;
}

/** Body prose, rendered as a continuous flowing document via the shared
 *  `.prose` typographic system (serif, 17px/1.65). No card, no border. The
 *  model emits markdown (bold, lists, inline code), so we render it through
 *  react-markdown (same renderer the mentor chat uses) into the elements
 *  `.prose` already styles, instead of leaking literal `**` / `-` markers. */
function ProseBody({ body, size, muted }: { body: string; size?: number; muted?: boolean }) {
  return (
    <div
      className="prose"
      style={{
        ...(size ? { fontSize: size } : {}),
        ...(muted ? { color: "var(--ink-2)" } : {}),
      }}
    >
      <ReactMarkdown>{body}</ReactMarkdown>
    </div>
  );
}

/** Ordinary explanatory prose — the bulk of a lesson. De-boxed: a quiet serif
 *  sub-heading (when present) over flowing body text. */
function ProseBlock({
  title,
  body,
  timestamp,
  onTimestampClick,
  waypointId,
}: {
  title?: string | null;
  body?: string | null;
  timestamp?: number | null;
  onTimestampClick?: (seconds: number) => void;
  waypointId?: string;
}) {
  const showHead = Boolean(title || (timestamp && onTimestampClick));
  return (
    <section data-lesson-waypoint={waypointId}>
      {showHead ? (
        <div className="flex flex-wrap items-baseline gap-2" style={{ marginBottom: 8 }}>
          {title ? (
            <h3
              className="serif"
              style={{
                fontSize: 19,
                fontWeight: 600,
                lineHeight: 1.3,
                letterSpacing: "-0.01em",
                color: "var(--ink)",
                margin: 0,
              }}
            >
              {title}
            </h3>
          ) : null}
          {timestamp && onTimestampClick ? (
            <TimestampLink seconds={timestamp} onClick={() => onTimestampClick(timestamp)} />
          ) : null}
        </div>
      ) : null}
      {body ? <ProseBody body={body} /> : null}
    </section>
  );
}

/** The opening hook. Not a box: a terracotta lead-rule with slightly larger
 *  serif lead text, so the lesson opens with a beat instead of a blue card. */
function IntroLead({ title, body }: { title?: string | null; body?: string | null }) {
  const text = body || title;
  if (!text) return null;
  return (
    <section style={{ borderLeft: "2px solid var(--accent)", paddingLeft: 18 }}>
      <ProseBody body={text} size={19} />
    </section>
  );
}

/** End-of-lesson synthesis. Earns a quiet warm inset (not a hard emerald box):
 *  a tan surface, soft radius, a small eyebrow label, muted body. */
function RecapBlock({ title, body }: { title?: string | null; body?: string | null }) {
  return (
    <section
      style={{
        background: "var(--surface-2)",
        borderRadius: "var(--r-lg)",
        padding: "16px 20px",
      }}
    >
      <div className="eyebrow" style={{ color: "var(--ink-3)", marginBottom: 8 }}>
        {title || "小结"}
      </div>
      {body ? <ProseBody body={body} size={16} muted /> : null}
    </section>
  );
}

/** Forward pointer. De-boxed: a hairline rule + accent eyebrow + a single
 *  muted line, reading as a closing beat rather than another card. */
function NextStepBlock({ title, body }: { title?: string | null; body?: string | null }) {
  if (!title && !body) return null;
  return (
    <section style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
      <div className="eyebrow" style={{ color: "var(--accent)", marginBottom: 6 }}>
        {title || "下一步"}
      </div>
      {body ? (
        <p
          className="serif"
          style={{ fontSize: 16, lineHeight: 1.6, color: "var(--ink-2)", margin: 0 }}
        >
          {body}
        </p>
      ) : null}
    </section>
  );
}

/** Further reading: real, citable references (classic + frontier). A hairline
 *  section, each entry tagged 经典/前沿; the title links out only when the
 *  reference carries a verified url (fetched), otherwise it's name-only. */
function FurtherReadingBlock({
  title,
  references,
}: {
  title?: string | null;
  references?: LessonReference[];
}) {
  const refs = (references ?? []).filter((r) => r && r.title);
  if (refs.length === 0) return null;
  return (
    <section style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
      <div className="eyebrow" style={{ color: "var(--ink-3)", marginBottom: 12 }}>
        {title || "延伸阅读"}
      </div>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {refs.map((r, i) => {
          const frontier = r.kind === "frontier";
          const meta = [r.source, r.year].filter(Boolean).join(" · ");
          return (
            <li key={i} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
              <span
                className="chip"
                style={{
                  flexShrink: 0,
                  fontSize: 11,
                  background: frontier ? "var(--accent-soft)" : "var(--sage-soft)",
                  color: frontier ? "var(--accent-ink)" : "var(--sage-ink)",
                }}
              >
                {frontier ? "前沿" : "经典"}
              </span>
              <div style={{ minWidth: 0 }}>
                {r.url ? (
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "var(--accent)", fontWeight: 500 }}
                  >
                    {r.title}
                  </a>
                ) : (
                  <span style={{ color: "var(--ink)", fontWeight: 500 }}>{r.title}</span>
                )}
                {meta ? (
                  <span style={{ color: "var(--ink-3)", fontSize: 13 }}> · {meta}</span>
                ) : null}
                {r.note ? (
                  <div style={{ color: "var(--ink-2)", fontSize: 14, lineHeight: 1.5, marginTop: 2 }}>
                    {r.note}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default function LessonBlockRenderer({
  lesson,
  onTimestampClick,
  sectionId,
  courseId,
  labMode,
  graphCard,
}: {
  lesson: LessonContent;
  onTimestampClick?: (seconds: number) => void;
  sectionId?: string | null;
  courseId?: string | null;
  labMode?: LabMode | null;
  graphCard?: GraphCard | null;
}) {
  const blocks = withRuntimeFallbacks(blocksFromLegacy(lesson), {
    sectionId,
    courseId,
    labMode,
    graphCard,
  });
  const waypointIdsByHeading = new Map(
    lesson.sections.map((item, index) => [item.heading, `lesson-waypoint-${index}`])
  );
  const anchoredWaypoints = new Set<string>();

  function takeWaypointId(block: LessonBlock): string | undefined {
    if (block.type !== "prose" || !block.title) return undefined;

    const waypointId = waypointIdsByHeading.get(block.title);
    if (!waypointId || anchoredWaypoints.has(waypointId)) return undefined;
    anchoredWaypoints.add(waypointId);
    return waypointId;
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-7 px-5 py-8">
      {blocks.map((block, index) => {
        const blockKey = `${block.type}-${block.title ?? "untitled"}-${index}`;

        switch (block.type) {
          case "intro_card":
            return <IntroLead key={blockKey} title={block.title} body={block.body} />;
          case "prose":
            return (
              <ProseBlock
                key={blockKey}
                title={block.title}
                body={block.body}
                timestamp={readNumberMetadata(block, "timestamp")}
                onTimestampClick={onTimestampClick}
                waypointId={takeWaypointId(block)}
              />
            );
          case "diagram": {
            const diagramType = block.diagram_type ?? readStringMetadata(block, "diagramType");
            const diagramContent = block.diagram_content ?? block.body;
            if (!diagramContent) return null;
            return diagramType === "mermaid" ? (
              <MermaidDiagram key={blockKey} content={diagramContent} title={block.title ?? ""} />
            ) : (
              <figure
                key={blockKey}
                style={{
                  margin: 0,
                  border: "1px solid var(--border)",
                  borderRadius: "var(--r-lg)",
                  background: "var(--surface)",
                  padding: 16,
                }}
              >
                {block.title ? (
                  <figcaption className="eyebrow" style={{ color: "var(--ink-3)", marginBottom: 10 }}>
                    {block.title}
                  </figcaption>
                ) : null}
                <pre
                  style={{
                    margin: 0,
                    overflowX: "auto",
                    background: "var(--surface-2)",
                    borderRadius: "var(--r)",
                    padding: 14,
                    fontFamily: "var(--mono)",
                    fontSize: 12,
                    lineHeight: 1.6,
                    color: "var(--ink)",
                  }}
                >
                  {diagramContent}
                </pre>
              </figure>
            );
          }
          case "code_example": {
            const code = block.code ?? block.body;
            if (!code) return null;
            // CodeBlock already self-styles (token-aware dark pre + context +
            // copy affordance), so no outer card — that was the redundant box.
            return (
              <CodeBlock
                key={blockKey}
                language={block.language ?? readStringMetadata(block, "language") ?? "plaintext"}
                code={code}
                context={block.body && block.body !== code ? block.body : block.title ?? undefined}
              />
            );
          }
          case "concept_relation":
            return <ConceptRelationCard key={blockKey} title={block.title} concepts={block.concepts} />;
          case "practice_trigger": {
            const blockSectionId = readBlockSectionId(block) ?? sectionId ?? null;
            return blockSectionId ? (
              <PracticeTriggerCard
                key={blockKey}
                title={block.title ?? "动手练习"}
                body={block.body ?? "打开练习，边学边做。"}
                sectionId={blockSectionId}
                enabled
              />
            ) : null;
          }
          case "exercise_trigger": {
            const blockSectionId = readBlockSectionId(block) ?? sectionId ?? null;
            const blockCourseId = readStringMetadata(block, "courseId") ?? courseId ?? null;
            return blockSectionId ? (
              <ExerciseTriggerCard
                key={blockKey}
                title={block.title ?? "检验掌握程度"}
                body={block.body ?? "做几道练习巩固本节要点。"}
                sectionId={blockSectionId}
                courseId={blockCourseId}
                enabled
              />
            ) : null;
          }
          case "recap":
            return <RecapBlock key={blockKey} title={block.title} body={block.body} />;
          case "further_reading":
            return (
              <FurtherReadingBlock
                key={blockKey}
                title={block.title}
                references={block.references}
              />
            );
          case "next_step":
            return <NextStepBlock key={blockKey} title={block.title} body={block.body} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
