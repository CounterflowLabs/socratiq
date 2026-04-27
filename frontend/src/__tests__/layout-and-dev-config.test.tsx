import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../../next.config";
import { LayoutInner, SIDEBAR_DESKTOP_QUERY } from "@/app/layout";

const { mockPathname } = vi.hoisted(() => ({
  mockPathname: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
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

  it("bridges common light Tailwind utilities to theme variables in dark mode", () => {
    const css = readFileSync("src/app/globals.css", "utf8");

    expect(css).toContain(':root[data-theme="dark"] :where(.bg-white');
    expect(css).toContain(':root:not([data-theme="light"]) :where(.bg-white');
    expect(css).toContain(".text-gray-900");
    expect(css).toContain(".border-gray-200");
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
