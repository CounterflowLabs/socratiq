import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React, { Suspense } from "react";

import { LayoutInner, SIDEBAR_DESKTOP_QUERY } from "@/app/layout-inner";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) =>
    React.createElement("div", { "data-testid": "markdown" }, children),
}));

vi.mock("next/font/google", () => ({
  Source_Serif_4: () => ({ variable: "--font-source-serif", style: { fontFamily: "Source Serif 4" } }),
  Geist: () => ({ variable: "--font-geist", style: { fontFamily: "Geist" } }),
  Geist_Mono: () => ({ variable: "--font-geist-mono", style: { fontFamily: "Geist Mono" } }),
  Noto_Serif_SC: () => ({ variable: "--font-noto-serif-sc", style: { fontFamily: "Noto Serif SC" } }),
  Noto_Sans_SC: () => ({ variable: "--font-noto-sans-sc", style: { fontFamily: "Noto Sans SC" } }),
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
  return <Suspense fallback={<div>Loading…</div>}>{children}</Suspense>;
}

describe("Learn page shell", () => {
  const courseResponse = {
    id: "c1",
    title: "测试课程",
    description: "desc",
    version_index: 1,
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

  it("renders the dedicated learn shell without the global nav", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as unknown as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "测试课程" })).toBeInTheDocument();
      expect(screen.getByText("课程目录")).toBeInTheDocument();
    });

    expect(screen.getByLabelText("返回首页")).toHaveAttribute("href", "/");
  });

  it("shows the persistent mentor and sources panels on desktop by default", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as unknown as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>,
    );

    await waitFor(() => {
      expect(screen.getByText("课程目录")).toBeInTheDocument();
      expect(screen.getByText("这是本节的正文内容。")).toBeInTheDocument();
    });

    // Mentor + sources rail visible by default — no iframe yet because the
    // active panel starts on "video", but the toggle buttons should be rendered.
    expect(screen.getByRole("button", { name: "原视频" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "原 PDF" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "参考资料" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI 导师" })).toBeInTheDocument();
  });

  it("surfaces lesson waypoints in the course outline", async () => {
    const courseWithWaypoints = {
      ...courseResponse,
      sections: [
        {
          ...courseResponse.sections[0],
          content: {
            lesson: {
              ...courseResponse.sections[0].content.lesson,
              sections: [
                {
                  heading: "从正文开始",
                  content: "这是本节的正文内容。",
                  timestamp: 12,
                  code_snippets: [],
                  key_concepts: ["变量", "类型"],
                  diagrams: [],
                  interactive_steps: null,
                },
                {
                  heading: "把概念跑起来",
                  content: "用一个例子确认理解。",
                  timestamp: 75,
                  code_snippets: [],
                  key_concepts: ["练习"],
                  diagrams: [],
                  interactive_steps: null,
                },
              ],
            },
          },
        },
      ],
    };

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseWithWaypoints,
    }) as unknown as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("本节脉络")).toBeInTheDocument();
    });

    const waypoints = within(screen.getByLabelText("本节脉络"));
    expect(waypoints.getByRole("button", { name: /从正文开始/ })).toBeInTheDocument();
    expect(waypoints.getByRole("button", { name: /把概念跑起来/ })).toBeInTheDocument();
  });

  it("opens the video aside when a lesson timestamp is clicked", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": courseResponse,
    }) as unknown as typeof fetch;

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;

    render(
      <LayoutInner>
        <SuspenseWrapper>
          <LearnPage />
        </SuspenseWrapper>
      </LayoutInner>,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /0:12/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /0:12/i }));

    await waitFor(() => {
      expect(screen.getByTitle("课程原视频")).toBeInTheDocument();
    });
  });
});
