import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/react";
import React, { Suspense } from "react";

// Mock react-markdown (ESM-only package that doesn't work in jsdom).
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

function mockFetch(responses: Record<string, unknown>): typeof fetch {
  const fn = vi.fn((url: string) => {
    const sortedKeys = Object.keys(responses).sort((a, b) => b.length - a.length);
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
  return fn as unknown as typeof fetch;
}

function mockSettingsFetch(options: {
  models?: unknown[];
  routes?: unknown[];
  createModel?: unknown;
} = {}): typeof fetch {
  const models = options.models ?? [];
  const routes = options.routes ?? [];
  const createModel = options.createModel ?? {
    name: "created-model",
    provider_type: "openai_compatible",
    model_type: "chat",
    model_id: "created-model",
    supports_tool_use: true,
    supports_streaming: true,
    max_tokens_limit: 4096,
    is_active: true,
  };

  const fn = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/api/v1/models") && init?.method === "POST") {
      return Promise.resolve({
        ok: true,
        status: 201,
        json: () => Promise.resolve(createModel),
        text: () => Promise.resolve(JSON.stringify(createModel)),
      });
    }
    if (url.endsWith("/api/v1/model-routes")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(routes),
        text: () => Promise.resolve(JSON.stringify(routes)),
      });
    }
    if (url.endsWith("/api/v1/models")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(models),
        text: () => Promise.resolve(JSON.stringify(models)),
      });
    }
    if (url.endsWith("/api/v1/setup/bilibili/status")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ logged_in: false }),
        text: () => Promise.resolve(JSON.stringify({ logged_in: false })),
      });
    }
    if (url.endsWith("/api/v1/setup/whisper")) {
      const whisper = {
        mode: "api",
        api_base_url: "",
        api_model: "",
        api_key_masked: null,
        local_model: "base",
      };
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(whisper),
        text: () => Promise.resolve(JSON.stringify(whisper)),
      });
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      text: () => Promise.resolve("Not found"),
    });
  });
  return fn as unknown as typeof fetch;
}

function SuspenseWrapper({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<div>Loading…</div>}>{children}</Suspense>;
}

import { useChatStore, useCoursesStore, useSourcesStore, useTasksStore } from "@/lib/stores";

function resetStores() {
  useCoursesStore.getState().setCourses([]);
  useCoursesStore.getState().setLoading(false);
  useChatStore.getState().clearChat();
  useSourcesStore.getState().setSources([]);
  useSourcesStore.getState().setLoading(false);
  useTasksStore.setState({ tasks: [] });
}

beforeEach(() => {
  resetStores();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.resetModules();
});

// ─── Dashboard ─────────────────────────────────────────

describe("Dashboard", () => {
  it("shows the empty-state CTA when no courses are loaded", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/courses": { items: [], total: 0, skip: 0, limit: 20 },
      "/api/v1/reviews/stats": { due_today: 0, completed_today: 0 },
      "/api/v1/reviews/due": { items: [] },
      "/api/v1/setup/status": { has_models: true },
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
            version_index: 1,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
      "/api/v1/reviews/stats": { due_today: 0, completed_today: 0 },
      "/api/v1/reviews/due": { items: [] },
      "/api/v1/setup/status": { has_models: true },
    });

    const DashboardPage = (await import("@/app/page")).default;
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("深度学习基础")).toBeInTheDocument();
    });
  });
});

// ─── Import ────────────────────────────────────────────

