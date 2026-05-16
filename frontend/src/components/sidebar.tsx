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
  IcClock,
  IcImport,
  IcLang,
  IcMenu,
  IcMoon,
  IcPlus,
  IcSearch,
  IcSettings,
  IcSources,
  IcSparkle,
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
  // Pull the actual mentor model out of /api/v1/model-routes so the account
  // row in the sidebar shows the truth (was hardcoded to "ollama · qwen2.5"
  // even when the user routed mentor_chat to a different model).
  const [mentorModelLabel, setMentorModelLabel] = useState<string | null>(null);
  useEffect(() => {
    setMounted(true);
  }, []);
  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      fetch("/api/v1/model-routes").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/v1/models").then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([routes, models]) => {
        if (cancelled) return;
        const mentorRoute = Array.isArray(routes)
          ? routes.find((r: { task_type: string }) => r.task_type === "mentor_chat")
          : null;
        if (!mentorRoute) return;
        const model = Array.isArray(models)
          ? models.find((m: { name: string }) => m.name === mentorRoute.model_name)
          : null;
        if (!model) {
          setMentorModelLabel(mentorRoute.model_name);
          return;
        }
        const provider = String(model.provider_type ?? "")
          .replace(/_/g, " ")
          .trim();
        setMentorModelLabel(provider ? `${provider} · ${model.model_id}` : model.model_id);
      })
      .catch(() => {
        // Sidebar is decorative — never show an error here.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const showLabels = !collapsed || mobileOpen;
  const [newMenuOpen, setNewMenuOpen] = useState(false);

  // Close the +New popover on outside click / escape.
  useEffect(() => {
    if (!newMenuOpen) return;
    function close(e: MouseEvent | KeyboardEvent) {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      setNewMenuOpen(false);
    }
    window.addEventListener("click", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", close);
    };
  }, [newMenuOpen]);

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
      href: "/sources",
      icon: IcSources,
      label: t("nav.sources"),
      match: (p) => p.startsWith("/sources"),
    },
    {
      href: "/tasks",
      icon: IcClock,
      label: t("nav.tasks"),
      match: (p) => p.startsWith("/tasks"),
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

        {/* Primary CTA — "+ 新建" opens a popover so the user picks the
            task type (add source vs generate course) before navigating. */}
        <div style={{ position: "relative", margin: "0 4px 12px" }}>
          <button
            type="button"
            className="btn btn-accent"
            style={{
              justifyContent: "flex-start",
              gap: 8,
              height: 36,
              padding: showLabels ? "0 12px" : 0,
              width: showLabels ? "100%" : 36,
            }}
            onClick={(e) => {
              e.stopPropagation();
              setNewMenuOpen((v) => !v);
            }}
            aria-expanded={newMenuOpen}
            title={t("common.new")}
          >
            <IcPlus size={14} />
            {showLabels ? <span>{t("common.new")}</span> : null}
          </button>

          {newMenuOpen ? (
            <div
              onClick={(e) => e.stopPropagation()}
              role="menu"
              style={{
                position: "absolute",
                top: 42,
                left: showLabels ? 0 : 40,
                width: 256,
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-lg)",
                boxShadow: "var(--shadow-lg)",
                padding: 6,
                zIndex: 50,
              }}
            >
              <NewMenuItem
                icon={<IcImport size={16} />}
                title={t("newPopover.addSourceTitle")}
                hint={t("newPopover.addSourceHint")}
                chip={t("tasks.typeEmbed")}
                chipClass="chip-accent"
                onClick={() => {
                  setNewMenuOpen(false);
                  router.push("/import");
                  if (mobileOpen) onMobileToggle();
                }}
              />
              <NewMenuItem
                icon={<IcSparkle size={16} />}
                title={t("newPopover.generateTitle")}
                hint={t("newPopover.generateHint")}
                chip={t("tasks.typeGenerate")}
                chipClass="chip-sage"
                onClick={() => {
                  setNewMenuOpen(false);
                  router.push("/generate");
                  if (mobileOpen) onMobileToggle();
                }}
              />
              <hr className="divider" style={{ margin: "6px 0" }} />
              <button
                type="button"
                className="nav-item"
                style={{ gap: 10 }}
                onClick={() => {
                  setNewMenuOpen(false);
                  router.push("/tasks");
                  if (mobileOpen) onMobileToggle();
                }}
              >
                <IcClock size={14} />
                <span style={{ fontSize: 12 }}>
                  {t("newPopover.viewTasks")}
                </span>
              </button>
            </div>
          ) : null}
        </div>

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
                suppressHydrationWarning
              >
                {mentorModelLabel ?? (lang === "zh" ? "未配置导师模型" : "Mentor not set")}
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

function NewMenuItem({
  icon,
  title,
  hint,
  chip,
  chipClass,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  chip: string;
  chipClass: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      role="menuitem"
      style={{
        width: "100%",
        background: "transparent",
        border: "none",
        cursor: "pointer",
        textAlign: "left",
        padding: "10px 12px",
        borderRadius: "var(--r)",
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-2)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = "transparent";
      }}
    >
      <span
        style={{
          width: 28,
          height: 28,
          borderRadius: "var(--r)",
          background: "var(--surface-2)",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--ink-2)",
          flexShrink: 0,
        }}
      >
        {icon}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            color: "var(--ink)",
            font: "500 13px var(--sans)",
          }}
        >
          {title}
          <span className={`chip ${chipClass}`} style={{ height: 18, fontSize: 10 }}>
            {chip}
          </span>
        </span>
        <span style={{ display: "block", fontSize: 11, color: "var(--ink-3)", marginTop: 2 }}>
          {hint}
        </span>
      </span>
    </button>
  );
}
