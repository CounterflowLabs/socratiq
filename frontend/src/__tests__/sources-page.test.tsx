import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

type MockResponse = {
  items?: unknown[];
  total?: number;
  skip?: number;
  limit?: number;
  [key: string]: unknown;
};

function makeSource(overrides: Record<string, unknown> = {}) {
  return {
    id: "src-1",
    type: "youtube",
    url: "https://www.youtube.com/watch?v=kCc8FmEb1nY",
    title: "Karpathy GPT",
    status: "ready",
    metadata_: {},
    latest_processing_task: {
      task_type: "source_processing",
      status: "success",
      stage: "ready",
    },
    latest_course_task: null,
    latest_course_id: null,
    course_count: 0,
    created_at: "2026-04-19T00:00:00Z",
    updated_at: "2026-04-19T00:00:00Z",
    ...overrides,
  };
}

function jsonResponse(response: MockResponse) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(response),
    text: () => Promise.resolve(JSON.stringify(response)),
  });
}

function mockFetchSequence(
  responses: MockResponse[],
  overrides: { progress?: MockResponse } = {},
) {
  let index = 0;

  return vi.fn((url: string) => {
    if (!url.includes("/api/v1/sources")) {
      return Promise.resolve({
        ok: false,
        status: 404,
        statusText: "Not Found",
        url,
        text: () => Promise.resolve("Not found"),
      });
    }

    if (url.includes("/chunks")) {
      return jsonResponse({ items: [], total: 0, skip: 0, limit: 5 });
    }

    if (url.includes("/citations")) {
      return jsonResponse({ items: [], total: 0 });
    }

    if (url.includes("/progress")) {
      return jsonResponse(
        overrides.progress ?? {
          source_id: "source-1",
          source_status: "ready",
          error: null,
          course_id: null,
          tasks: [],
        },
      );
    }

    const response = responses[Math.min(index, responses.length - 1)];
    index += 1;

    return jsonResponse(response);
  });
}

