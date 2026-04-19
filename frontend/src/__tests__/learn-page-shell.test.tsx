import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React, { Suspense } from "react";

import { LayoutInner, SIDEBAR_DESKTOP_QUERY } from "@/app/layout";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) =>
    React.createElement("div", { "data-testid": "markdown" }, children),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => {
    const params = new URLSearchParams();
    params.set("courseId", "c1");
    params.set("sectionId", "s1");
    return params;
  },
  usePathname: () => "/learn",
}));

function installMatchMedia(width: number) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === SIDEBAR_DESKTOP_QUERY ? width >= 1280 : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as typeof window.matchMedia;
}

function mockFetch(responses: Record<string, unknown>) {
  return vi.fn((url: string) => {
    const sortedKeys = Object.keys(responses).sort((a, b) => b.length - a.length);
    const matchedUrl = sortedKeys.find((key) => url.endsWith(key) || url.includes(`${key}?`));

    if (matchedUrl) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(responses[matchedUrl]),
        text: () => Promise.resolve(JSON.stringify(responses[matchedUrl])),
      });
    }

    return Promise.resolve({
      ok: false,
      status: 404,
      text: () => Promise.resolve("Not found"),
    });
  });
}

function SuspenseWrapper({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<div>Loading...</div>}>{children}</Suspense>;
}

