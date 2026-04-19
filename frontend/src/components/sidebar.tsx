"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, BookOpen, Search, BarChart3, ChevronLeft, ChevronRight, Brain, Settings, Menu, X } from "lucide-react";
import { clsx } from "clsx";

const items = [
  { id: "/", label: "首页", icon: Home },
  { id: "/import", label: "导入资料", icon: Search },
  { id: "/settings", label: "设置", icon: Settings },
];

export function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileToggle: () => void;
}) {
  const pathname = usePathname();

  return (
    <>
      {/* Mobile hamburger button — hidden when sidebar is open */}
      {!mobileOpen && (
        <button
          onClick={onMobileToggle}
          className="fixed top-3 left-3 z-40 flex md:hidden items-center justify-center w-11 h-11"
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
      {mobileOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/20 md:hidden"
          onClick={onMobileToggle}
        />
      )}

      {/* Sidebar — desktop: always visible; mobile: slide-in overlay */}
      <aside
        className={clsx(
          "fixed left-0 top-0 h-full z-[60] flex flex-col",
          "hidden md:flex",
          collapsed ? "md:w-16" : "md:w-56",
          mobileOpen && "!flex w-64"
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
          {mobileOpen && (
            <button
              onClick={onMobileToggle}
              className="flex md:hidden items-center justify-center w-8 h-8"
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

        {/* Toggle — desktop only */}
        <div
          className="hidden md:block p-2"
          style={{ borderTop: "1px solid var(--border)" }}
        >
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
      </aside>
    </>
  );
}
