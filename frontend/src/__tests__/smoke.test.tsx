import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import React, { Suspense } from "react";

// Mock react-markdown (ESM-only package that doesn't work in jsdom)
vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) =>
    React.createElement("div", { "data-testid": "markdown" }, children),
}));

// Helper: mock fetch with exact-end-of-path matching to avoid ambiguity
function mockFetch(responses: Record<string, unknown>) {
  return vi.fn((url: string) => {
    // Sort keys by length descending so more specific paths match first
    const sortedKeys = Object.keys(responses).sort(
      (a, b) => b.length - a.length
    );
    const matchedUrl = sortedKeys.find((key) => url.endsWith(key) || url.includes(key + "?"));
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

// Wrapper for components using useSearchParams (needs Suspense)
function SuspenseWrapper({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<div>Loading...</div>}>{children}</Suspense>;
}

// Reset Zustand stores between tests
import { useCoursesStore, useChatStore } from "@/lib/stores";

function resetStores() {
  useCoursesStore.getState().setCourses([]);
  useCoursesStore.getState().setLoading(false);
  useChatStore.getState().clearChat();
}

beforeEach(() => {
  resetStores();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── Dashboard Tests ────────────────────────────────

describe("Dashboard", () => {
  it("shows empty state when no courses", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses": { items: [], total: 0, skip: 0, limit: 20 },
      "/api/v1/reviews/stats": { due_today: 0, completed_today: 0 },
    });

    const DashboardPage = (await import("@/app/page")).default;
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("还没有课程")).toBeInTheDocument();
    });
  });

  it("shows course cards when courses exist", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses": {
        items: [
          {
            id: "c1",
            title: "深度学习基础",
            description: "测试课程",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
      "/api/v1/reviews/stats": { due_today: 3, completed_today: 1 },
    });

    const DashboardPage = (await import("@/app/page")).default;
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("深度学习基础")).toBeInTheDocument();
    });
  });
});

// ─── Import Tests ────────────────────────────────────

describe("Import Page", () => {
  it("renders both source type tabs", async () => {
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    // Use getByRole to avoid matching the description paragraph
    const buttons = screen.getAllByRole("button");
    const biliButton = buttons.find((b) => b.textContent?.includes("B站视频"));
    const pdfButton = buttons.find((b) => b.textContent?.includes("PDF 文档"));
    expect(biliButton).toBeTruthy();
    expect(pdfButton).toBeTruthy();
  });

  it("shows URL input on Bilibili tab", async () => {
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    await waitFor(() => {
      const input = screen.getByPlaceholderText(
        "https://www.bilibili.com/video/BV..."
      );
      expect(input).toBeInTheDocument();
    });
  });

  it("shows upload area on PDF tab", async () => {
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    // Click the PDF tab
    const buttons = screen.getAllByRole("button");
    const pdfTab = buttons.find((b) => b.textContent?.includes("PDF 文档"));
    fireEvent.click(pdfTab!);

    await waitFor(() => {
      expect(
        screen.getByText("拖拽 PDF 到这里，或点击选择文件")
      ).toBeInTheDocument();
    });
  });
});

// ─── Settings Tests ──────────────────────────────────

