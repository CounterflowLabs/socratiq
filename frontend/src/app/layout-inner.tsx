"use client";

import {
  useSyncExternalStore,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { usePathname } from "next/navigation";

import { Sidebar } from "@/components/sidebar";
import { useLocaleStore } from "@/lib/i18n";

export const SIDEBAR_DESKTOP_QUERY = "(min-width: 1024px)";

function isDedicatedLearnRoute(pathname: string): boolean {
  return pathname === "/learn" || pathname.startsWith("/learn/");
}

function isHiddenChromeRoute(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname === "/setup" ||
    pathname === "/welcome" ||
    isDedicatedLearnRoute(pathname)
  );
}

function shouldShowSidebar(pathname: string): boolean {
  return !isHiddenChromeRoute(pathname);
}

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

export function LayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpenPath, setMobileOpenPath] = useState<string | null>(null);
  const isDesktop = useMediaQuery(SIDEBAR_DESKTOP_QUERY);
  const showDesktopSidebar = shouldShowSidebar(pathname);
  const hideSidebarEntirely = isHiddenChromeRoute(pathname);
  const mobileOpen = mobileOpenPath === pathname;

  const setTheme = useLocaleStore((s) => s.setTheme);
  const setDensity = useLocaleStore((s) => s.setDensity);
  const setLang = useLocaleStore((s) => s.setLang);
  const hasHydrated = useRef(false);

  useEffect(() => {
    if (hasHydrated.current) return;
    hasHydrated.current = true;
    try {
      const storedTheme = window.localStorage?.getItem("locale.theme") as
        | "light"
        | "dark"
        | "system"
        | null
        | undefined;
      const storedDensity = window.localStorage?.getItem("locale.density") as
        | "spacious"
        | "balanced"
        | "dense"
        | null
        | undefined;
      const storedLang = window.localStorage?.getItem("locale.lang") as
        | "zh"
        | "en"
        | null
        | undefined;
      if (storedTheme) setTheme(storedTheme);
      if (storedDensity) setDensity(storedDensity);
      if (storedLang) setLang(storedLang);
    } catch {
      // localStorage may be blocked in private mode / sandboxed iframes
    }
  }, [setTheme, setDensity, setLang]);

  if (hideSidebarEntirely) {
    return <>{children}</>;
  }

  const sidebarWidth = isDesktop && showDesktopSidebar ? (collapsed ? 64 : 244) : 0;

  return (
    <div className="app-layout">
      {showDesktopSidebar ? (
        <Sidebar
          collapsed={collapsed}
          desktopMode={isDesktop}
          onToggle={() => setCollapsed(!collapsed)}
          mobileOpen={mobileOpen}
          onMobileToggle={() =>
            setMobileOpenPath((current) => (current === pathname ? null : pathname))
          }
        />
      ) : null}
      <main
        id="main-content"
        className="main-content"
        style={{
          marginLeft: sidebarWidth,
          minHeight: "100vh",
          transition: "margin-left var(--duration-fast) ease",
        }}
      >
        {children}
      </main>
    </div>
  );
}
