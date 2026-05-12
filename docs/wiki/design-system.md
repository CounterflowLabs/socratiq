# Design system

The current frontend design ships as commit `2c0ee27 feat(frontend): warm-paper redesign + persistent Socratic mentor`. This page describes the visual system, where tokens live, and how to extend without breaking dark mode or i18n.

## Identity in one sentence

Socratiq is for **slow study**. Warm paper, serif display, considered density. Terracotta for "you're working on this", sage for "you've mastered this", ink for the things that don't move. Not a productivity tool — a tutor.

## File map

```
frontend/src/
├── app/globals.css                Token defs + base typography + Tailwind bridge
├── app/layout.tsx                 Loads fonts via next/font, applies persisted theme/density
├── lib/i18n.ts                    Translation table + Zustand locale store
├── components/icons.tsx           50 custom icons + SocratiqMark / SocratiqLogo
├── components/ui/
│   ├── eyebrow.tsx                Mono uppercase 11px label
│   ├── ornament.tsx               — • —  scholarly divider
│   ├── page-header.tsx            Eyebrow + 40px serif title + subtitle + action slot
│   ├── section-title.tsx          13px bold + optional mono count + action slot
│   ├── progress-bar.tsx           Progress / ProgressBar
│   ├── avatar.tsx                 Serif-initial chip
│   ├── chip primitives            CSS-class-driven (.chip / .chip-accent / .chip-sage / .chip-warn / .chip-mono)
│   ├── button.tsx                 Wraps the .btn token classes
│   ├── card.tsx                   Wraps .card / .card-quiet / .card-soft
│   ├── badge.tsx                  Legacy alias mapping color names to chip variants
│   └── segmented.tsx              Theme/lang/density-style toggle
├── app/system/page.tsx            Design-system showcase (mark + colors + type + icons + components)
└── app/graph/page.tsx             Knowledge graph view (uses .hatched bg)
```

## Tokens (`globals.css`)

The whole palette is CSS variables on `:root`. Every page and component should consume them — never hardcode hex. Dark theme overrides the same variables on `:root[data-theme="dark"]`.

```css
:root {
  /* Warm paper surfaces */
  --bg: #f3ede1;            /* paper */
  --surface: #faf6ed;        /* card */
  --surface-2: #ebe2d0;      /* recessed surfaces */
  --surface-3: #e4d9c2;      /* deeper still */

  --ink: #1a1611;            /* primary text */
  --ink-2: #5c5448;          /* secondary text */
  --ink-3: #8b8270;          /* tertiary text */
  --ink-4: #b3a890;          /* placeholder text */

  --border: rgba(26, 22, 17, 0.10);
  --border-2: rgba(26, 22, 17, 0.06);
  --border-strong: rgba(26, 22, 17, 0.20);

  /* Semantic accents */
  --accent: #c96442;        /* terracotta — primary action / "learning" */
  --accent-hover: #b85636;
  --accent-soft: #f0e0d2;
  --accent-ink: #6b2e1a;

  --sage: #6b7d5b;          /* "mastered" / success */
  --sage-soft: #dde2d4;
  --sage-ink: #3d4a32;

  --warn: #b8842a;          /* "review due" / warning */
  --warn-soft: #f1e6cc;

  --error: #b3422f;
  --error-soft: #f4dbd3;

  /* Type stacks — values are injected by next/font in layout.tsx */
  --serif: var(--font-serif), Georgia, "Source Han Serif SC", "Noto Serif SC", serif;
  --sans:  var(--font-sans), -apple-system, BlinkMacSystemFont, "PingFang SC", system-ui, sans-serif;
  --mono:  var(--font-mono), ui-monospace, "SF Mono", Menlo, monospace;

  /* Density (balanced is default; spacious / dense override these) */
  --gap-xs: 4px;  --gap-sm: 8px;  --gap: 12px;
  --gap-md: 16px; --gap-lg: 24px; --gap-xl: 40px;
  --pad-card: 20px;

  /* Radius */
  --r-sm: 4px; --r: 8px; --r-md: 10px; --r-lg: 14px; --r-xl: 20px;
}

:root[data-theme="dark"] {
  --bg: #14110e;
  --surface: #1d1916;
  /* etc. — see globals.css for the full set */
}
```

