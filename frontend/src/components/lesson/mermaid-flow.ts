export interface MermaidFlowNode {
  id: string;
  label: string;
}

export interface MermaidFlowEdge {
  from: string;
  to: string;
  label?: string;
}

export interface MermaidFlowSummary {
  direction: string | null;
  nodes: MermaidFlowNode[];
  edges: MermaidFlowEdge[];
  branchCount: number;
  isLinear: boolean;
}

const GRAPH_DECLARATION = /^(?:graph|flowchart)\s+([A-Za-z]{2})/;
const EDGE_OPERATOR = /\s*(?:-->|---|==>|-.->|--\s*[^-]+?\s*-->)\s*/;
const NODE_TOKEN = /^([A-Za-z0-9_:-]+)(?:\[(.+?)\]|\{(.+?)\}|\((.+?)\))?/;

function cleanLabel(value: string): string {
  return value.replace(/^["']|["']$/g, "").trim();
}

function parseNodeToken(token: string): MermaidFlowNode | null {
  const normalized = token.trim().replace(/;+$/, "");
  const match = normalized.match(NODE_TOKEN);
  if (!match) return null;

  const id = match[1];
  const label = cleanLabel(match[2] ?? match[3] ?? match[4] ?? id);
  return { id, label };
}

function addNode(nodes: Map<string, MermaidFlowNode>, node: MermaidFlowNode | null) {
  if (!node) return;

  const existing = nodes.get(node.id);
  if (!existing || existing.label === existing.id) {
    nodes.set(node.id, node);
  }
}

function parseEdgeLine(line: string): {
  from: MermaidFlowNode;
  to: MermaidFlowNode;
  label?: string;
} | null {
  const parts = line.split(EDGE_OPERATOR);
  if (parts.length < 2) return null;

  const from = parseNodeToken(parts[0]);
  const to = parseNodeToken(parts[1]);
  if (!from || !to) return null;

  const labelMatch = line.match(/--\s*([^->]+?)\s*-->/);
  const label = labelMatch?.[1] ? cleanLabel(labelMatch[1]) : undefined;
  return { from, to, label };
}

export function summarizeMermaidFlow(content: string): MermaidFlowSummary {
  const nodes = new Map<string, MermaidFlowNode>();
  const edges: MermaidFlowEdge[] = [];
  let direction: string | null = null;

  content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("%%"))
    .forEach((line) => {
      const declaration = line.match(GRAPH_DECLARATION);
      if (declaration) {
        direction = declaration[1].toUpperCase();
        return;
      }

      const edge = parseEdgeLine(line);
      if (edge) {
        addNode(nodes, edge.from);
        addNode(nodes, edge.to);
        edges.push({ from: edge.from.id, to: edge.to.id, label: edge.label });
        return;
      }

      addNode(nodes, parseNodeToken(line));
    });

  const outgoingCount = new Map<string, number>();
  edges.forEach((edge) => {
    outgoingCount.set(edge.from, (outgoingCount.get(edge.from) ?? 0) + 1);
  });

  const branchCount = [...outgoingCount.values()].filter((count) => count > 1).length;
  const nodeList = [...nodes.values()];

  return {
    direction,
    nodes: nodeList,
    edges,
    branchCount,
    isLinear: branchCount === 0 && edges.length === Math.max(0, nodeList.length - 1),
  };
}
