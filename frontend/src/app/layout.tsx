"use client";

import { useSyncExternalStore, useCallback, useState } from "react";
import { usePathname } from "next/navigation";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

// Pages that show the sidebar
const SIDEBAR_PAGES = ["/", "/import", "/settings", "/sources"];

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
    <html lang="zh">
      <body className="bg-[var(--bg)]">
        <LayoutInner>{children}</LayoutInner>
      </body>
    </html>
  );
}

function LayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpenPath, setMobileOpenPath] = useState<string | null>(null);
  const isDesktop = useMediaQuery("(min-width: 768px)");
  const showDesktopSidebar = SIDEBAR_PAGES.includes(pathname);
  const hideSidebarEntirely = pathname === "/login" || pathname === "/setup";
  const mobileOpen = mobileOpenPath === pathname;

  if (hideSidebarEntirely) {
    return <>{children}</>;
  }

  const marginLeft = isDesktop && showDesktopSidebar ? (collapsed ? 64 : 224) : 0;

  return (
    <div className="app-layout">
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        mobileOpen={mobileOpen}
        onMobileToggle={() =>
          setMobileOpenPath((currentPath) => (currentPath === pathname ? null : pathname))
        }
      />
      <main
        className="main-content transition-[margin] duration-200 min-h-screen"
        style={{ marginLeft }}
      >
        {children}
      </main>
    </div>
  );
}
