import { describe, expect, it } from "vitest";

import { summarizeMermaidFlow } from "@/components/lesson/mermaid-flow";

describe("summarizeMermaidFlow", () => {
  it("extracts a readable learning path from a simple Mermaid flowchart", () => {
    const summary = summarizeMermaidFlow(`graph LR
  A[以往序列模型] --> B[分析结构与瓶颈]
  B --> C[Transformer 与 Self-Attention]
  C --> D[解释为何带来突破]`);

    expect(summary.direction).toBe("LR");
    expect(summary.nodes.map((node) => node.label)).toEqual([
      "以往序列模型",
      "分析结构与瓶颈",
      "Transformer 与 Self-Attention",
      "解释为何带来突破",
    ]);
    expect(summary.edges).toHaveLength(3);
    expect(summary.isLinear).toBe(true);
  });

  it("marks branching diagrams as non-linear", () => {
    const summary = summarizeMermaidFlow(`flowchart TD
  D{固定长度输入}
  D --> E[平均]
  D --> F[拼接]`);

    expect(summary.nodes.map((node) => node.label)).toContain("固定长度输入");
    expect(summary.branchCount).toBe(1);
    expect(summary.isLinear).toBe(false);
  });
});
