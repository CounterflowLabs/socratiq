import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const initializeMock = vi.fn();
const parseMock = vi.fn(async () => ({ diagramType: "flowchart-v2" }));
const renderMock = vi.fn(async () => ({ svg: "<svg data-testid='mock-mermaid'></svg>" }));

vi.mock("mermaid", () => ({
  default: {
    initialize: initializeMock,
    parse: parseMock,
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
    parseMock.mockClear();
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
            primaryColor: "#EEF4FF",
            primaryTextColor: "#0F172A",
          }),
        })
      );
    });
  });

  it("normalizes generated flowchart labels before rendering", async () => {
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(
      <MermaidDiagram
        title="流程图"
        content={"flowchart TD\nA[编码器输出 (512维)] --> B[解码器输出 (512维)]"}
      />
    );

    await waitFor(() => {
      expect(renderMock).toHaveBeenCalledWith(
        expect.any(String),
        'flowchart TD\nA["编码器输出 (512维)"] --> B["解码器输出 (512维)"]'
      );
    });
  });

  it("normalizes generated prime node ids before rendering", async () => {
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(
      <MermaidDiagram
        title="流程图"
        content={"graph LR\nA[H₁：分词] --> C'\nC' --> F[解码生成\"easy\"]"}
      />
    );

    await waitFor(() => {
      expect(renderMock).toHaveBeenCalledWith(
        expect.any(String),
        'graph LR\nA["H₁：分词"] --> C_prime\nC_prime --> F["解码生成#quot;easy#quot;"]'
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

  it("does not display Mermaid's generated error svg", async () => {
    renderMock.mockResolvedValueOnce({
      svg: "<svg><text>Syntax error in text</text><text>mermaid version 11.13.0</text></svg>",
    });
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(<MermaidDiagram title="流程图" content={"flowchart TD\nA[输入 (512维)] --> B"} />);

    await waitFor(() => {
      expect(screen.getByText("图表渲染失败，显示原始语法：")).toBeInTheDocument();
      expect(document.querySelector("pre")?.textContent).toBe(
        "flowchart TD\nA[输入 (512维)] --> B"
      );
    });
    expect(screen.queryByText("Syntax error in text")).not.toBeInTheDocument();
  });

  it("renders Mermaid diagrams without auxiliary summary panels", async () => {
    const { default: MermaidDiagram } = await import("@/components/lesson/mermaid-diagram");

    render(<MermaidDiagram title="流程图" content={"flowchart TD\nA[起点]-->B[终点]"} />);

    await waitFor(() => {
      expect(document.querySelector("[data-testid='mock-mermaid']")).toBeTruthy();
    });
    expect(screen.queryByText("Show Me Demo")).toBeNull();
    expect(screen.queryByRole("button", { name: "播放动态讲解" })).toBeNull();
    expect(screen.queryByText("2 个节点")).toBeNull();
    expect(screen.queryByText("节点")).toBeNull();
    expect(screen.queryByText("连接")).toBeNull();
    expect(screen.queryByText("分支")).toBeNull();
    expect(screen.queryByText("线性主线")).toBeNull();
    expect(screen.queryByText("含分支路径")).toBeNull();
  });
});
