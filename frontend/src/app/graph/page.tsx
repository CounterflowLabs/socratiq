"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { IcFilter, IcLoader, IcRegen } from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Ornament } from "@/components/ui/ornament";
import { PageHeader } from "@/components/ui/page-header";
import {
  getKnowledgeGraph,
  listCourses,
  type CourseResponse,
  type KnowledgeGraphEdge,
  type KnowledgeGraphNode,
} from "@/lib/api";
import { useT, type TranslationKey } from "@/lib/i18n";

type MasteryStatus = "mastered" | "learning" | "seen";

function masteryFor(node: KnowledgeGraphNode): MasteryStatus {
  if (node.mastery >= 0.7) return "mastered";
  if (node.mastery >= 0.3) return "learning";
  return "seen";
}

function statusColor(status: MasteryStatus): string {
  return status === "mastered" ? "var(--ink)" : status === "learning" ? "var(--accent)" : "var(--ink-4)";
}
function statusFill(status: MasteryStatus): string {
  return status === "mastered" ? "var(--ink)" : status === "learning" ? "var(--accent)" : "transparent";
}

/** Lay out nodes around concentric rings. The backend doesn't return positions
 *  yet, so the front-end picks a deterministic, readable arrangement. */
function layoutNodes(nodes: KnowledgeGraphNode[]): Array<KnowledgeGraphNode & { x: number; y: number; size: number }> {
  if (nodes.length === 0) return [];
  const rings = [
    { count: 1, radius: 0 },
    { count: 6, radius: 28 },
    { count: 12, radius: 42 },
  ];
  return nodes.map((node, idx) => {
    let placed = idx;
    let ringIndex = 0;
    let positionInRing = 0;
    for (let i = 0; i < rings.length; i++) {
      if (placed < rings[i].count) {
        ringIndex = i;
        positionInRing = placed;
        break;
      }
      placed -= rings[i].count;
      ringIndex = i;
      positionInRing = placed;
    }
    const ring = rings[Math.min(ringIndex, rings.length - 1)];
    const angle = (positionInRing / Math.max(ring.count, 1)) * Math.PI * 2;
    const cx = 50 + Math.cos(angle) * ring.radius;
    const cy = 50 + Math.sin(angle) * ring.radius;
    const status = masteryFor(node);
    const baseSize = status === "mastered" ? 22 : status === "learning" ? 18 : 14;
    return { ...node, x: cx, y: cy, size: baseSize };
  });
}

