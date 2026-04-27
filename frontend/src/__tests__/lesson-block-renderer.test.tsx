import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSectionLabMock = vi.fn();

vi.mock("@/components/lab/lab-editor", () => ({
  default: ({ lab }: { lab: { title: string } }) => <div data-testid="lab-editor">{lab.title}</div>,
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getSectionLab: getSectionLabMock,
  };
});

beforeEach(() => {
  getSectionLabMock.mockReset();
});

describe("LessonBlockRenderer", () => {
  it("renders intro, prose, concept relation, practice trigger, and recap blocks", async () => {
    const { default: LessonBlockRenderer } = await import("@/components/lesson/lesson-block-renderer");

    render(
      <LessonBlockRenderer
        lesson={{
          title: "Transformer Intro",
          summary: "课程概览",
          blocks: [
            { type: "intro_card", title: "你将学到什么", body: "Attention 的核心思想" },
            { type: "prose", title: "背景", body: "RNN 的瓶颈在于..." },
            {
              type: "concept_relation",
              title: "概念关系",
              concepts: [{ label: "attention" }, { label: "encoder" }],
            },
            {
              type: "practice_trigger",
              title: "动手试一试",
              body: "实现一个简化 attention scorer",
              metadata: { sectionId: "s1" },
            },
            { type: "recap", title: "本节小结", body: "Attention 解决了长依赖问题" },
          ],
          sections: [],
        }}
      />
    );

    expect(screen.getByText("你将学到什么")).toBeInTheDocument();
    expect(screen.getByText("动手试一试")).toBeInTheDocument();
  });

  it("renders backend-native code and diagram block fields instead of only body metadata fallbacks", async () => {
    const { default: LessonBlockRenderer } = await import("@/components/lesson/lesson-block-renderer");

    render(
      <LessonBlockRenderer
        lesson={{
          title: "Backend Shape",
          summary: "真实 payload",
          blocks: [
            {
              type: "code_example",
              title: "示例代码",
              body: "这段说明不应该替代真正代码",
              code: "print('hello from block.code')",
              language: "python",
            },
            {
              type: "diagram",
              title: "结构图",
              body: "这段 prose 不应该替代 diagram_content",
              diagram_type: "plain",
              diagram_content: "A --> B --> C",
            },
          ],
          sections: [],
        }}
      />
    );

    expect(screen.getByText("print('hello from block.code')")).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("A --> B --> C")).toBeInTheDocument();
    expect(screen.queryByText("这段 prose 不应该替代 diagram_content")).not.toBeInTheDocument();
  });

  it("adds an inline practice entry when runtime lab mode is inline even without a practice block", async () => {
    const { default: LessonBlockRenderer } = await import("@/components/lesson/lesson-block-renderer");

    render(
      <LessonBlockRenderer
        lesson={{
          title: "Runtime Fallback",
          summary: "只给后端真实 lesson blocks",
          blocks: [{ type: "prose", title: "正文", body: "先学习，再动手。" }],
          sections: [],
        }}
        sectionId="section-inline-1"
        labMode="inline"
      />
    );

    expect(screen.getByRole("button", { name: "开始练习" })).toBeInTheDocument();
  });

  it("retries inline practice loading after an error and eventually renders the lab editor", async () => {
    const { default: LessonBlockRenderer } = await import("@/components/lesson/lesson-block-renderer");

    getSectionLabMock
      .mockRejectedValueOnce(new Error("服务器暂时不可用"))
      .mockResolvedValueOnce({
        id: "lab-1",
        section_id: "section-inline-1",
        title: "Attention Lab",
        description: "练习 attention",
        language: "python",
        starter_code: { "main.py": "print('hi')" },
        test_code: {},
        run_instructions: "python main.py",
        confidence: 0.9,
      });

    render(
      <LessonBlockRenderer
        lesson={{
          title: "Runtime Fallback",
          summary: "只给后端真实 lesson blocks",
          blocks: [{ type: "prose", title: "正文", body: "先学习，再动手。" }],
          sections: [],
        }}
        sectionId="section-inline-1"
        labMode="inline"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "开始练习" }));

    await waitFor(() => {
      expect(screen.getByText("服务器暂时不可用")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => {
      expect(screen.getByTestId("lab-editor")).toHaveTextContent("Attention Lab");
    });
    expect(getSectionLabMock).toHaveBeenCalledTimes(2);
  });

  it("adds a concept relation fallback from graph card runtime data", async () => {
    const { default: LessonBlockRenderer } = await import("@/components/lesson/lesson-block-renderer");

    render(
      <LessonBlockRenderer
        lesson={{
          title: "Graph Runtime",
          summary: "图谱兜底",
          blocks: [{ type: "prose", title: "正文", body: "注意 prerequisite 关系。" }],
          sections: [],
        }}
        graphCard={{
          current: ["attention"],
          prerequisites: ["linear algebra"],
          unlocks: ["transformer"],
          section_anchor: 1,
        }}
      />
    );

    expect(screen.getByText("attention")).toBeInTheDocument();
    expect(screen.getByText("linear algebra")).toBeInTheDocument();
    expect(screen.getByText("transformer")).toBeInTheDocument();
  });

  it("merges interactive steps from sections even when backend blocks already exist", async () => {
    const { default: LessonBlockRenderer } = await import("@/components/lesson/lesson-block-renderer");

    render(
      <LessonBlockRenderer
        lesson={{
          title: "Existing Blocks",
          summary: "仍然需要 interactive steps fallback",
          blocks: [{ type: "prose", title: "正文", body: "先理解概念。" }],
          sections: [
            {
              heading: "步骤练习",
              content: "这里有操作步骤。",
              timestamp: 0,
              code_snippets: [],
              key_concepts: [],
              diagrams: [],
              interactive_steps: {
                title: "自己试着走一遍",
                steps: [
                  { label: "第一步", detail: "先打开输入张量。" },
                  { label: "第二步", detail: "再计算注意力分数。" },
                ],
              },
            },
          ],
        }}
      />
    );

    expect(screen.getByText("自己试着走一遍")).toBeInTheDocument();
    expect(screen.getByText(/1\. 第一步/)).toBeInTheDocument();
    expect(screen.getByText(/2\. 第二步/)).toBeInTheDocument();
  });

  it("does not duplicate interactive steps when an equivalent next step block already exists", async () => {
    const { default: LessonBlockRenderer } = await import("@/components/lesson/lesson-block-renderer");

    render(
      <LessonBlockRenderer
        lesson={{
          title: "No Duplicate Steps",
          summary: "去重检查",
          blocks: [
            {
              type: "next_step",
              title: "自己试着走一遍",
              body: "1. 第一步\n先打开输入张量。\n\n2. 第二步\n再计算注意力分数。",
            },
          ],
          sections: [
            {
              heading: "步骤练习",
              content: "这里有操作步骤。",
              timestamp: 0,
              code_snippets: [],
              key_concepts: [],
              diagrams: [],
              interactive_steps: {
                title: "自己试着走一遍",
                steps: [
                  { label: "第一步", detail: "先打开输入张量。" },
                  { label: "第二步", detail: "再计算注意力分数。" },
                ],
              },
            },
          ],
        }}
      />
    );

    expect(screen.getAllByText("自己试着走一遍")).toHaveLength(1);
  });
});
