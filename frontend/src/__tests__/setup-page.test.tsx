import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

function jsonResponse(response: unknown) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(response),
    text: () => Promise.resolve(JSON.stringify(response)),
  });
}

describe("Setup Page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("keeps Ollama embedding models out of the chat model selector", async () => {
    globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/setup/status")) {
        return jsonResponse({
          has_models: false,
          ollama_available: true,
          ollama_models: ["nomic-embed-text:latest", "qwen3.6:latest"],
          ollama_embedding_models: ["nomic-embed-text:latest"],
          ollama_base_url: "http://localhost:11434/v1",
          codex_available: false,
          codex_logged_in: false,
          codex_auth_mode: null,
          codex_status_message: "",
          codex_models: [],
          codex_error: null,
        });
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        text: () => Promise.resolve("Not found"),
      });
    }) as unknown as typeof fetch;

    const SetupPage = (await import("@/app/setup/page")).default;
    render(<SetupPage />);

    await waitFor(() => {
      expect(screen.getByText("检测到本地 Ollama")).toBeInTheDocument();
    });

    const selector = screen.getByRole("combobox") as HTMLSelectElement;
    expect(selector.value).toBe("qwen3.6:latest");
    expect(screen.queryByRole("option", { name: "nomic-embed-text:latest" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /同时配置向量模型/ }));

    const selectors = screen.getAllByRole("combobox") as HTMLSelectElement[];
    expect(selectors).toHaveLength(2);
    expect(selectors[0].value).toBe("qwen3.6:latest");
    expect(selectors[1].value).toBe("nomic-embed-text:latest");
    expect(screen.getByRole("option", { name: "nomic-embed-text:latest" })).toBeInTheDocument();
  });
});
