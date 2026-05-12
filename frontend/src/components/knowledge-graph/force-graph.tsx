"use client";

import { useEffect, useRef } from "react";
import * as d3 from "d3";
import type { KnowledgeGraphNode, KnowledgeGraphEdge } from "@/lib/api";

interface ForceGraphProps {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  onNodeClick?: (node: KnowledgeGraphNode) => void;
}

function getMasteryColor(mastery: number): string {
  if (mastery >= 0.7) return "var(--success)";
  if (mastery >= 0.3) return "var(--warning)";
  return "var(--error)";
}

function masteryLabel(mastery: number): string {
  if (mastery >= 0.7) return "已掌握";
  if (mastery >= 0.3) return "学习中";
  return "未掌握";
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export default function ForceGraph({ nodes, edges, onNodeClick }: ForceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight || 400;

    // Container group for zoom/pan
    const g = svg.append("g");

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });

    svg.call(zoom);

    const simulation = d3.forceSimulation(nodes as d3.SimulationNodeDatum[])
      .force("link", d3.forceLink(edges as d3.SimulationLinkDatum<d3.SimulationNodeDatum>[]).id((d: d3.SimulationNodeDatum) => (d as KnowledgeGraphNode).id).distance(80))
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2));

    // Edges
    const link = g.append("g")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr("stroke", "var(--border-medium)")
      .attr("stroke-width", 1.5);

    // Nodes
    const showTooltip = (event: MouseEvent, d: KnowledgeGraphNode) => {
      const tooltip = tooltipRef.current;
      const container = containerRef.current;
      if (!tooltip || !container) return;
      const rect = container.getBoundingClientRect();
      tooltip.style.left = `${event.clientX - rect.left + 14}px`;
      tooltip.style.top = `${event.clientY - rect.top + 14}px`;
      tooltip.style.opacity = "1";
      tooltip.style.pointerEvents = "none";
      const masteryPct = Math.round(d.mastery * 100);
      tooltip.innerHTML = `
        <div style="font-weight:600;font-size:13px;color:var(--text-primary,#1f1a14);margin-bottom:4px;">
          ${escapeHtml(d.label)}
        </div>
        <div style="font-size:11px;color:var(--text-secondary,#6b6258);line-height:1.5;">
          ${d.category ? `<div>类别：${escapeHtml(d.category)}</div>` : ""}
          <div>掌握度：${masteryPct}% · ${masteryLabel(d.mastery)}</div>
          ${d.section_id ? `<div style="margin-top:2px;color:var(--accent,#a4582b);">点击跳转到所属章节</div>` : ""}
        </div>
      `;
    };

    const hideTooltip = () => {
      const tooltip = tooltipRef.current;
      if (tooltip) tooltip.style.opacity = "0";
    };

    const node = g.append("g")
      .selectAll<SVGCircleElement, KnowledgeGraphNode>("circle")
      .data(nodes)
      .join("circle")
      .attr("r", 12)
      .attr("fill", (d) => getMasteryColor(d.mastery))
      .attr("stroke", "var(--surface)")
      .attr("stroke-width", 2)
      .style("cursor", "pointer")
      .on("click", (_, d) => onNodeClick?.(d))
      .on("mouseover", function (event: MouseEvent, d) {
        d3.select(this).attr("stroke", "var(--accent, #a4582b)").attr("stroke-width", 3);
        showTooltip(event, d);
      })
      .on("mousemove", (event: MouseEvent, d) => showTooltip(event, d))
      .on("mouseout", function () {
        d3.select(this).attr("stroke", "var(--surface)").attr("stroke-width", 2);
        hideTooltip();
      });

    // Labels
    const label = g.append("g")
      .selectAll("text")
      .data(nodes)
      .join("text")
      .text((d) => d.label)
      .attr("font-size", 11)
      .attr("fill", "var(--text-secondary)")
      .attr("dx", 16)
      .attr("dy", 4);

    // Native SVG title remains as an a11y fallback for screen readers + users
    // without hover (touch devices won't fire mouseover).
    node.append("title")
      .text((d) => `${d.label} · 掌握度 ${Math.round(d.mastery * 100)}%`);

    // Drag
    node.call(d3.drag<SVGCircleElement, KnowledgeGraphNode>()
      .on("start", (event, d: d3.SimulationNodeDatum & KnowledgeGraphNode) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d: d3.SimulationNodeDatum & KnowledgeGraphNode) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d: d3.SimulationNodeDatum & KnowledgeGraphNode) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      })
    );

    simulation.on("tick", () => {
      link
        .attr("x1", (d: unknown) => (d as { source: { x: number } }).source.x)
        .attr("y1", (d: unknown) => (d as { source: { y: number } }).source.y)
        .attr("x2", (d: unknown) => (d as { target: { x: number } }).target.x)
        .attr("y2", (d: unknown) => (d as { target: { y: number } }).target.y);
      node
        .attr("cx", (d: unknown) => (d as { x: number }).x)
        .attr("cy", (d: unknown) => (d as { y: number }).y);
      label
        .attr("x", (d: unknown) => (d as { x: number }).x)
        .attr("y", (d: unknown) => (d as { y: number }).y);
    });

    return () => { simulation.stop(); };
  }, [nodes, edges, onNodeClick]);

  return (
    <div ref={containerRef} className="relative w-full" style={{ minHeight: 400 }}>
      <svg ref={svgRef} className="w-full h-full" style={{ minHeight: 400 }} />
      <div
        ref={tooltipRef}
        role="tooltip"
        style={{
          position: "absolute",
          pointerEvents: "none",
          opacity: 0,
          transition: "opacity 120ms ease",
          background: "var(--surface, #fffdf7)",
          border: "1px solid var(--border, rgba(20,16,10,0.12))",
          borderRadius: 8,
          padding: "8px 10px",
          boxShadow: "0 4px 16px rgba(20,16,10,0.12)",
          maxWidth: 220,
          zIndex: 20,
        }}
      />
      {/* Legend */}
      <div
        className="absolute bottom-3 left-3 flex items-center gap-3 rounded-lg border px-3 py-2 text-xs"
        style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text-secondary)" }}
      >
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: "var(--success)" }} />
          掌握 ≥70%
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: "var(--warning)" }} />
          ≥30%
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: "var(--error)" }} />
          &lt;30%
        </span>
      </div>
      <p className="absolute bottom-3 right-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
        滚轮缩放 · 拖拽平移
      </p>
    </div>
  );
}
