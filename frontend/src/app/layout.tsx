"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { clsx } from "clsx";

// Pages that show the sidebar
const SIDEBAR_PAGES = ["/", "/courses", "/explore", "/progress", "/settings"];

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

  const showSidebar = SIDEBAR_PAGES.includes(pathname);

  if (!showSidebar) {
    return <>{children}</>;
  }

  return (
    <div className="app-layout">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <main
        className="main-content"
        style={{ marginLeft: collapsed ? 64 : 224 }}
      >
        {children}
      </main>
    </div>
  );
}
