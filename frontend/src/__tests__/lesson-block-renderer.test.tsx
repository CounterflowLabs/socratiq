import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
});
