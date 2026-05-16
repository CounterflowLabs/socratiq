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
              task_type: "course_generation",
              status: "failure",
              stage: "assembling_course",
              error_summary: "LLM timeout",
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
      expect(screen.getByText("当前状态")).toBeInTheDocument();
      expect(screen.getAllByText("课程生成失败").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("资料来源")).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "https://www.youtube.com/watch?v=kCc8FmEb1nY",
      }),
    ).toHaveAttribute("href", "https://www.youtube.com/watch?v=kCc8FmEb1nY");
    expect(screen.queryByRole("link", { name: "进入课程" })).not.toBeInTheDocument();
    expect(screen.getByText("当前没有可进入的课程，请先查看失败原因。")).toBeInTheDocument();
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

    expect(screen.getByText("组装课程")).toBeInTheDocument();

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