describe("Settings Page", () => {
  it("shows loading state initially", async () => {
    // Fetch that never resolves
    globalThis.fetch = vi.fn(() => new Promise(() => {}));

    const SettingsPage = (await import("@/app/settings/page")).default;
    render(<SettingsPage />);

    expect(screen.getByText("加载中...")).toBeInTheDocument();
  });

  it("renders model list", async () => {
    const modelsData = [
      {
        name: "claude-sonnet",
        provider_type: "anthropic",
        model_id: "claude-sonnet-4",
        supports_tool_use: true,
        supports_streaming: true,
        max_tokens_limit: 4096,
        is_active: true,
      },
    ];
    const routesData = [
      { task_type: "mentor_chat", model_name: "claude-sonnet" },
    ];

    globalThis.fetch = vi.fn((url: string) => {
      if (url.endsWith("/api/v1/model-routes")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(routesData),
          text: () => Promise.resolve(JSON.stringify(routesData)),
        });
      }
      if (url.endsWith("/api/v1/models")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(modelsData),
          text: () => Promise.resolve(JSON.stringify(modelsData)),
        });
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        text: () => Promise.resolve("Not found"),
      });
    });

    const SettingsPage = (await import("@/app/settings/page")).default;
    render(<SettingsPage />);

    await waitFor(() => {
      // "claude-sonnet" appears in both route and model sections
      expect(screen.getAllByText("claude-sonnet").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("anthropic")).toBeInTheDocument();
    });
  });

  it("shows empty state when no models", async () => {
    globalThis.fetch = vi.fn((url: string) => {
      if (url.endsWith("/api/v1/model-routes")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
          text: () => Promise.resolve("[]"),
        });
      }
      if (url.endsWith("/api/v1/models")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
          text: () => Promise.resolve("[]"),
        });
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        text: () => Promise.resolve("Not found"),
      });
    });

    const SettingsPage = (await import("@/app/settings/page")).default;
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText(/暂无模型配置/)).toBeInTheDocument();
    });
  });
});

// ─── Learn Page Tests ────────────────────────────────

describe("Learn Page", () => {
  it("renders chat interface with course data", async () => {
    vi.doMock("next/navigation", () => ({
      useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
      useSearchParams: () => {
        const params = new URLSearchParams();
        params.set("courseId", "c1");
        params.set("sectionId", "s1");
        return params;
      },
      usePathname: () => "/learn",
    }));

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": {
        id: "c1",
        title: "测试课程",
        description: "desc",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        source_ids: [],
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
    });

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;
    render(
      <SuspenseWrapper>
        <LearnPage />
      </SuspenseWrapper>
    );

    await waitFor(
      () => {
        // The learn page should show the course title and tab bar
        expect(screen.getByText("测试课程")).toBeInTheDocument();
        // Tab bar should include the tutor tab
        expect(screen.getByText("导师")).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  });
});

// ─── Path Page Tests ─────────────────────────────────

describe("Path Page", () => {
  it("renders course sections", async () => {
    vi.doMock("next/navigation", () => ({
      useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
      useSearchParams: () => {
        const params = new URLSearchParams();
        params.set("courseId", "c1");
        return params;
      },
      usePathname: () => "/path",
    }));

    globalThis.fetch = mockFetch({
      "/api/v1/courses/c1": {
        id: "c1",
        title: "测试课程",
        description: "课程描述",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        source_ids: [],
        sections: [
          {
            id: "s1",
            title: "基础概念",
            order_index: 0,
            difficulty: 1,
            content: {},
          },
          {
            id: "s2",
            title: "进阶内容",
            order_index: 1,
            difficulty: 3,
            content: {},
          },
        ],
      },
    });

    vi.resetModules();
    const PathPage = (await import("@/app/path/page")).default;
    render(
      <SuspenseWrapper>
        <PathPage />
      </SuspenseWrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("测试课程")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("基础概念")).toBeInTheDocument();
      expect(screen.getByText("进阶内容")).toBeInTheDocument();
    });
  });
});

// ─── API Client Tests ────────────────────────────────

describe("API Client", () => {
  it("createSourceFromURL calls fetch correctly", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "src1",
          type: "bilibili",
          status: "pending",
          task_id: "t1",
        }),
    });

    const { createSourceFromURL } = await import("@/lib/api");
    const result = await createSourceFromURL(
      "https://bilibili.com/video/BV1test"
    );

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = (globalThis.fetch as any).mock.calls[0];
    expect(url).toContain("/api/v1/sources");
    expect(options.method).toBe("POST");
    expect(result.type).toBe("bilibili");
  });

  it("listCourses returns paginated response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ items: [], total: 0, skip: 0, limit: 20 }),
    });

    const { listCourses } = await import("@/lib/api");
    const result = await listCourses();

    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
  });
});
