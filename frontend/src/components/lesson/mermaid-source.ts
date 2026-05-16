const GRAPH_DECLARATION = /^(?:graph|flowchart)\s+[A-Za-z]{2}\b/;

function stripMermaidFence(content: string): string {
  const trimmed = content.trim();
  const fenced = trimmed.match(/^```(?:mermaid)?\s*\r?\n([\s\S]*?)\r?\n```$/i);
  if (fenced) return fenced[1].trim();

  const lines = trimmed.split(/\r?\n/);
  if (lines[0]?.trim().toLowerCase() === "mermaid") {
    return lines.slice(1).join("\n").trim();
  }

  return trimmed;
}

function escapeQuotedLabel(label: string): string {
  return label.trim().replace(/"/g, "#quot;");
}

function quoteSquareLabels(line: string): string {
  return line.replace(
    /(^|[\s>|.-])([A-Za-z0-9_:-]+)\[([^\]\n]+)\]/g,
    (match, prefix: string, id: string, label: string) => {
      const trimmed = label.trim();
      if (trimmed.startsWith('"') && trimmed.endsWith('"')) return match;
      return `${prefix}${id}["${escapeQuotedLabel(trimmed)}"]`;
    }
  );
}

function quoteDecisionLabels(line: string): string {
  return line.replace(
    /(^|[\s>|.-])([A-Za-z0-9_:-]+)\{([^{}\n]+)\}/g,
    (match, prefix: string, id: string, label: string) => {
      const trimmed = label.trim();
      if (trimmed.startsWith('"') && trimmed.endsWith('"')) return match;
      return `${prefix}${id}{"${escapeQuotedLabel(trimmed)}"}`;
    }
  );
}

function normalizePrimeNodeIds(line: string): string {
  return line
    .replace(
      /^(\s*(?:style|class)\s+)([A-Za-z][A-Za-z0-9_:-]*)'+(\s+)/,
      (_match, prefix: string, id: string, suffix: string) => `${prefix}${id}_prime${suffix}`
    )
    .replace(
      /\b([A-Za-z][A-Za-z0-9_:-]*)'+(?=\s*(?:\[|\{|\(|-->|---|==>|-.->|$|;))/g,
      (_match, id: string) => `${id}_prime`
    );
}

function isFlowchart(content: string): boolean {
  return content
    .split(/\r?\n/)
    .some((line) => GRAPH_DECLARATION.test(line.trim()));
}

export function normalizeMermaidSource(content: string): string {
  const stripped = stripMermaidFence(content);
  if (!isFlowchart(stripped)) return stripped;

  return stripped
    .split(/\r?\n/)
    .map((line) => quoteDecisionLabels(quoteSquareLabels(normalizePrimeNodeIds(line))))
    .join("\n");
}

export function isMermaidErrorSvg(svg: string): boolean {
  const normalized = svg.toLowerCase();
  return (
    normalized.includes("syntax error in text") ||
    normalized.includes("class=\"error-icon\"") ||
    normalized.includes("id=\"error-icon\"") ||
    normalized.includes("mermaid version")
  );
}