describe("Import Page", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn((url: RequestInfo | URL) => {
      const u = typeof url === "string" ? url : url.toString();
      if (u.includes("/setup/bilibili/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ logged_in: true, source: "db" }),
        }) as ReturnType<typeof fetch>;
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      }) as ReturnType<typeof fetch>;
    }) as unknown as typeof fetch;
  });

  it("renders the URL / Upload / Text tabs", async () => {
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    expect(screen.getByRole("button", { name: /从链接导入/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /上传文件/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /粘贴文本/ })).toBeInTheDocument();
  });

  it("shows the URL input on the URL tab by default", async () => {
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText(/粘贴 B站 \/ YouTube 链接/),
      ).toBeInTheDocument();
    });
  });

  it("blocks bilibili import and shows the settings link when no credential is configured", async () => {
    const push = vi.fn();
    vi.doMock("next/navigation", () => ({
      useRouter: () => ({ push, back: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
      useSearchParams: () => new URLSearchParams(),
      usePathname: () => "/import",
    }));

    globalThis.fetch = vi.fn((url: RequestInfo | URL) => {
      const u = typeof url === "string" ? url : url.toString();
      if (u.includes("/setup/bilibili/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ logged_in: false, source: null }),
        }) as ReturnType<typeof fetch>;
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as ReturnType<typeof fetch>;
    }) as unknown as typeof fetch;

    vi.resetModules();
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    const input = screen.getByPlaceholderText(/粘贴 B站 \/ YouTube 链接/);
    fireEvent.change(input, { target: { value: "https://www.bilibili.com/video/BV1xx" } });

    const banner = await screen.findByRole("alert");
    expect(banner.textContent).toContain("登录");

    fireEvent.click(screen.getByRole("button", { name: /前往设置登录/ }));
    expect(push).toHaveBeenCalledWith("/settings?section=sources");
  });

  it("submits a URL import and pushes the user to /sources", async () => {
    const push = vi.fn();

    vi.doMock("next/navigation", () => ({
      useRouter: () => ({ push, back: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
      useSearchParams: () => new URLSearchParams(),
      usePathname: () => "/import",
    }));

    let createCalls = 0;
    const fetchMock = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      const u = typeof url === "string" ? url : url.toString();
      if (u.includes("/setup/bilibili/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ logged_in: true, source: "db" }),
        }) as ReturnType<typeof fetch>;
      }
      if (u.includes("/api/v1/sources") && init?.method === "POST") {
        createCalls += 1;
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({ id: "src1", type: "bilibili", status: "pending", task_id: "t1" }),
      }) as ReturnType<typeof fetch>;
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    vi.resetModules();
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    fireEvent.change(screen.getByPlaceholderText(/B站|Bilibili/), {
      target: { value: "https://www.bilibili.com/video/BV1xoJwzDESD" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始分析|Analyze/ }));

    await waitFor(() => expect(createCalls).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: /资料库|source library/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/sources"));
  });

  it("shows an existing-source prompt and jumps to the source detail", async () => {
    const push = vi.fn();

    vi.doMock("next/navigation", () => ({
      useRouter: () => ({ push, back: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
      useSearchParams: () => new URLSearchParams(),
      usePathname: () => "/import",
    }));

    globalThis.fetch = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      const u = typeof url === "string" ? url : url.toString();
      if (u.includes("/setup/bilibili/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ logged_in: true, source: "db" }),
        }) as ReturnType<typeof fetch>;
      }
      if (u.includes("/api/v1/sources") && init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: "src-existing",
              type: "bilibili",
              url: "https://www.bilibili.com/video/BV1xoJwzDESD",
              title: "Existing Material",
              status: "ready",
              metadata_: {},
              task_id: null,
              latest_processing_task: null,
              latest_course_task: null,
              course_count: 1,
              latest_course_id: "course-existing",
              duplicate_of_source_id: "src-existing",
              duplicate_reason: "user_existing",
              created_at: "2026-04-19T00:00:00Z",
              updated_at: "2026-04-19T00:00:00Z",
            }),
        }) as ReturnType<typeof fetch>;
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      }) as ReturnType<typeof fetch>;
    }) as unknown as typeof fetch;

    vi.resetModules();
    const ImportPage = (await import("@/app/import/page")).default;
    render(<ImportPage />);

    fireEvent.change(screen.getByPlaceholderText(/B站|Bilibili/), {
      target: { value: "https://www.bilibili.com/video/BV1xoJwzDESD" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始分析|Analyze/ }));

    await waitFor(() => {
      expect(screen.getByText("已存在资料")).toBeInTheDocument();
      expect(screen.getByText("已找到已有资料：Existing Material")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /打开已有资料/ }));
    expect(push).toHaveBeenCalledWith("/sources?sourceId=src-existing");
  });
});

