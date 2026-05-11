import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";
import React from "react";

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    back: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));

// Mock next/link
type MockLinkProps = React.AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  children: React.ReactNode;
};

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: MockLinkProps) =>
    React.createElement("a", { href, ...props }, children),
}));

// next/font/google ships transformed font metadata at build time. In jsdom
// the real module isn't usable — return inert variable / style descriptors so
// importing layout.tsx in tests doesn't blow up.
vi.mock("next/font/google", () => {
  const fakeFont = (config: { variable?: string }) => ({
    variable: config?.variable ?? "--font-test",
    style: { fontFamily: "Test" },
    className: "test-font",
  });
  return {
    Source_Serif_4: fakeFont,
    Geist: fakeFont,
    Geist_Mono: fakeFont,
    Noto_Serif_SC: fakeFont,
    Noto_Sans_SC: fakeFont,
  };
});
