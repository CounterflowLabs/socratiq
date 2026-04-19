import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../../next.config";
import { LayoutInner, SIDEBAR_DESKTOP_QUERY } from "@/app/layout";

vi.mock("next/navigation", () => ({
  usePathname: () => "/sources",
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
});

describe("app layout responsiveness", () => {
  beforeEach(() => {
    installMatchMedia(1082);
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
});