Same tokens reshape under `:root[data-density="dense"]` and `:root[data-density="spacious"]`. The shape of every page changes from one container, no per-page tuning.

## Type pairing

Loaded via `next/font/google` in `app/layout.tsx`:

| Role | Family | Use |
|---|---|---|
| Display / serif | **Source Serif 4** + Noto Serif SC | Page titles, lesson titles, mentor messages, course names |
| Body / sans | **Geist** + Noto Sans SC | UI chrome, controls, body copy |
| Mono | **Geist Mono** | Timecodes, code, IDs, eyebrows, tabular numerals |

Eyebrow utility:
```css
.eyebrow {
  font-family: var(--mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-3);
  font-weight: 500;
}
```

Use `Eyebrow` (the React primitive) over hand-writing the class — its semantics are everywhere ("section 03", weekday strings, status labels).

## Icons

`components/icons.tsx` exports ~60 single-purpose components:

```tsx
<IcLesson size={16} />            // open-book stacked-pages glyph
<IcMentor size={18} />            // speech bubble with question dot
<IcExercise size={14} />          // clipboard with tick
<IcGraph size={20} />             // 3-node mini cluster
<SocratiqMark size={32} />        // stroked Q with dot + tail
<SocratiqLogo size={22} />        // mark + serif "socratiq" wordmark
<SourceIcon type="bilibili" />    // dispatcher for {youtube, bilibili, pdf, markdown, url}
```

All icons use `stroke="currentColor"`, 1.5px stroke (configurable via `stroke` prop), `strokeLinecap="round"`. Tweak inline styles via `style={{ color: "var(--accent)" }}`.

`SourceIcon` is the convention for "I need to render the icon for an unknown source type" — dispatches by string, falls back to a folder glyph.

## Color usage rules

1. **Primary action** uses `var(--ink)` background, `var(--surface)` text. Looks like "ink on paper". Not an accent — the primary action is the calm one.
2. **Accent button** uses `var(--accent)` background, `#fff` text. Reserved for high-priority CTAs like "新建" / "开始分析" / "导师".
3. **Outline button** uses `var(--surface)` background, `var(--border-strong)` border, ink text. Tertiary.
4. **Ghost button** is transparent until hover. Quaternary, for icon-only or low-weight actions.
5. **Mastery palette** is dedicated:
   - "Mastered" → `var(--ink)` (filled or text)
   - "Learning" → `var(--accent)` (filled or text)
   - "Seen" → outline only with `var(--ink-4)`
   - These are what the Graph nodes use.
6. **Status chips** (sage/warn/error) map to learning state, never to decoration.

## Components ship as CSS classes

Most "components" are CSS classes (in `globals.css`) wrapped by tiny React primitives:

```css
.btn { display: inline-flex; align-items: center; height: 32px; padding: 0 12px; ... }
.btn-primary { background: var(--ink); color: var(--surface); ... }
.btn-accent  { background: var(--accent); color: #fff; ... }
.btn-outline { background: var(--surface); border: 1px solid var(--border-strong); ... }
.btn-ghost   { color: var(--ink-2); }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; }
.btn-lg { height: 40px; padding: 0 18px; font-size: 14px; }
.btn-icon { padding: 0; width: 32px; }

.card        { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); padding: var(--pad-card); }
.card-quiet  { background: transparent; border: 1px solid var(--border); ... }
.card-soft   { background: var(--surface-2); ... }

.chip        { 22px pill, --surface-2 bg, --ink-2 text, --border border }
.chip-accent { --accent-soft bg, --accent-ink text }
.chip-sage   { --sage-soft   bg, --sage-ink   text }
.chip-warn   { --warn-soft   bg, --warn       text }
.chip-mono   { font-family: var(--mono); }
```

This is intentional. The React wrappers (`<Button>`, `<Card>`, `<Badge>`) just pick a class. Swapping a token in `globals.css` updates every consumer.

## The hatched fill

```css
.hatched {
  background-color: var(--surface-2);
  background-image: repeating-linear-gradient(135deg, transparent, transparent 6px, var(--border-2) 6px, var(--border-2) 7px);
}
```

