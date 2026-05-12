"use client";

import {
  useSyncExternalStore,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import {
  Source_Serif_4,
  Geist,
  Geist_Mono,
  Noto_Serif_SC,
  Noto_Sans_SC,
} from "next/font/google";
import Script from "next/script";

import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { useLocaleStore } from "@/lib/i18n";

/* Fonts — loaded once at the root and hung on `--font-*` CSS variables.
   `globals.css` references these via `--serif/--sans/--mono`. */
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-source-serif",
  display: "swap",
});

const geist = Geist({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-geist",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-geist-mono",
  display: "swap",
});

const notoSerif = Noto_Serif_SC({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-noto-serif-sc",
  display: "swap",
});

const notoSans = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-noto-sans-sc",
  display: "swap",
});

/**
 * Sidebar shows everywhere except dedicated full-bleed routes.
 * `/learn/*` owns its own three-column shell, and `/login` / `/setup`
 * are the cold-start landing surfaces.
 */
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
  // The sidebar is the project's primary chrome — show it everywhere except
  // the explicit cold-start / full-bleed routes. This mirrors the original
  // layout's behaviour (e.g. an unknown `/learners` route still gets nav).
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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Build a reusable "use this CSS variable for --serif/sans/mono" scope.
  const fontVars = `${sourceSerif.variable} ${geist.variable} ${geistMono.variable} ${notoSerif.variable} ${notoSans.variable}`;
  return (
    <html lang="zh" suppressHydrationWarning className={fontVars}>
      <head>
        <style>{`
          :root {
            --font-serif: ${sourceSerif.style.fontFamily}, ${notoSerif.style.fontFamily};
            --font-sans: ${geist.style.fontFamily}, ${notoSans.style.fontFamily};
            --font-mono: ${geistMono.style.fontFamily};
          }
        `}</style>
      </head>
      <body>
        {/* Boot script — applies the persisted theme + density before first
            paint so the warm-paper palette never flashes a stale scheme
            between SSR and hydration. ``beforeInteractive`` injects it
            ahead of any client-side JS without triggering React's
            "script tag inside component" warning. */}
        <Script
          id="socratiq-boot-theme"
          strategy="beforeInteractive"
        >
          {`(()=>{try{const t=localStorage.getItem('locale.theme');const d=localStorage.getItem('locale.density');if(t&&t!=='system')document.documentElement.setAttribute('data-theme',t);else document.documentElement.removeAttribute('data-theme');if(d)document.documentElement.setAttribute('data-density',d);}catch(e){}})();`}
        </Script>
        <a href="#main-content" className="skip-to-content">
          跳到主要内容
        </a>
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
  const showDesktopSidebar = shouldShowSidebar(pathname);
  const hideSidebarEntirely = isHiddenChromeRoute(pathname);
  const mobileOpen = mobileOpenPath === pathname;

  // Re-apply persisted theme / density when the locale store mounts, in case
  // localStorage changed in another tab.
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
