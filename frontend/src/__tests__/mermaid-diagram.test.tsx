import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const initializeMock = vi.fn();
const renderMock = vi.fn(async () => ({ svg: "<svg data-testid='mock-mermaid'></svg>" }));

vi.mock("mermaid", () => ({
  default: {
    initialize: initializeMock,
    render: renderMock,
  },
}));

function installColorSchemeMatchMedia(prefersDark: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)" ? prefersDark : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as typeof window.matchMedia;
}

describe("MermaidDiagram", () => {
  beforeEach(() => {
    initializeMock.mockClear();
    renderMock.mockClear();
    document.documentElement.removeAttribute("data-theme");
    installColorSchemeMatchMedia(false);
  });

  afterEach(() => {
    document.documentElement.removeAttribute("data-theme");
  });

  it("uses explicit dark theme styling when the site theme is dark", async () => {
    document.documentElement.dataset.theme = "dark";
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(<MermaidDiagram title="流程图" content={"flowchart TD\nA-->B"} />);

    await waitFor(() => {
      expect(initializeMock).toHaveBeenCalledWith(
        expect.objectContaining({
          theme: "base",
          themeVariables: expect.objectContaining({
            primaryColor: "#13203C",
            primaryTextColor: "#F8FAFC",
            lineColor: "#94A3B8",
          }),
        })
      );
    });
  });

  it("defaults to light theme when no explicit site theme is set", async () => {
    installColorSchemeMatchMedia(true);
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(<MermaidDiagram title="流程图" content={"flowchart TD\nA-->B"} />);

    await waitFor(() => {
      expect(initializeMock).toHaveBeenCalledWith(
        expect.objectContaining({
          theme: "base",
          themeVariables: expect.objectContaining({
            primaryColor: "#F8FBFF",
            primaryTextColor: "#0F172A",
          }),
        })
      );
    });
  });

  it("renders the raw diagram source when Mermaid rendering fails", async () => {
    renderMock.mockRejectedValueOnce(new Error("broken graph"));
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(<MermaidDiagram title="流程图" content={"flowchart TD\nA-->B"} />);

    await waitFor(() => {
      expect(document.querySelector("pre")?.textContent).toBe("flowchart TD\nA-->B");
    });
  });

  it("keeps Mermaid diagrams as static summaries without autoplay controls", async () => {
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(<MermaidDiagram title="流程图" content={"flowchart TD\nA[起点]-->B[终点]"} />);

    await waitFor(() => {
      expect(screen.getByText("流程摘要")).toBeTruthy();
    });
    expect(screen.queryByText("Show Me Demo")).toBeNull();
    expect(screen.queryByRole("button", { name: "播放动态讲解" })).toBeNull();
  });
});