describe("/sources page", () => {
  beforeEach(() => {
    vi.resetModules();
    const storage = new Map<string, string>([["locale.lang", "zh"]]);
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
        clear: () => storage.clear(),
        removeItem: (key: string) => {
          storage.delete(key);
        },
      },
    });
    window.localStorage.setItem("locale.lang", "zh");
  });

  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("keeps ready materials with active course generation in the processing filter", async () => {
    globalThis.fetch = mockFetchSequence([
      {
        items: [
          makeSource({
            id: "src-processing",
            title: "Karpathy GPT",
            latest_course_task: {
              task_type: "course_generation",
              status: "running",
              stage: "assembling_course",
            },
          }),
          makeSource({
            id: "src-ready",
            title: "Math Notes",
          }),
        ],
        total: 2,
        skip: 0,
        limit: 20,
      },
    ]) as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("Karpathy GPT")).toBeInTheDocument();
      expect(screen.getByText("Math Notes")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("状态筛选"), {
      target: { value: "processing" },
    });

    await waitFor(() => {
      expect(screen.getByText("Karpathy GPT")).toBeInTheDocument();
      expect(screen.queryByText("Math Notes")).not.toBeInTheDocument();
      expect(screen.getByText("课程正在组装中")).toBeInTheDocument();
    });
  });

  it("lets active course generation override stale embed status in the list", async () => {
    globalThis.fetch = mockFetchSequence([
      {
        items: [
          makeSource({
            id: "src-stale-course-active",
            title: "Course Active Material",
            embed: {
              status: "stale",
              model: "old-model",
              reason: "embed model upgraded",
            },
            latest_course_task: {
              id: "task-row-active",
              task_type: "course_generation",
              status: "running",
              stage: "assembling_course",
            },
          }),
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
    ]) as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("Course Active Material")).toBeInTheDocument();
      expect(screen.getByText("课程生成中")).toBeInTheDocument();
      expect(screen.getByText("课程正在组装中")).toBeInTheDocument();
    });

    expect(screen.queryByText("需重新处理")).not.toBeInTheDocument();
    expect(screen.queryByText("embed model upgraded")).not.toBeInTheDocument();
  });

  it("shows a generated course as complete even when embedding is stale", async () => {
    globalThis.fetch = mockFetchSequence([
      {
        items: [
          makeSource({
            id: "src-stale-course-ready",
            title: "Generated Course Material",
            embed: {
              status: "stale",
              model: "old-model",
              reason: "embed model upgraded",
            },
            latest_course_id: "course-ready",
            course_count: 1,
            latest_course_task: {
              id: "task-row-ready",
              task_type: "course_generation",
              status: "success",
              stage: "ready",
            },
          }),
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
    ]) as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("Generated Course Material")).toBeInTheDocument();
      expect(screen.getByText("已生成 1 门课程")).toBeInTheDocument();
    });

    expect(screen.queryByText("需重新处理")).not.toBeInTheDocument();
    expect(screen.queryByText("embed model upgraded")).not.toBeInTheDocument();
  });

  it("shows source section planning as an in-order processing step", async () => {
    globalThis.fetch = mockFetchSequence([
      {
        items: [
          makeSource({
            id: "src-source-planning",
            title: "Planning Source Material",
            status: "planning",
            latest_processing_task: {
              task_type: "source_processing",
              status: "running",
              stage: "planning",
            },
          }),
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
    ]) as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("Planning Source Material")).toBeInTheDocument();
      expect(screen.getByText("资料正在规划章节中")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Planning Source Material"));

    await waitFor(() => {
      expect(screen.getAllByText("规划章节").length).toBeGreaterThan(0);
      expect(screen.queryByText("planning")).not.toBeInTheDocument();
    });
  });

  it("does not show enter-course CTA when the derived state is failed", async () => {
    globalThis.fetch = mockFetchSequence([
      {
        items: [
          makeSource({
            id: "src-failed",
            title: "Broken Material",
            latest_course_id: "course-stale",
            course_count: 1,
            latest_course_task: {
              id: "course-task-row-failed",
              task_type: "course_generation",
              status: "failure",
              stage: "assembling_course",
              error_summary: "LLM timeout",
              celery_task_id: "course-task-failed",
            },
          }),
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
    ]) as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("Broken Material")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Broken Material"));

    await waitFor(() => {
      expect(screen.getByText("课程状态")).toBeInTheDocument();
      expect(screen.getAllByText("课程生成失败").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("资料来源")).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "https://www.youtube.com/watch?v=kCc8FmEb1nY",
      }),
    ).toHaveAttribute("href", "https://www.youtube.com/watch?v=kCc8FmEb1nY");
    expect(screen.queryByRole("link", { name: "进入课程" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试生成" })).toBeInTheDocument();
    expect(screen.getAllByText("LLM timeout").length).toBeGreaterThan(0);
  });

  it("lets active course generation be cancelled from the source drawer", async () => {
    const activeSource = makeSource({
      id: "src-active-course",
      title: "Queued Course Material",
      latest_course_task: {
        id: "task-row-1",
        task_type: "course_generation",
        status: "pending",
        stage: "pending",
        celery_task_id: "course-task-1",
        metadata_: {
          section_progress: {
            total: 2,
            completed: 1,
            failed: 0,
            active: "section-2",
            items: [
              {
                key: "section-1",
                title: "输入层",
                status: "success",
                order_index: 0,
              },
              {
                key: "section-2",
                title: "隐藏层",
                status: "running",
                order_index: 1,
              },
            ],
          },
        },
      },
    });
    const cancelledSource = makeSource({
      id: "src-active-course",
      title: "Queued Course Material",
      latest_course_task: {
        id: "task-row-1",
        task_type: "course_generation",
        status: "cancelled",
        stage: "cancelled",
        celery_task_id: "course-task-1",
      },
    });
    let sourceListCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes("/chunks")) {
        return jsonResponse({ items: [], total: 0, skip: 0, limit: 5 });
      }
      if (url.includes("/citations")) {
        return jsonResponse({ items: [], total: 0 });
      }
      if (url.includes("/progress")) {
        return jsonResponse({
          source_id: "src-active-course",
          source_status: "ready",
          error: null,
          course_id: null,
          tasks: [],
        });
      }
      if (url.includes("/api/v1/tasks/task-row-1/cancel")) {
        expect(init?.method).toBe("POST");
        return jsonResponse({ task_id: "task-row-1", cancelled: true });
      }
      if (url === "/api/v1/sources") {
        sourceListCalls += 1;
        return jsonResponse({
          items: [sourceListCalls > 1 ? cancelledSource : activeSource],
          total: 1,
          skip: 0,
          limit: 20,
        });
      }

      return Promise.resolve({
        ok: false,
        status: 404,
        statusText: "Not Found",
        url,
        text: () => Promise.resolve("Not found"),
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("Queued Course Material")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Queued Course Material"));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "取消课程生成" })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /查看任务/ })).toHaveAttribute("href", "/tasks");
      expect(screen.getByText("排队生成")).toBeInTheDocument();
      expect(screen.getAllByText("规划章节").length).toBeGreaterThan(0);
      expect(screen.getByText("生成组装")).toBeInTheDocument();
      expect(screen.getByText("课程就绪")).toBeInTheDocument();
      expect(screen.getByText("章节组装进度")).toBeInTheDocument();
      expect(screen.getByText("已完成 1 / 2 个 section。")).toBeInTheDocument();
      expect(screen.getByText(/#1 输入层/)).toBeInTheDocument();
      expect(screen.getByText(/#2 隐藏层/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "取消课程生成" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/v1/tasks/task-row-1/cancel", {
        method: "POST",
      });
      expect(screen.getAllByText("已取消").length).toBeGreaterThan(0);
    });
  });

  it("renders cancelled materials consistently in the list and drawer", async () => {
    globalThis.fetch = mockFetchSequence(
      [
        {
          items: [
            makeSource({
              id: "src-cancelled",
              title: "Cancelled Material",
              status: "cancelled",
              latest_processing_task: {
                task_type: "source_processing",
                status: "cancelled",
                stage: "cancelled",
              },
              embed: {
                status: "queued",
                model: null,
              },
            }),
          ],
          total: 1,
          skip: 0,
          limit: 20,
        },
      ],
      {
        progress: {
          source_id: "src-cancelled",
          source_status: "cancelled",
          error: null,
          course_id: null,
          tasks: [
            {
              task_type: "source_processing",
              status: "cancelled",
              stage: "cancelled",
              error_summary: null,
              celery_task_id: "task-cancelled",
              cancel_requested: false,
              course_id: null,
              created_at: "2026-04-19T00:00:00Z",
              updated_at: "2026-04-19T00:00:00Z",
            },
          ],
        },
      },
    ) as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("Cancelled Material")).toBeInTheDocument();
      expect(screen.getByText("已取消")).toBeInTheDocument();
    });

    expect(screen.queryByText("排队中")).not.toBeInTheDocument();
    expect(screen.queryByText("资料正在cancelled中")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Cancelled Material"));

    await waitFor(() => {
      expect(screen.getAllByText("资料处理已取消，可重试处理").length).toBeGreaterThan(0);
      expect(screen.getByText("重试处理")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("历史")).toBeInTheDocument();
    });

    expect(screen.queryByText(/^cancelled$/)).not.toBeInTheDocument();
    expect(screen.queryByText("资料正在cancelled中")).not.toBeInTheDocument();
  });

  it("polls active materials and updates the card and drawer state", async () => {
    vi.useFakeTimers();

    globalThis.fetch = mockFetchSequence([
      {
        items: [
          makeSource({
            id: "src-polling",
            title: "Realtime Material",
            latest_course_task: {
              task_type: "course_generation",
              status: "running",
              stage: "assembling_course",
            },
          }),
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
      {
        items: [
          makeSource({
            id: "src-polling",
            title: "Realtime Material",
            latest_course_task: {
              task_type: "course_generation",
              status: "success",
              stage: "ready",
            },
            latest_course_id: "course-123",
            course_count: 1,
            updated_at: "2026-04-19T00:05:00Z",
          }),
        ],
        total: 1,
        skip: 0,
        limit: 20,
      },
    ]) as unknown as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("Realtime Material")).toBeInTheDocument();
    expect(screen.getByText("课程正在组装中")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Realtime Material"));

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getAllByText("组装课程").length).toBeGreaterThan(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(screen.getAllByText("已生成课程").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "进入课程" })).toHaveAttribute(
      "href",
      "/path?courseId=course-123"
    );

    expect(screen.queryByText("加载中...")).not.toBeInTheDocument();
  });
});