// ─── Settings ──────────────────────────────────────────

describe("Settings Page", () => {
  it("renders model rows when LLM section is active", async () => {
    const modelsData = [
      {
        name: "claude-sonnet",
        provider_type: "anthropic",
        model_type: "chat",
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

    globalThis.fetch = mockSettingsFetch({
      models: modelsData,
      routes: routesData,
    });

    const SettingsPage = (await import("@/app/settings/page")).default;
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: "LLM 提供商" }));

    await waitFor(() => {
      expect(screen.getAllByText("claude-sonnet").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("anthropic")).toBeInTheDocument();
    });
  });

  it("opens the add-model form and prefills the DeepSeek preset", async () => {
    const fetchMock = mockSettingsFetch({
      createModel: {
        name: "deepseek-default",
        provider_type: "openai_compatible",
        model_type: "chat",
        model_id: "deepseek-v4-flash",
        base_url: "https://api.deepseek.com",
        supports_tool_use: true,
        supports_streaming: true,
        max_tokens_limit: 4096,
        is_active: true,
      },
    });
    globalThis.fetch = fetchMock;

    const SettingsPage = (await import("@/app/settings/page")).default;
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: "LLM 提供商" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /添加模型/ })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /添加模型/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "Provider 预设" }), {
      target: { value: "deepseek" },
    });

    expect(screen.getByDisplayValue("deepseek-default")).toBeInTheDocument();
  });
});

// ─── Learn ─────────────────────────────────────────────

describe("Learn Page", () => {
  it("renders the persistent-mentor learn shell with the back-to-home link", async () => {
    vi.doMock("next/navigation", () => ({
      useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
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
        version_index: 1,
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
    });

    vi.resetModules();
    const LearnPage = (await import("@/app/learn/page")).default;
    render(
      <SuspenseWrapper>
        <LearnPage />
      </SuspenseWrapper>,
    );

    await waitFor(
      () => {
        expect(screen.getByRole("heading", { name: "测试课程" })).toBeInTheDocument();
        expect(screen.getByText("课程目录")).toBeInTheDocument();
        expect(screen.getByLabelText("返回首页")).toHaveAttribute("href", "/");
      },
      { timeout: 3000 },
    );
  });
});

// ─── Path ──────────────────────────────────────────────

describe("Path Page", () => {
  it("renders course sections grouped by unit", async () => {
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
        version_index: 1,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        sources: [],
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
      "/api/v1/courses/c1/progress": [],
    });

    vi.resetModules();
    const PathPage = (await import("@/app/path/page")).default;
    render(
      <SuspenseWrapper>
        <PathPage />
      </SuspenseWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "测试课程" })).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("基础概念")).toBeInTheDocument();
      expect(screen.getByText("进阶内容")).toBeInTheDocument();
    });
  });
});

// ─── API Client ────────────────────────────────────────

describe("API Client", () => {
  it("createSourceFromURL calls fetch correctly", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "src1",
          type: "bilibili",
          status: "pending",
          task_id: "t1",
        }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { createSourceFromURL } = await import("@/lib/api");
    const result = await createSourceFromURL("https://bilibili.com/video/BV1test");

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toContain("/api/v1/sources");
    expect(options.method).toBe("POST");
    expect(result.type).toBe("bilibili");
  });

  it("listCourses returns paginated response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ items: [], total: 0, skip: 0, limit: 20 }),
    });

    const { listCourses } = await import("@/lib/api");
    const result = await listCourses();

    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
  });
});
