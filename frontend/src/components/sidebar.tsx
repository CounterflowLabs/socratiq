"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, BookOpen, ChevronLeft, ChevronRight, Brain, Settings, Menu, X, Sun, Moon } from "lucide-react";
import { clsx } from "clsx";

const items = [
  { id: "/", label: "首页", icon: Home },
  { id: "/sources", label: "资料", icon: BookOpen },
  { id: "/settings", label: "设置", icon: Settings },
];

export function Sidebar({
  collapsed,
  desktopMode,
  onToggle,
  mobileOpen,
  onMobileToggle,
}: {
  collapsed: boolean;
  desktopMode: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileToggle: () => void;
}) {
  const pathname = usePathname();
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    // Restore saved theme on mount
    const saved = localStorage.getItem("theme");
    if (saved === "dark" || saved === "light") {
      document.documentElement.dataset.theme = saved;
      setIsDark(saved === "dark");
    } else {
      setIsDark(window.matchMedia("(prefers-color-scheme: dark)").matches);
    }
  }, []);

  function toggleTheme() {
    const next = isDark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    setIsDark(!isDark);
  }

  return (
    <>
      {/* Mobile hamburger button — hidden when sidebar is open */}
      {!desktopMode && !mobileOpen && (
        <button
          onClick={onMobileToggle}
          className="fixed left-3 top-3 z-40 flex h-11 w-11 items-center justify-center"
          style={{
            borderRadius: "var(--radius)",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--text-secondary)",
          }}
          aria-label="打开菜单"
        >
          <Menu className="w-5 h-5" />
        </button>
      )}

      {/* Mobile overlay backdrop */}
      {!desktopMode && mobileOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/20"
          onClick={onMobileToggle}
        />
      )}

      {/* Sidebar — desktop: always visible; mobile: slide-in overlay */}
      <aside
        className={clsx(
          "fixed left-0 top-0 z-[60] flex h-full flex-col transition-[width,transform] duration-200",
          desktopMode
            ? [collapsed ? "w-16" : "w-56", "translate-x-0"]
            : ["w-64", mobileOpen ? "translate-x-0" : "-translate-x-full"]
        )}
        style={{
          background: "var(--surface)",
          borderRight: "1px solid var(--border)",
          transition: `width var(--duration-fast) ease`,
        }}
      >
        {/* Logo + mobile close */}
        <div
          className="flex items-center gap-2 px-4 h-14"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div
            className="w-8 h-8 flex items-center justify-center flex-shrink-0"
            style={{ borderRadius: "var(--radius-sm)", background: "var(--primary)" }}
          >
            <Brain className="w-4 h-4 text-white" />
          </div>
          {(!collapsed || mobileOpen) && (
            <span
              className="font-semibold text-sm flex-1"
              style={{ color: "var(--text)" }}
            >
              Socratiq
            </span>
          )}
          {/* Mobile close button */}
          {!desktopMode && mobileOpen && (
            <button
              onClick={onMobileToggle}
              className="flex h-8 w-8 items-center justify-center"
              style={{
                borderRadius: "var(--radius-sm)",
                color: "var(--text-tertiary)",
                transition: `background var(--duration-fast) ease`,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface-alt)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              aria-label="关闭菜单"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-2 px-2 space-y-0.5">
          {items.map((item) => {
            const Icon = item.icon;
            const isActive =
              item.id === "/"
                ? pathname === "/"
                : pathname.startsWith(item.id);
            return (
              <Link
                key={item.id}
                href={item.id}
                onClick={() => mobileOpen && onMobileToggle()}
                className="w-full flex items-center gap-3 px-3 py-2.5 min-h-[44px] text-sm no-underline"
                style={{
                  borderRadius: "var(--radius)",
                  background: isActive ? "var(--primary-light)" : "transparent",
                  color: isActive ? "var(--primary)" : "var(--text-secondary)",
                  fontWeight: isActive ? 500 : 400,
                  transition: `background var(--duration-fast) ease, color var(--duration-fast) ease`,
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    (e.currentTarget as HTMLElement).style.background = "var(--surface-alt)";
                    (e.currentTarget as HTMLElement).style.color = "var(--text)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    (e.currentTarget as HTMLElement).style.background = "transparent";
                    (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                  }
                }}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {(!collapsed || mobileOpen) && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Theme toggle */}
        <div className="px-2 pb-1">
          <button
            onClick={toggleTheme}
            className="w-full flex items-center gap-3 px-3 py-2.5 min-h-[44px] text-sm"
            style={{
              borderRadius: "var(--radius)",
              color: "var(--text-secondary)",
              transition: `background var(--duration-fast) ease`,
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--surface-alt)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            aria-label="切换深色/浅色模式"
          >
            {isDark ? <Sun className="w-4 h-4 flex-shrink-0" /> : <Moon className="w-4 h-4 flex-shrink-0" />}
            {(!collapsed || mobileOpen) && <span>{isDark ? "浅色模式" : "深色模式"}</span>}
          </button>
        </div>

        {/* Toggle — desktop only */}
        {desktopMode && (
          <div className="p-2" style={{ borderTop: "1px solid var(--border)" }}>
            <button
              onClick={onToggle}
              className="w-full flex items-center justify-center p-2"
              style={{
                borderRadius: "var(--radius)",
                color: "var(--text-tertiary)",
                transition: `background var(--duration-fast) ease, color var(--duration-fast) ease`,
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.background = "var(--surface-alt)";
                (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = "transparent";
                (e.currentTarget as HTMLElement).style.color = "var(--text-tertiary)";
              }}
            >
              {collapsed ? (
                <ChevronRight className="w-4 h-4" />
              ) : (
                <ChevronLeft className="w-4 h-4" />
              )}
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
