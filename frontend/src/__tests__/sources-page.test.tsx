import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

type MockResponse = {
  items: unknown[];
  total: number;
  skip?: number;
  limit?: number;
};

function makeSource(overrides: Record<string, unknown> = {}) {
  return {
    id: "src-1",
    type: "youtube",
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

function mockFetchSequence(responses: MockResponse[]) {
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

    const response = responses[Math.min(index, responses.length - 1)];
    index += 1;

    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(response),
      text: () => Promise.resolve(JSON.stringify(response)),
    });
  });
}

describe("/sources page", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.useRealTimers();
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
    ]) as typeof fetch;

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
      expect(screen.getByText("课程生成中")).toBeInTheDocument();
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
    ]) as typeof fetch;

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

    expect(screen.queryByRole("link", { name: "进入课程" })).not.toBeInTheDocument();
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
    ]) as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("Realtime Material")).toBeInTheDocument();
    expect(screen.getByText("课程生成中")).toBeInTheDocument();

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
