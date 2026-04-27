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
