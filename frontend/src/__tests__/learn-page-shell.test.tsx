import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
      "/api/v1/courses/c1": {
        id: "c1",
        title: "测试课程",
        description: "desc",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        sources: [],
        sections: [
          {
            id: "s1",
            title: "第一章",
            order_index: 0,
            difficulty: 2,
            content: {},
            source_start: null,
            source_end: null,
          },
        ],
      },
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
});
