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
  if (mastery >= 0.7) return "#22c55e"; // green
  if (mastery >= 0.3) return "#eab308"; // yellow
  return "#ef4444"; // red
}

export default function ForceGraph({ nodes, edges, onNodeClick }: ForceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight || 400;

    const simulation = d3.forceSimulation(nodes as d3.SimulationNodeDatum[])
      .force("link", d3.forceLink(edges as d3.SimulationLinkDatum<d3.SimulationNodeDatum>[]).id((d: d3.SimulationNodeDatum) => (d as KnowledgeGraphNode).id).distance(80))
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2));

    // Edges
    const link = svg.append("g")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr("stroke", "#d1d5db")
      .attr("stroke-width", 1.5);

    // Nodes
    const node = svg.append("g")
      .selectAll<SVGCircleElement, KnowledgeGraphNode>("circle")
      .data(nodes)
      .join("circle")
      .attr("r", 12)
      .attr("fill", (d) => getMasteryColor(d.mastery))
      .attr("stroke", "#fff")
      .attr("stroke-width", 2)
      .style("cursor", "pointer")
      .on("click", (_, d) => onNodeClick?.(d));

    // Labels
    const label = svg.append("g")
      .selectAll("text")
      .data(nodes)
      .join("text")
      .text((d) => d.label)
      .attr("font-size", 11)
      .attr("fill", "#374151")
      .attr("dx", 16)
      .attr("dy", 4);

    // Tooltip
    node.append("title")
      .text((d) => `${d.label}\n掌握度: ${Math.round(d.mastery * 100)}%`);

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

  return <svg ref={svgRef} className="w-full h-full min-h-[400px]" />;
}
