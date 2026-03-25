"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

// Pages that show the sidebar
const SIDEBAR_PAGES = ["/", "/import", "/settings"];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh">
      <body>
        <LayoutInner>{children}</LayoutInner>
      </body>
    </html>
  );
}

function LayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);

  const showSidebar = SIDEBAR_PAGES.includes(pathname);

  // Close mobile sidebar on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Track desktop breakpoint for margin calculation
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    setIsDesktop(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  if (!showSidebar) {
    return <>{children}</>;
  }

  const marginLeft = isDesktop ? (collapsed ? 64 : 224) : 0;

  return (
    <div className="app-layout">
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        mobileOpen={mobileOpen}
        onMobileToggle={() => setMobileOpen(!mobileOpen)}
      />
      <main
        className="main-content transition-[margin] duration-200"
        style={{ marginLeft }}
      >
        {children}
      </main>
    </div>
  );
}
