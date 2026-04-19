import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

function mockFetch(responses: Record<string, unknown>) {
  return vi.fn((url: string) => {
    const matchedUrl = Object.keys(responses).find(
      (key) => url.endsWith(key) || url.includes(`${key}?`)
    );

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
      statusText: "Not Found",
      url,
      text: () => Promise.resolve("Not found"),
    });
  });
}

describe("/sources page", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("filters materials and opens the detail drawer", async () => {
    globalThis.fetch = mockFetch({
      "/api/v1/sources": {
        items: [
          {
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
            latest_course_task: {
              task_type: "course_generation",
              status: "running",
              stage: "assembling_course",
            },
            latest_course_id: null,
            course_count: 0,
            created_at: "2026-04-19T00:00:00Z",
            updated_at: "2026-04-19T00:00:00Z",
          },
          {
            id: "src-2",
            type: "pdf",
            title: "Linear Algebra Notes",
            status: "error",
            metadata_: {},
            latest_processing_task: {
              task_type: "source_processing",
              status: "failure",
              stage: "error",
            },
            latest_course_task: null,
            latest_course_id: "course-2",
            course_count: 1,
            created_at: "2026-04-18T00:00:00Z",
            updated_at: "2026-04-18T00:00:00Z",
          },
        ],
        total: 2,
        skip: 0,
        limit: 20,
      },
    }) as typeof fetch;

    const Page = (await import("@/app/sources/page")).default;
    render(<Page />);

    await waitFor(() => {
      expect(screen.getByText("资料")).toBeInTheDocument();
      expect(screen.getByText("Karpathy GPT")).toBeInTheDocument();
      expect(screen.getByText("Linear Algebra Notes")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText("搜索资料标题"), {
      target: { value: "Karpathy" },
    });

    await waitFor(() => {
      expect(screen.getByText("Karpathy GPT")).toBeInTheDocument();
      expect(screen.queryByText("Linear Algebra Notes")).not.toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("状态筛选"), {
      target: { value: "all" },
    });

    fireEvent.click(screen.getByText("Karpathy GPT"));

    await waitFor(() => {
      expect(screen.getByText("当前状态")).toBeInTheDocument();
      expect(screen.getByText("组装课程")).toBeInTheDocument();
    });
  });
});
