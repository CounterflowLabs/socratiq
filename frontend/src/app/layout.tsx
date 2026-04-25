"use client";

import { useSyncExternalStore, useCallback, useState } from "react";
import { usePathname } from "next/navigation";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

// Pages that show the sidebar
const SIDEBAR_PAGES = ["/", "/import", "/settings", "/sources"];
export const SIDEBAR_DESKTOP_QUERY = "(min-width: 1024px)";

function isDedicatedLearnRoute(pathname: string): boolean {
  return pathname === "/learn" || pathname.startsWith("/learn/");
}

// Use useSyncExternalStore for media queries to avoid React Compiler issues
function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    [query],
  );
  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query]);
  const getServerSnapshot = useCallback(() => false, []);
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh" suppressHydrationWarning>
      <body className="bg-[var(--bg)]">
        <a href="#main-content" className="skip-to-content">跳到主要内容</a>
        <LayoutInner>{children}</LayoutInner>
      </body>
    </html>
  );
}

export function LayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpenPath, setMobileOpenPath] = useState<string | null>(null);
  const isDesktop = useMediaQuery(SIDEBAR_DESKTOP_QUERY);
  const showDesktopSidebar = SIDEBAR_PAGES.includes(pathname);
  const hideSidebarEntirely =
    pathname === "/login" || pathname === "/setup" || isDedicatedLearnRoute(pathname);
  const mobileOpen = mobileOpenPath === pathname;

  if (hideSidebarEntirely) {
    return <>{children}</>;
  }

  const marginLeft = isDesktop && showDesktopSidebar ? (collapsed ? 64 : 224) : 0;

  return (
    <div className="app-layout">
      <Sidebar
        collapsed={collapsed}
        desktopMode={isDesktop}
        onToggle={() => setCollapsed(!collapsed)}
        mobileOpen={mobileOpen}
        onMobileToggle={() =>
          setMobileOpenPath((currentPath) => (currentPath === pathname ? null : pathname))
        }
      />
      <main
        id="main-content"
        className="main-content transition-[margin] duration-200 min-h-screen"
        style={{ marginLeft }}
      >
        {children}
      </main>
    </div>
  );
}
