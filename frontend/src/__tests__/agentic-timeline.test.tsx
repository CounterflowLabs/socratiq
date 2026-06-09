import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgenticTimeline from "@/components/materials/agentic-timeline";
import type { AgenticProgress } from "@/lib/use-run-progress";

/** Minimal agentic projection carrying only narrated tool-call activities —
 *  the shape the ingestion pipeline produces (no graph steps / critic). */
function withActivities(
  activities: AgenticProgress["activities"],
): AgenticProgress {
  return {
    steps: [],
    activities,
    critic: null,
    backtracks: [],
    replans: 0,
    active: true,
  };
}

describe("AgenticTimeline — narrated tool-call activity feed", () => {
  it("renders each activity with a localized label, its tag, and result summary", () => {
    const agentic = withActivities([
      { id: "a1", name: "extract.bilibili", detail: null, result: "51 段内容", state: "done", order: 0 },
      { id: "a2", name: "analyze.content", detail: null, result: "8 个概念 · 6 段", state: "done", order: 1 },
      { id: "a3", name: "embed.vectors", detail: null, result: null, state: "running", order: 2 },
    ]);

    render(<AgenticTimeline agentic={agentic} running lang="zh" />);

    // Localized labels (tag → 中文).
    expect(screen.getByText("抓取 B站字幕")).toBeInTheDocument();
    expect(screen.getByText("分析内容结构")).toBeInTheDocument();
    expect(screen.getByText("向量化")).toBeInTheDocument();
    // The technical tag is shown verbatim alongside (Claude-Desktop style).
    expect(screen.getByText("extract.bilibili")).toBeInTheDocument();
    // Dynamic result summary from TOOL_CALL_RESULT.
    expect(screen.getByText("51 段内容")).toBeInTheDocument();
    expect(screen.getByText("8 个概念 · 6 段")).toBeInTheDocument();
  });

  it("falls back to a verb-prefixed label for unknown tags", () => {
    const agentic = withActivities([
      { id: "x", name: "references.search", detail: "attention, transformer", result: "8 候选 → 保留 5", state: "done", order: 0 },
    ]);
    render(<AgenticTimeline agentic={agentic} lang="zh" />);
    expect(screen.getByText("检索参考文献")).toBeInTheDocument();
    expect(screen.getByText("8 候选 → 保留 5")).toBeInTheDocument();
  });

  it("shows the args detail when no result has arrived yet (still running)", () => {
    const agentic = withActivities([
      { id: "x", name: "extract.youtube", detail: "https://youtu.be/abc", result: null, state: "running", order: 0 },
    ]);
    render(<AgenticTimeline agentic={agentic} running lang="zh" />);
    expect(screen.getByText("抓取 YouTube 字幕")).toBeInTheDocument();
    expect(screen.getByText("https://youtu.be/abc")).toBeInTheDocument();
  });

  it("renders nothing when the projection is inactive", () => {
    const { container } = render(
      <AgenticTimeline
        agentic={{ steps: [], activities: [], critic: null, backtracks: [], replans: 0, active: false }}
        lang="zh"
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