Used for placeholder regions (the Graph canvas; the Import page's file-upload dropzone; the mini-graph panel on the dashboard hero card). 135° gives "engineering paper" rather than "loading state". The pattern uses `--border-2` so it shifts correctly in dark mode.

## i18n

`lib/i18n.ts` exports a `useT()` hook and `tr(lang, key, ...args)` function. The translation table is a typed Pydantic-like nested object:

```ts
const dict = {
  zh: {
    nav: { dashboard: "今日", import: "导入", sources: "资料库", ... },
    common: { new: "新建", continue: "继续学习", ... },
    learn: { mentor: "苏格拉底导师", askPlaceholder: "问导师一个问题…", ... },
    ...
  },
  en: { /* same shape */ },
};

const { t, lang } = useT();
t("learn.mentor");          // 苏格拉底导师 | Socratic mentor
t("learn.progressLabel", 1, 4);  // 进度 1/4   | 1 / 4
```

Keys are dot-paths, fully typed via `TranslationKey`. Adding a key: edit `dict.zh` and `dict.en` in `lib/i18n.ts`. Both languages are required at parity.

Locale persistence: Zustand store at `useLocaleStore`. Reads localStorage on client init (server-safe), writes on every toggle. The `<html lang>` attribute isn't currently switched — but the visible UI strings are.

## Dark mode bridge

The redesign migrated everything to tokens, but 13 legacy components still use raw Tailwind palette utilities (`bg-white`, `text-slate-900`, `bg-blue-600`, etc.). The bridge in `globals.css` re-routes those classes:

```css
/* Global — applies in both themes — saturated CTAs map to the new accent */
:where(.bg-blue-500, .bg-blue-600, .bg-blue-700, .bg-violet-600, ...) {
  background-color: var(--accent);
  color: #fff;
}

/* Dark-only — pale backgrounds map to dark surfaces */
:root[data-theme="dark"] :where(.bg-white, .bg-slate-50, .bg-sky-50, ...) {
  background-color: var(--surface) | var(--surface-2) | var(--accent-soft);
}
```

This is a **stopgap**, not the steady state. Each legacy component should eventually author itself directly in tokens. The bridge is intentionally narrow (only the classes actually in use) so we can grep `:where(.bg-` to find what's still legacy.

Files still on legacy palette (run `grep -l "bg-slate-\|bg-blue-6" src --include="*.tsx"`):
- `app/setup/page.tsx`
- `app/exercise/page.tsx`
- `app/diagnostic/page.tsx`
- `components/lab/lab-editor.tsx` + `lab-viewer.tsx`
- `components/materials/source-pipeline-view.tsx` + `source-detail-drawer.tsx`
- `components/lesson/timestamp-link.tsx` + `step-by-step.tsx` + `lesson-block-renderer.tsx`
- `components/lesson/blocks/exercise-trigger-card.tsx` + `practice-trigger-card.tsx`
- `components/learn/regenerate-drawer.tsx`

## Density

`data-density="dense"` shrinks gaps and card padding; `data-density="spacious"` enlarges them. Always reach for `var(--gap-md)` etc. instead of hardcoding `16px` — that way the density toggle works for your new component.

## Adding a new component

```tsx
// components/ui/ribbon.tsx
import { Eyebrow } from "./eyebrow";

export function Ribbon({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      style={{
        background: "var(--surface-2)",          // ← tokens, not Tailwind
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        padding: "var(--gap-sm) var(--gap-md)",  // ← density-aware
        display: "flex",
        gap: "var(--gap-sm)",
      }}
    >
      <Eyebrow>{label}</Eyebrow>
      <div style={{ color: "var(--ink-2)", fontSize: 13 }}>{children}</div>
    </div>
  );
}
```

If you find yourself reaching for `bg-white` or `text-slate-900`, stop. Use the token. The bridge exists for legacy, not for new code.

## The `/system` showcase

The page at `frontend/src/app/system/page.tsx` is a living reference: mark in three treatments (paper, ink-tinted, lockup), all color swatches with hex + variable name, the full type ramp with CJK samples, the entire icon grid, and every component (buttons / chips / inputs / ornament). Visit it after any token change to eyeball that nothing regressed.

## Adjacent docs

- [Frontend layout](./frontend-layout.md) — how the tokens compose into pages
- [Architecture](./architecture.md) — frontend ↔ backend boundary
