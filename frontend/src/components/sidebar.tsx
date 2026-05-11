"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clsx } from "clsx";

import {
  IcChevronLeft,
  IcChevronRight,
  IcClose,
  IcDesign,
  IcGraph,
  IcHome,
  IcImport,
  IcLang,
  IcMenu,
  IcMoon,
  IcPlus,
  IcSearch,
  IcSettings,
  IcSources,
  IcSun,
  SocratiqLogo,
} from "@/components/icons";
import { Avatar } from "@/components/ui/avatar";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Ornament } from "@/components/ui/ornament";
import { useLocaleStore, useT } from "@/lib/i18n";
import { useCoursesStore } from "@/lib/stores";

interface NavRow {
  href: string;
  icon: typeof IcHome;
  label: string;
  match: (pathname: string) => boolean;
}

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
  const router = useRouter();
  const { t, lang } = useT();
  const setLang = useLocaleStore((s) => s.setLang);
  const setTheme = useLocaleStore((s) => s.setTheme);
  const themePreference = useLocaleStore((s) => s.theme);
  const { courses } = useCoursesStore();
  const [resolvedDark, setResolvedDark] = useState(false);
  // SSR has no access to localStorage; the locale store re-reads it on
  // client mount. Defer any DOM that depends on the resolved preference
  // until after hydration to avoid the SSR/client title mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  const showLabels = !collapsed || mobileOpen;

  useEffect(() => {
    function update() {
      const explicit = document.documentElement.dataset.theme;
      if (explicit === "dark" || explicit === "light") {
        setResolvedDark(explicit === "dark");
        return;
      }
      setResolvedDark(window.matchMedia("(prefers-color-scheme: dark)").matches);
    }
    update();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => {
      mq.removeEventListener("change", update);
      observer.disconnect();
    };
  }, []);

  const nav: NavRow[] = [
    {
      href: "/",
      icon: IcHome,
      label: t("nav.dashboard"),
      match: (p) => p === "/",
    },
    {
      href: "/import",
      icon: IcImport,
      label: t("nav.import"),
      match: (p) => p.startsWith("/import"),
    },
    {
      href: "/sources",
      icon: IcSources,
      label: t("nav.sources"),
      match: (p) => p.startsWith("/sources"),
    },
    {
      href: "/graph",
      icon: IcGraph,
      label: t("nav.graph"),
      match: (p) => p.startsWith("/graph"),
    },
  ];

  const meta: NavRow[] = [
    {
      href: "/system",
      icon: IcDesign,
      label: t("nav.system"),
      match: (p) => p.startsWith("/system"),
    },
    {
      href: "/settings",
      icon: IcSettings,
      label: t("nav.settings"),
      match: (p) => p.startsWith("/settings"),
    },
  ];

  function toggleTheme() {
    // Cycle: light → dark → system → light. The boot script in layout reads
    // `locale.theme` so the next reload starts in the right place.
    const next = themePreference === "light" ? "dark" : themePreference === "dark" ? "system" : "light";
    setTheme(next);
  }

  function toggleLang() {
    setLang(lang === "zh" ? "en" : "zh");
  }

  return (
    <>
      {/* Mobile hamburger */}
      {!desktopMode && !mobileOpen ? (
        <button
          type="button"
          onClick={onMobileToggle}
          aria-label="打开菜单"
          className="btn btn-outline btn-icon"
          style={{
            position: "fixed",
            left: 12,
            top: 12,
            zIndex: 40,
            height: 40,
            width: 40,
          }}
        >
          <IcMenu size={16} />
        </button>
      ) : null}

      {/* Mobile backdrop */}
      {!desktopMode && mobileOpen ? (
        <div
          role="presentation"
          onClick={onMobileToggle}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            background: "rgba(26, 22, 17, 0.35)",
          }}
        />
      ) : null}

      <aside
        className={clsx("sidebar")}
        style={{
          width: desktopMode ? (collapsed ? 64 : 244) : 244,
          transform: desktopMode || mobileOpen ? "translateX(0)" : "translateX(-100%)",
          transition: "transform var(--duration-fast) ease, width var(--duration-fast) ease",
          position: desktopMode ? "sticky" : "fixed",
          left: 0,
          top: 0,
          zIndex: 60,
          padding: showLabels ? "16px 12px" : "16px 8px",
          display: "flex",
          flexDirection: "column",
          gap: 4,
          height: "100vh",
          overflowY: "auto",
          flexShrink: 0,
          background: "var(--surface)",
          borderRight: "1px solid var(--border)",
        }}
      >
        {/* Brand row */}
        <div
          style={{
            padding: "4px 8px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          {showLabels ? (
            <Link href="/" style={{ display: "inline-flex", textDecoration: "none" }}>
              <SocratiqLogo size={22} />
            </Link>
          ) : (
            <Link href="/" style={{ display: "inline-flex", textDecoration: "none" }}>
              <SocratiqLogo size={22} color="var(--ink)" />
            </Link>
          )}

          {showLabels && desktopMode ? (
            <button
              type="button"
              className="btn btn-icon btn-sm btn-ghost"
              title={t("common.search")}
              aria-label={t("common.search")}
            >
              <IcSearch size={14} />
            </button>
          ) : null}

          {!desktopMode && mobileOpen ? (
            <button
              type="button"
              onClick={onMobileToggle}
              className="btn btn-icon btn-sm btn-ghost"
              aria-label="关闭菜单"
            >
              <IcClose size={14} />
            </button>
          ) : null}
        </div>

        {/* Primary CTA — "新建" routes to import */}
        <button
          type="button"
          className="btn btn-accent"
          style={{
            margin: "0 4px 12px",
            justifyContent: "flex-start",
            gap: 8,
            height: 36,
            padding: showLabels ? "0 12px" : 0,
            width: showLabels ? undefined : 36,
          }}
          onClick={() => {
            router.push("/import");
            if (mobileOpen) onMobileToggle();
          }}
          title={t("common.new")}
        >
          <IcPlus size={14} />
          {showLabels ? <span>{t("common.new")}</span> : null}
        </button>

        {nav.map((row) => {
          const Icon = row.icon;
          const active = row.match(pathname);
          return (
            <Link
              key={row.href}
              href={row.href}
              onClick={() => {
                if (mobileOpen) onMobileToggle();
              }}
              className={clsx("nav-item", active && "active")}
              style={{ justifyContent: showLabels ? "flex-start" : "center" }}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={16} />
              {showLabels ? <span>{row.label}</span> : null}
              {showLabels ? <span className="nav-dot" /> : null}
            </Link>
          );
        })}

        {showLabels && courses.length > 0 ? (
          <>
            <Ornament width={40} />
            <Eyebrow>{t("nav.recent")}</Eyebrow>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 2 }}>
              {courses.slice(0, 3).map((course, idx) => {
                const accentColor =
                  idx === 0
                    ? "var(--accent)"
                    : idx === 1
                      ? "var(--sage)"
                      : "var(--ink-3)";
                return (
                  <Link
                    key={course.id}
                    href={`/path?courseId=${course.id}`}
                    className="nav-item"
                    style={{
                      fontSize: 12,
                      color: "var(--ink-2)",
                      padding: "5px 10px",
                      alignItems: "center",
                    }}
                    onClick={() => {
                      if (mobileOpen) onMobileToggle();
                    }}
                  >
                    <span
                      style={{
                        width: 5,
                        height: 5,
                        borderRadius: "50%",
                        background: accentColor,
                        flexShrink: 0,
                      }}
                    />
                    <span
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {course.title}
                    </span>
                  </Link>
                );
              })}
            </div>
          </>
        ) : null}

        <div style={{ flex: 1 }} />

        <hr className="divider" style={{ margin: "8px 0" }} />

        {meta.map((row) => {
          const Icon = row.icon;
          const active = row.match(pathname);
          return (
            <Link
              key={row.href}
              href={row.href}
              className={clsx("nav-item", active && "active")}
              style={{ justifyContent: showLabels ? "flex-start" : "center" }}
              onClick={() => {
                if (mobileOpen) onMobileToggle();
              }}
            >
              <Icon size={16} />
              {showLabels ? <span>{row.label}</span> : null}
              {showLabels ? <span className="nav-dot" /> : null}
            </Link>
          );
        })}

        {/* Theme + lang quick toggles, shown only when expanded. */}
        {showLabels ? (
          <div
            style={{
              padding: "8px 4px 0",
              display: "flex",
              gap: 6,
              alignItems: "center",
            }}
          >
            <button
              type="button"
              onClick={toggleTheme}
              className="btn btn-ghost btn-sm btn-icon"
              title={t("settings.themeLabel")}
              aria-label={t("settings.themeLabel")}
              suppressHydrationWarning
            >
              {/* Icon depends on the resolved theme which only stabilises
                  after mount — wrap in suppressHydrationWarning so React
                  doesn't warn about the icon swap on the first paint. */}
              <span suppressHydrationWarning>
                {mounted && resolvedDark ? <IcSun size={14} /> : <IcMoon size={14} />}
              </span>
            </button>
            <button
              type="button"
              onClick={toggleLang}
              className="btn btn-ghost btn-sm"
              style={{ paddingLeft: 8, paddingRight: 8, gap: 4 }}
              title={t("settings.langLabel")}
            >
              <IcLang size={14} />
              <span style={{ fontSize: 11 }} suppressHydrationWarning>
                {mounted ? (lang === "zh" ? "中文" : "EN") : ""}
              </span>
            </button>
          </div>
        ) : null}

        {/* Account row */}
        {showLabels ? (
          <div
            style={{
              padding: "12px 8px 4px",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <Avatar name="Y" accent="sage" size={26} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: "var(--ink)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {lang === "zh" ? "本地学习者" : "Local learner"}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: "var(--ink-3)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                ollama · qwen2.5
              </div>
            </div>
          </div>
        ) : null}

        {/* Desktop collapse chevron */}
        {desktopMode ? (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
            className="btn btn-ghost btn-sm btn-icon"
            style={{
              alignSelf: collapsed ? "center" : "flex-end",
              marginTop: 8,
              color: "var(--ink-3)",
            }}
          >
            {collapsed ? <IcChevronRight size={14} /> : <IcChevronLeft size={14} />}
          </button>
        ) : null}
      </aside>
    </>
  );
}