export default function GraphPage() {
  const { t, lang } = useT();
  const router = useRouter();
  const [courses, setCourses] = useState<CourseResponse[]>([]);
  const [activeCourseId, setActiveCourseId] = useState<string | null>(null);
  const [nodes, setNodes] = useState<KnowledgeGraphNode[]>([]);
  const [edges, setEdges] = useState<KnowledgeGraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | MasteryStatus>("all");
  const [hovered, setHovered] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCourses()
      .then((res) => {
        if (cancelled) return;
        setCourses(res.items);
        if (res.items[0]) setActiveCourseId(res.items[0].id);
        else setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activeCourseId) return;
    let cancelled = false;
    // Defer the loading flag to a microtask so React doesn't see two
    // synchronous setStates back-to-back inside an effect body.
    queueMicrotask(() => {
      if (!cancelled) setLoading(true);
    });
    getKnowledgeGraph(activeCourseId, 2)
      .then((data) => {
        if (cancelled) return;
        setNodes(data.nodes);
        setEdges(data.edges);
      })
      .catch(() => {
        if (!cancelled) {
          setNodes([]);
          setEdges([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeCourseId]);

  const positioned = useMemo(() => layoutNodes(nodes), [nodes]);

  const counts = useMemo(() => {
    const initial = { total: nodes.length, mastered: 0, learning: 0, seen: 0 };
    for (const node of nodes) {
      const status = masteryFor(node);
      if (status === "mastered") initial.mastered += 1;
      else if (status === "learning") initial.learning += 1;
      else initial.seen += 1;
    }
    return initial;
  }, [nodes]);

  const visibleIds = useMemo(() => {
    if (filter === "all") return new Set(positioned.map((n) => n.id));
    return new Set(positioned.filter((n) => masteryFor(n) === filter).map((n) => n.id));
  }, [filter, positioned]);

  const hoveredNode = positioned.find((n) => n.id === hovered) ?? null;

  return (
    <div style={{ padding: "32px 40px 80px", maxWidth: 1280, margin: "0 auto", width: "100%" }}>
      <PageHeader
        eyebrow={t("nav.graph")}
        title={t("graph.title")}
        subtitle={t("graph.subtitle")}
        action={
          <>
            {courses.length > 1 ? (
              <select
                aria-label={lang === "zh" ? "课程" : "Course"}
                value={activeCourseId ?? ""}
                onChange={(e) => setActiveCourseId(e.target.value || null)}
                className="input"
                style={{ width: 220, height: 32, padding: "0 12px", fontSize: 12 }}
              >
                {courses.map((course) => (
                  <option key={course.id} value={course.id}>
                    {course.title}
                  </option>
                ))}
              </select>
            ) : null}
            <button type="button" className="btn btn-outline btn-sm">
              <IcFilter size={12} />
              <span>{t("common.filter")}</span>
            </button>
            <button type="button" className="btn btn-outline btn-sm btn-icon" aria-label={t("path.regenerate")}>
              <IcRegen size={12} />
            </button>
          </>
        }
      />

      {/* Stats strip — clicking a column filters the graph by that mastery state. */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          marginBottom: "var(--gap-lg)",
          borderTop: "1px solid var(--border)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {(
          [
            { key: "all" as const, label: t("graph.total"), value: counts.total, color: "var(--ink)" },
            { key: "mastered" as const, label: t("graph.mastered"), value: counts.mastered, color: "var(--ink)" },
            { key: "learning" as const, label: t("graph.learning"), value: counts.learning, color: "var(--accent)" },
            { key: "seen" as const, label: t("graph.seen"), value: counts.seen, color: "var(--ink-3)" },
          ]
        ).map((stat, i) => (
          <button
            key={stat.key}
            type="button"
            onClick={() => setFilter(stat.key)}
            style={{
              padding: "18px 20px",
              textAlign: "left",
              background: filter === stat.key ? "var(--surface-2)" : "transparent",
              borderRight: i < 3 ? "1px solid var(--border)" : "none",
              border: 0,
              cursor: "pointer",
              font: "inherit",
              color: "inherit",
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}
          >
            <Eyebrow>{stat.label}</Eyebrow>
            <div
              className="num"
              style={{
                fontFamily: "var(--serif)",
                fontSize: 32,
                fontWeight: 400,
                color: stat.color,
                lineHeight: 1,
              }}
            >
              {stat.value}
            </div>
          </button>
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 280px",
          gap: 24,
          alignItems: "flex-start",
        }}
      >
        <div
          className="hatched"
          style={{
            aspectRatio: "4 / 3",
            borderRadius: "var(--r-lg)",
            border: "1px solid var(--border)",
            position: "relative",
            overflow: "hidden",
          }}
        >
          {loading ? (
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--ink-3)",
                gap: 8,
                fontSize: 13,
              }}
            >
              <IcLoader size={16} className="spin" />
              <span>{t("common.loading")}</span>
            </div>
          ) : positioned.length === 0 ? (
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--ink-3)",
                fontSize: 13,
              }}
            >
              {lang === "zh" ? "没有可显示的概念" : "No concepts to show yet"}
            </div>
          ) : (
            <>
              <svg
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
              >
                {edges.map((edge, i) => {
                  const a = positioned.find((n) => n.id === edge.source);
                  const b = positioned.find((n) => n.id === edge.target);
                  if (!a || !b) return null;
                  const dim = !visibleIds.has(a.id) || !visibleIds.has(b.id);
                  return (
                    <line
                      key={`${edge.source}-${edge.target}-${i}`}
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      stroke="var(--ink-3)"
                      strokeWidth="0.15"
                      opacity={dim ? 0.1 : 0.4}
                    />
                  );
                })}
              </svg>
              {positioned.map((node) => {
                const status = masteryFor(node);
                const dim = !visibleIds.has(node.id);
                const isHover = hovered === node.id;
                return (
                  <div
                    key={node.id}
                    onMouseEnter={(e) => {
                      setHovered(node.id);
                      const wrap = e.currentTarget.parentElement as HTMLElement | null;
                      const wrapRect = wrap?.getBoundingClientRect();
                      if (wrapRect) {
                        setTooltipPos({
                          x: e.clientX - wrapRect.left,
                          y: e.clientY - wrapRect.top,
                        });
                      }
                    }}
                    onMouseMove={(e) => {
                      const wrap = e.currentTarget.parentElement as HTMLElement | null;
                      const wrapRect = wrap?.getBoundingClientRect();
                      if (wrapRect) {
                        setTooltipPos({
                          x: e.clientX - wrapRect.left,
                          y: e.clientY - wrapRect.top,
                        });
                      }
                    }}
                    onMouseLeave={() => {
                      setHovered((current) => (current === node.id ? null : current));
                      setTooltipPos(null);
                    }}
                    onClick={() => {
                      if (node.section_id && activeCourseId) {
                        router.push(`/learn?courseId=${activeCourseId}&sectionId=${node.section_id}`);
                      }
                    }}
                    style={{
                      position: "absolute",
                      left: `${node.x}%`,
                      top: `${node.y}%`,
                      transform: "translate(-50%, -50%)",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: 4,
                      cursor: node.section_id ? "pointer" : "default",
                      opacity: dim ? 0.2 : 1,
                      transition: "opacity 0.2s ease",
                      zIndex: isHover ? 10 : 1,
                    }}
                  >
                    <span
                      style={{
                        width: node.size,
                        height: node.size,
                        borderRadius: "50%",
                        background: statusFill(status),
                        border: `1.5px solid ${statusColor(status)}`,
                        boxShadow: isHover ? "0 0 0 4px var(--accent-soft)" : "none",
                        transition: "box-shadow 0.15s ease",
                      }}
                    />
                    <span
                      style={{
                        fontFamily: "var(--serif)",
                        fontSize: isHover ? 13 : 11,
                        fontWeight: isHover || status === "mastered" ? 500 : 400,
                        color: dim
                          ? "var(--ink-4)"
                          : status === "learning"
                            ? "var(--accent)"
                            : "var(--ink)",
                        background: "var(--bg)",
                        padding: "0 4px",
                        whiteSpace: "nowrap",
                        transition: "all 0.15s ease",
                      }}
                    >
                      {node.label}
                    </span>
                  </div>
                );
              })}
              {hoveredNode && tooltipPos ? (
                <div
                  role="tooltip"
                  style={{
                    position: "absolute",
                    left: tooltipPos.x + 14,
                    top: tooltipPos.y + 14,
                    pointerEvents: "none",
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "8px 10px",
                    boxShadow: "0 4px 16px rgba(20,16,10,0.18)",
                    maxWidth: 220,
                    fontSize: 12,
                    color: "var(--ink)",
                    zIndex: 20,
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 3, fontFamily: "var(--serif)" }}>
                    {hoveredNode.label}
                  </div>
                  <div style={{ color: "var(--ink-2)", lineHeight: 1.5 }}>
                    {hoveredNode.category ? (
                      <div>{lang === "zh" ? "类别：" : "Category: "}{hoveredNode.category}</div>
                    ) : null}
                    <div>
                      {lang === "zh" ? "掌握度：" : "Mastery: "}
                      {Math.round(hoveredNode.mastery * 100)}% · {t(`graph.${masteryFor(hoveredNode)}` as TranslationKey)}
                    </div>
                    {hoveredNode.section_id ? (
                      <div style={{ marginTop: 4, color: "var(--accent)" }}>
                        {lang === "zh" ? "点击跳转到所属课文" : "Click to open the lesson"}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
              <div
                style={{
                  position: "absolute",
                  bottom: 16,
                  left: 16,
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: 10,
                  display: "flex",
                  flexDirection: "column",
                  gap: 5,
                  fontSize: 11,
                }}
              >
                <Eyebrow>{t("graph.legend")}</Eyebrow>
                {(
                  [
                    { color: "var(--ink)", filled: true, label: t("graph.mastered") },
                    { color: "var(--accent)", filled: true, label: t("graph.learning") },
                    { color: "var(--ink-4)", filled: false, label: t("graph.seen") },
                  ]
                ).map((row, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: row.filled ? row.color : "transparent",
                        border: `1.5px solid ${row.color}`,
                      }}
                    />
                    <span style={{ color: "var(--ink-2)" }}>{row.label}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <aside style={{ position: "sticky", top: 24 }}>
          {hoveredNode ? (
            <div className="card">
              <Eyebrow>{t("graph.concept")}</Eyebrow>
              <h3
                className="serif"
                style={{ fontSize: 22, fontWeight: 500, margin: "6px 0 4px" }}
              >
                {hoveredNode.label}
              </h3>
              <span
                className="chip chip-mono"
                style={{
                  background: statusFill(masteryFor(hoveredNode)),
                  color: masteryFor(hoveredNode) === "seen" ? "var(--ink-3)" : "#fff",
                  border: "none",
                }}
              >
                {t(`graph.${masteryFor(hoveredNode)}` as TranslationKey)}
              </span>
              <Ornament width={32} />
              <div style={{ fontSize: 12, color: "var(--ink-2)", lineHeight: 1.6 }}>
                {hoveredNode.category
                  ? lang === "zh"
                    ? `属于「${hoveredNode.category}」分类。`
                    : `Category: ${hoveredNode.category}.`
                  : lang === "zh"
                    ? "暂无更多元数据。"
                    : "No additional metadata."}
                {hoveredNode.section_id ? (
                  <div style={{ marginTop: 8, color: "var(--accent)" }}>
                    {lang === "zh" ? "点击查看课文 →" : "Click to open the lesson →"}
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div
              className="card-quiet"
              style={{ color: "var(--ink-3)", fontSize: 12, padding: 18 }}
            >
              <Eyebrow>{lang === "zh" ? "提示" : "Hint"}</Eyebrow>
              <p style={{ margin: "8px 0 0", lineHeight: 1.5 }}>{t("graph.hint")}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
