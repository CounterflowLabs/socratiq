import type { Metadata, Viewport } from "next";
import {
  Source_Serif_4,
  Geist,
  Geist_Mono,
  Noto_Serif_SC,
  Noto_Sans_SC,
} from "next/font/google";
import "./globals.css";
import { LayoutInner } from "./layout-inner";

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

export const metadata: Metadata = {
  title: {
    default: "Socratiq — 你的私人苏格拉底导师",
    template: "%s · Socratiq",
  },
  description:
    "Socratiq 是一个 AI Agent 驱动的个性化学习平台：把任意素材变成对话式课程，并由持续演化的学生画像驱动苏格拉底式引导。",
  applicationName: "Socratiq",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f5efe2" },
    { media: "(prefers-color-scheme: dark)", color: "#1b1814" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
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
        {/* Anti-FOUC boot — apply the persisted theme + density to <html>
            before first paint so the warm-paper palette never flashes a stale
            scheme between SSR and hydration. A raw inline <script> in <head>
            is rendered identically server- and client-side (no hydration
            mismatch) and runs synchronously ahead of body render. It only
            mutates <html>, which carries `suppressHydrationWarning`.
            (next/script `beforeInteractive` was wrong here: from a <body>
            JSX slot it is hoisted into <head>, so its server/client position
            diverged — the hydration error — and per the Next 16 docs it does
            not block hydration anyway.) */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(()=>{try{const t=localStorage.getItem('locale.theme');const d=localStorage.getItem('locale.density');if(t&&t!=='system')document.documentElement.setAttribute('data-theme',t);else document.documentElement.removeAttribute('data-theme');if(d)document.documentElement.setAttribute('data-density',d);}catch(e){}})();`,
          }}
        />
      </head>
      <body>
        <a href="#main-content" className="skip-to-content">
          跳到主要内容
        </a>
        <LayoutInner>{children}</LayoutInner>
      </body>
    </html>
  );
}
