import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../../next.config";
import { LayoutInner, SIDEBAR_DESKTOP_QUERY } from "@/app/layout-inner";

const { mockPathname } = vi.hoisted(() => ({
  mockPathname: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
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

describe("frontend dev config", () => {
  it("allows local IAB origins in development", () => {
    expect(nextConfig.allowedDevOrigins).toEqual(
      expect.arrayContaining(["127.0.0.1", "localhost"])
    );
  });

  it("ships the warm-paper design tokens and a dark-mode palette", () => {
    // The legacy Tailwind-utility bridge has been replaced with first-class
    // tokens. This test now verifies that the redesign's identity primitives
    // (terracotta accent, sage, paper bg, dark scholarly variant) are present.
    const css = readFileSync("src/app/globals.css", "utf8");

    expect(css).toContain("--bg: #f3ede1");
    expect(css).toContain("--accent: #c96442");
    expect(css).toContain("--sage: #6b7d5b");
    expect(css).toContain(':root[data-theme="dark"]');
    expect(css).toContain(':root[data-density="dense"]');
    expect(css).toContain(':root[data-density="spacious"]');
  });
});

describe("app layout responsiveness", () => {
  beforeEach(() => {
    installMatchMedia(1082);
    mockPathname.mockReturnValue("/sources");
  });

  it("does not reserve desktop sidebar space on mid-width viewports", () => {
    const { container } = render(
      <LayoutInner>
        <div>资料页</div>
      </LayoutInner>
    );

    const main = container.querySelector("main");
    expect(main).not.toBeNull();
    expect(main).toHaveStyle({ marginLeft: "0px" });
  });

  it("does not treat /learners as a dedicated learn route", () => {
    mockPathname.mockReturnValue("/learners");

    render(
      <LayoutInner>
        <div>学习者列表</div>
      </LayoutInner>
    );

    expect(screen.getByLabelText("打开菜单")).toBeInTheDocument();
  });
});