describe("Learn page shell", () => {
  const courseResponse = {
    id: "c1",
    title: "测试课程",
    description: "desc",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    sources: [
      {
        id: "video-1",
        type: "youtube",
        url: "https://www.youtube.com/watch?v=demo-video",
      },
      {
        id: "pdf-1",
        type: "pdf",
        url: "https://example.com/lesson.pdf",
      },
      {
        id: "ref-1",
        type: "article",
        url: "https://example.com/reference",
      },
    ],
    sections: [
      {
        id: "s1",
        title: "第一章",
        order_index: 0,
        difficulty: 2,
        source_id: "video-1",
        content: {
          lesson: {
            title: "课程正文",
            summary: "课程摘要",
            sections: [
              {
                heading: "从正文开始",
                content: "这是本节的正文内容。",
                timestamp: 12,
                code_snippets: [],
                key_concepts: [],
                diagrams: [],
                interactive_steps: null,
              },
            ],
          },
        },
        source_start: null,
        source_end: null,
      },
    ],
  };

  beforeEach(() => {
    installMatchMedia(1440);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("renders the dedicated learn shell without the global nav or legacy tabs", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "测试课程" })).toBeInTheDocument();
      expect(screen.getByText("课程目录")).toBeInTheDocument();
    });

    expect(screen.queryByText("资料")).not.toBeInTheDocument();
    expect(screen.queryByText("Lab")).not.toBeInTheDocument();
  });

  it("keeps source video and pdf in the study aside instead of the main stage", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    const { container } = render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByText("课程目录")).toBeInTheDocument();
      expect(screen.getByText("这是本节的正文内容。")).toBeInTheDocument();
    });

    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.queryByText("原视频")).not.toBeInTheDocument();
    expect(screen.queryByText("原 PDF")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /打开学习辅助区/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "原 PDF" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "参考资料" })).toBeInTheDocument();
    });
  });

  it("lets desktop users close and reopen the study aside", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /打开学习辅助区/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /打开学习辅助区/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /关闭学习辅助区/i })).toBeInTheDocument();
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /关闭学习辅助区/i }));

    await waitFor(() => {
      expect(screen.queryByTitle("课程原视频")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /打开学习辅助区/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
    });
  });

  it("opens the video aside when a lesson timestamp is clicked", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /0:12/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /0:12/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /打开学习辅助区/i })).toHaveAttribute(
        "aria-expanded",
        "true"
      );
    });
  });

  it("keeps course-level video support when the current section comes from a pdf source", async () => {
    const mixedSourceCourse = {
      ...courseResponse,
      sources: [
        {
          id: "pdf-1",
          type: "pdf",
          url: null,
        },
        {
          id: "ref-1",
          type: "article",
          url: null,
        },
        {
          id: "video-1",
          type: "youtube",
          url: "https://www.youtube.com/watch?v=demo-video",
        },
      ],
      sections: [
        {
          ...courseResponse.sections[0],
          source_id: "pdf-1",
        },
      ],
    };

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": mixedSourceCourse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /0:12/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /0:12/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "原 PDF" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "参考资料" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "原 PDF" }));

    await waitFor(() => {
      expect(screen.getByRole("link", { name: /打开原 PDF/i })).toHaveAttribute(
        "href",
        "/api/v1/sources/pdf-1/file"
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "参考资料" }));

    await waitFor(() => {
      expect(screen.queryByRole("link", { name: /参考链接/i })).not.toBeInTheDocument();
    });
  });

  it("uses a deterministic course-material fallback when multiple videos and pdfs are available", async () => {
    const courseWithMultipleMaterials = {
      ...courseResponse,
      sources: [
        {
          id: "video-b",
          type: "youtube",
          url: "https://www.youtube.com/watch?v=late-video",
        },
        {
          id: "pdf-b",
          type: "pdf",
          url: "https://example.com/later.pdf",
        },
        {
          id: "article-1",
          type: "article",
          url: "https://example.com/article",
        },
        {
          id: "video-a",
          type: "youtube",
          url: "https://www.youtube.com/watch?v=primary-video",
        },
        {
          id: "pdf-a",
          type: "pdf",
          url: "https://example.com/primary.pdf",
        },
      ],
      sections: [
        {
          ...courseResponse.sections[0],
          id: "s-pdf",
          title: "主 PDF",
          order_index: 0,
          source_id: "pdf-a",
        },
        {
          ...courseResponse.sections[0],
          id: "s-article",
          title: "当前文章节",
          order_index: 1,
          source_id: "article-1",
        },
        {
          ...courseResponse.sections[0],
          id: "s-video-a",
          title: "主视频节",
          order_index: 2,
          source_id: "video-a",
        },
        {
          ...courseResponse.sections[0],
          id: "s-video-b",
          title: "备选视频节",
          order_index: 3,
          source_id: "video-b",
        },
      ],
    };

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseWithMultipleMaterials,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByText("当前文章节")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /打开学习辅助区/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toHaveAttribute(
        "src",
        expect.stringContaining("primary-video")
      );
      expect(screen.getByRole("button", { name: "原 PDF" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "原 PDF" }));

    await waitFor(() => {
      expect(screen.getByRole("link", { name: /打开原 PDF/i })).toHaveAttribute(
        "href",
        "https://example.com/primary.pdf"
      );
    });
  });

  it("preserves bilibili page selection when the current section itself is the video source", async () => {
    const bilibiliCourse = {
      ...courseResponse,
      sources: [
        {
          id: "pdf-1",
          type: "pdf",
          url: "https://example.com/notes.pdf",
        },
        {
          id: "video-1",
          type: "bilibili",
          url: "https://www.bilibili.com/video/BV1test1234",
        },
      ],
      sections: [
        {
          ...courseResponse.sections[0],
          id: "s0",
          title: "前置 PDF 节",
          order_index: 0,
          source_id: "pdf-1",
        },
        {
          ...courseResponse.sections[0],
          id: "s2",
          title: "视频第一节",
          order_index: 3,
          source_id: "video-1",
          content: {
            ...courseResponse.sections[0].content,
            page_index: 0,
          },
        },
        {
          ...courseResponse.sections[0],
          id: "s1",
          title: "视频第二节",
          order_index: 4,
          source_id: "video-1",
          content: {
            ...courseResponse.sections[0].content,
            page_index: 1,
          },
        },
      ],
    };

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": bilibiliCourse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /0:12/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /0:12/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toHaveAttribute(
        "src",
        expect.stringContaining("p=2")
      );
    });
  });

  it("keeps bilibili single-part videos on p=1 even when one source is split into multiple sections", async () => {
    const singlePartBilibiliCourse = {
      ...courseResponse,
      sources: [
        {
          id: "video-1",
          type: "bilibili",
          url: "https://www.bilibili.com/video/BV1single123",
        },
      ],
      sections: [
        {
          ...courseResponse.sections[0],
          id: "s1",
          title: "视频切片一",
          order_index: 0,
          source_id: "video-1",
        },
        {
          ...courseResponse.sections[0],
          id: "s2",
          title: "视频切片二",
          order_index: 1,
          source_id: "video-1",
        },
      ],
    };

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": singlePartBilibiliCourse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /0:12/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /0:12/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toHaveAttribute(
        "src",
        expect.stringContaining("p=1")
      );
    });
  });

  it("does not render a clickable timestamp when no video source is available", async () => {
    const courseWithoutVideo = {
      ...courseResponse,
      sources: courseResponse.sources.filter((source) => source.id !== "video-1"),
      sections: [
        {
          ...courseResponse.sections[0],
          source_id: "pdf-1",
        },
      ],
    };

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseWithoutVideo,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByText("这是本节的正文内容。")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /0:12/i })).not.toBeInTheDocument();
  });

  it("keeps a manually selected non-video aside panel stable", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /打开学习辅助区/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /打开学习辅助区/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "原 PDF" }));

    await waitFor(() => {
      expect(screen.getByRole("link", { name: /打开原 PDF/i })).toBeInTheDocument();
    });

    expect(screen.queryByTitle("课程原视频")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "AI 导师" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /打开 AI 导师/i })).toBeInTheDocument();
    });

    expect(screen.queryByTitle("课程原视频")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /打开原 PDF/i })).not.toBeInTheDocument();
  });

  it("shows the study aside as a visible overlay on narrow screens", async () => {
    installMatchMedia(768);

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /0:12/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /0:12/i }));

    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /学习辅助区/i })).toBeInTheDocument();
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
    });
  });
});
