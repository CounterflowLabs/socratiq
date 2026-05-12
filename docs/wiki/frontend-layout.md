# Frontend layout

Page-by-page reference. Each page has a corresponding `app/**/page.tsx` and consumes the design tokens from [design-system.md](./design-system.md).

## Top-level shell

`frontend/src/app/layout.tsx` is the global shell:

```
<html lang="zh" suppressHydrationWarning>
  <head>
    <script>            ← inline pre-paint theme/density bootstrapper
    <style>--font-*     ← font variables from next/font/google
  </head>
  <body>
    <a className="skip-to-content" href="#main-content">跳到主要内容</a>
    <LayoutInner>{children}</LayoutInner>
  </body>
</html>
```

`LayoutInner` decides whether to mount the persistent left sidebar. It hides the sidebar on:
- `/login`, `/setup` (cold-start landing surfaces)
- `/learn` and `/learn/...` (the Learn shell owns its own 3-column chrome)

Everywhere else: sidebar shows. The page's `<main>` gets a `marginLeft: 244px` on desktop (`>=1024px`), `0` on mobile (where the sidebar becomes an overlay).

Routes:

| Path | Page module | Sidebar? |
|---|---|---|
| `/` | `app/page.tsx` (Today) | yes |
| `/import` | `app/import/page.tsx` | yes |
| `/sources` | `app/sources/page.tsx` (Library) | yes |
| `/path` | `app/path/page.tsx` (Course outline) | yes |
| `/learn` | `app/learn/page.tsx` | **no** (owns its own shell) |
| `/graph` | `app/graph/page.tsx` (Knowledge graph) | yes |
| `/settings` | `app/settings/page.tsx` | yes |
| `/system` | `app/system/page.tsx` (Design system showcase) | yes |
| `/welcome`, `/diagnostic`, `/exercise` | aux pages | yes |
| `/login`, `/setup` | cold-start | **no** |

## Sidebar

`components/sidebar.tsx`. Layout, top to bottom:

```
┌─ Q-mark + serif "socratiq"                   [search icon] ─┐
│ [+ 新建]   accent CTA, routes to /import                    │
│                                                              │
│ 🏠 今日       /                                              │
│ ↓  导入      /import                                         │
│ 📁 资料库    /sources                                        │
│ ⊗  知识图谱  /graph                                          │
│                                                              │
│ — • —    ornament                                            │
│ RECENT                                                       │
│ • Smoke test                                                 │
│ • Tier2-known-good                                           │
│                                                              │
│ ─────────                                                    │
│ ⊠ 设计系统   /system                                         │
│ ⚙ 设置      /settings                                        │
│                                                              │
│ [☀/☾]  [🌐 中文]    theme + lang quick toggles               │
│ ⓨ 本地学习者  ollama · qwen2.5                              │
│ <                          collapse chevron (desktop only)   │
└──────────────────────────────────────────────────────────────┘
```

Width: 244px expanded, 64px collapsed (desktop). On mobile (< 1024px) it slides in over a backdrop.

The "recent courses" list reads `useCoursesStore()` (Zustand). The first 3 are shown; clicking goes to `/path?courseId=...`.

The theme toggle cycles `light → dark → system`. The lang toggle flips between `zh` and `en`. Both persist via `useLocaleStore` (localStorage). The icon swaps via a `mounted` guard to avoid SSR/client hydration mismatch.

## `/` Today (dashboard)

`app/page.tsx`. Structure:

1. **PageHeader** — weekday eyebrow ("MONDAY, MAY 11"), 40px serif "今日" title, subtitle, "+ 新建" action.
2. **Continue hero card** — only if `courses[0]` exists. Two-column:
   - Left: eyebrow "继续上次", 28px serif course title, source meta row (`SourceIcon · description · last-touched`), progress bar `01 / 04 · 进度 · 25%` row, "继续学习" primary button + "导师" ghost button.
   - Right: hatched mini-graph (5 SVG nodes representing the current concept neighborhood — placeholder until real graph data feeds in).
   - The whole card is `role="link"` so clicking anywhere navigates. Inner buttons stop propagation so they can do their own thing.
3. **Review section** — if `dueReviews.length > 0`. SectionTitle with count + `SM-2` mono label. Grid of `ReviewCard`s (tap-to-reveal answer + 4-button SM-2 rating).
4. **Processing section** — if there are active import tasks. Inline rows with `<SourceIcon>` + progress fragment (`embedding 64% · ~2 min`).
5. **Course grid** — `auto-fill, minmax(300px, 1fr)`. Each card: corner accent strip (terracotta/sage/ink rotating by index), serif title, description, `4 课文` count, last-touched timestamp, tiny progress bar at the bottom.

Loading state: spinner. Empty state: centered card with "还没有课程" + a primary CTA to `/import`.

The dashboard fetches via `lib/api.ts:listCourses()`. The pre-flight check is `getSetupStatus()` — if `has_models === false`, it redirects to `/setup`.

## `/import`

`app/import/page.tsx`. Centered narrow column (`max-width: 720px`).

```
01
导入新资料
一切学习的起点。从一段视频或一份文档开始。

[ 从链接导入 ] [ 上传文件 ] [ 粘贴文本 ]    ← tabs

[ URL input                                  ] [开始分析]
SUPPORTS [YouTube] [Bilibili] [PDF] [Markdown]

或试试这些示例
┌─ 📺 Karpathy — Let's build GPT from scratch ─┐
│   youtube.com/watch?v=...    1h 56m          │
└──────────────────────────────────────────────┘
... three sample cards

— • —

PROMPTS
01  我们优先复用已有字幕，无字幕时使用 Whisper。
02  PDF 与 Markdown 文档将按章节自动切分。
03  导入完成后会做一次 5 分钟的入学诊断。
```

After submit, the page transitions to a 4-step pipeline view (`fetch_transcript → analyze_content → plan_path → assemble_course`), each step with a numbered circle (pending) / spinning loader (active) / sage check (done). The pipeline animates forward at 1.1s/step locally — real status comes via background polling once the user lands on `/sources`.

Bilibili-credential gate: if the URL is bilibili.com and `getBilibiliStatus().logged_in === false`, the analyze button disables and a banner appears with a link to `/settings`.

## `/sources` Library

`app/sources/page.tsx`. Sortable table view:

```
资料库
所有导入过的源材料 — 章节、字幕、嵌入向量、引用都从这里开始。

[🔍 搜索资料标题             ] [▿ 全部状态]  当前显示 9 / 9 份资料

NAME                                   LENGTH  IMPORTED  CITED
─────────────────────────────────────────────────────────────
📺 Tier2-known-good                    —       5月9日    1×
   [已生成课程]  已生成 1 门课程
📺 Tier2-clean2                        —       5月9日    0×
   [资料处理失败]  资料处理失败，请查看详情
... etc.
```

The "CITED" counter renders in terracotta when `>5`. Click a row to open the `SourceDetailDrawer` (the slide-in right panel with stage-by-stage task progress and an "进入课程" CTA).

Polls `listSources()` every 3s if any source has an active task. Pure DB-authoritative state.

## `/path/:id`

`app/path/page.tsx`. Two-column wide layout (1280px max).

Left: scholarly outline.
- Back link `← 返回`.
- Eyebrow `课程路径 · 共 4 节`.
- 44px serif course title.
- Meta row: `SourceIcon · BILIBILI · 24 concepts · ~48m`.
- Description paragraph.
- Optional version chip: `第 2 版 · 查看上一版`.
- **Unit blocks** — sections grouped by `metadata_.unit` (or all-in-one if absent). Each block starts with `01 / 04 · 全部课文` (mono numbering + serif unit name).
- **Lesson rows** — status dot (sage check / accent arrow / outline / dashed-locked) · `L07` mono · serif lesson title · `当前` chip if current · meta row (`~12m`, `exercise`, `lab`, score%) · chevron.

Right (sticky 280px rail):
- **当前位置** card on `--accent-soft`. 4 actions: 阅读课文 (primary) / 做练习 / 进入 Lab / 与导师对话.
- **本周节奏** sparkline (placeholder bars; real data when learning_records is wired).

The "重新生成" CTA at the top opens `RegenerateDrawer`. While a regeneration is running, a banner sits between the header and the outline showing `重新生成中 · 生成课文 (4/12) · 38%`.

## `/learn` Learn (the consequential one)

`app/learn/page.tsx` + `components/learn/learn-shell.tsx`. Three columns by default on desktop:

```
┌─── outline 260 ────┐┌──────── lesson 760 ─────────┐┌────── mentor 380 ──────┐
│ LEARNING MAP      ││ [当前章节]                   ││ 苏格拉底导师           │
│ 课程目录          ││ Smoke test                   ││ 不直接给答案 …         │
│                    ││                              ││                        │
│ L01 ▸ first lesson││ [0:12]                       ││ 记得 · shaky           │
│ L02   second      ││  Lesson body in serif        ││                        │
│ L03   third       ││  17px / 1.65                 ││ [Empty state w/ mark]  │
│                    ││  …                           ││ Ask the mentor…        │
│ — • —              ││                              ││ ┌────────────────────┐ │
│ 本节脉络          ││  [1] [2] inline cite chips   ││ │ textarea           │ │
│ 1 从正文开始 0:12││                              ││ └────────────────────┘ │
│ 2 把概念跑起来   ││  ───────────────────────     ││ ✨ Suggest  🪲 Cite    │
│                    ││  [← 上一节] [下一节 →]      ││                        │
└────────────────────┘└──────────────────────────────┘└────────────────────────┘
```

`LearnShell` is a single inline-grid that swaps column counts based on `outlineOpen` × `asideOpen` × `isDesktop`. On mobile, the aside becomes a slide-up dialog overlay.

**Mentor as default panel.** The right rail's top has a small tab strip (`AI 导师 / 原视频 / 原 PDF / 参考资料`) — but on first load the active tab is **AI 导师**, and the rail renders the `MentorPanel` (chat composer + message stream + memory chips) directly. Per PRD §5.5, reading and dialogue are one continuous study surface.

Components:
- `components/learn/learn-shell.tsx` — header + sticky outline/aside columns + regenerate banner.
- `components/learn/course-outline.tsx` — left rail. Lessons as a list; waypoints (per-section heading) under a `本节脉络` ornament.
- `components/learn/study-aside.tsx` — right rail. Switches between MentorPanel (inline mode) and the materials card (video iframe / PDF link / references list).
- `components/learn/mentor-panel.tsx` — shared component for both inline rail and the legacy slide-in TutorDrawer overlay. `variant="inline" | "overlay"`.
- `components/lesson/lesson-renderer.tsx` → `lesson-block-renderer.tsx` — the lesson body, block by block.

Clicking a timestamp link in the lesson body fires `handleTimestampClick` in `app/learn/page.tsx`: opens the aside, switches the active panel to "video", persists the preference so subsequent section changes keep the video visible.

## `/graph`

`app/graph/page.tsx`. Stats strip → graph canvas + detail rail.

```
KNOWLEDGE GRAPH
知识图谱
你已经接触过的概念与它们之间的关系。

[Smoke test ▾] [▾ 筛选] [↻]      ← course picker + filter + regenerate

┌─ 概念总数 ─┬─ 已掌握 ─┬─ 学习中 ─┬─ 已接触 ─┐
│   24      │   8     │   5     │   11    │
└────────────┴──────────┴──────────┴─────────┘
 (clicking each column filters the graph to that mastery state)

┌── hatched canvas (4:3) ──────────────┐ ┌─ CONCEPT ─┐
│           ◯─────◯                    │ │ binary_search │
│         ◯─╳─•─◯                      │ │ [learning]    │
│             │                        │ │ — • —         │
│           ◯─◯                        │ │ Appears in 7  │
│ [Legend] ●mastered ●learning ◯seen   │ │ lessons; 5    │
└──────────────────────────────────────┘ │ neighbors…    │
                                          │ Open lesson → │
                                          └───────────────┘
```

Layout: deterministic concentric rings (1 center / 6 inner / 12 outer / wrap on the outermost). Filter dims to 0.2 opacity rather than hiding. Hover shows the detail card; click navigates to `/learn?sectionId=...` if the concept is anchored to a section.

See [Concepts & graph](./concepts-and-graph.md) for the data layer.

## `/settings`

`app/settings/page.tsx`. Left section rail + right pane.

```
设置

[外观]
 LLM 提供商
 模型路由
 数据源

──────── right pane (active = 外观) ────────
外观
主题、语言、密度都会立即生效，并保存在浏览器本地。

主题       [☀亮][☾暗][系统]      ← segmented control
界面语言    [中文][English]
密度       [宽松][平衡][紧凑]
```

Section rail panes:
- **外观** — theme/lang/density `SegmentedControl`s, all reading and writing `useLocaleStore`.
- **LLM 提供商** — model rows with provider chip + status dot, "添加模型" → form (provider preset → model_id → api_key → base_url).
- **模型路由** — per-task dropdown: `mentor_chat → claude-sonnet`, `content_analysis → ...`. Saves to `model_routes`.
- **数据源** — Bilibili login (QR scan; polls every 1.5s until the user confirms on phone), Whisper config (preset dropdown → URL/model/key fields).

All the real-world backend state (LLM provider config, Bilibili cookies, Whisper config) is preserved end-to-end.

## `/system`

`app/system/page.tsx`. The design-system reference page — see [Design system](./design-system.md#the-system-showcase). Internal use; the sidebar surfaces it under "设计系统".

## `/welcome`, `/diagnostic`, `/exercise`

Auxiliary surfaces:
- **`/welcome`** — onboarding stub.
- **`/diagnostic`** — 5-minute cold-start diagnostic (MCQ + short answer). Generated by `services/diagnostic.py` and graded via `TaskType.EVALUATION`.
- **`/exercise`** — section exercise runner. Pulls `getSectionExercises(sectionId)`; if `is_generating`, polls every 3s until done.

These pages still reference some legacy Tailwind palette utilities — they get bridged by `globals.css` in dark mode but should eventually be ported to design tokens.

## State

The frontend uses **Zustand** for global state. Stores live in `lib/stores.ts`:

| Store | Purpose |
|---|---|
| `useChatStore` | mentor conversation messages, streaming flag, conversation_id |
| `useSourcesStore` | imported sources list |
| `useTasksStore` | active import/regen tasks for polling |
| `useCoursesStore` | course list |

Plus `useLocaleStore` (`lib/i18n.ts`) for `lang / density / theme`.

Local state stays inside components (`useState`). Server cache (e.g. course detail by id) currently re-fetches on navigation — no react-query yet; one is on the wish list.

## LAN access

For phones/tablets on the same WiFi, `next.config.ts`:

```ts
allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.31.*", "192.168.*.*"],
```

Wildcards work segment-wise per Next 16's CSRF matcher (`node_modules/next/dist/server/app-render/csrf-protection.js`). Run the dev server with `npx next dev -H 0.0.0.0 -p 3000` and browse `http://<host-lan-ip>:3000` from any LAN client.

The proxy at `app/api/[...path]/route.ts` runs on the host, so `BACKEND_URL=http://localhost:8000` reaches the docker backend on the host.

## Tests

`vitest run` in `frontend/`. Notable:

- `__tests__/smoke.test.tsx` — dashboard / import / settings / learn / path / API client smoke
- `__tests__/learn-page-shell.test.tsx` — Learn shell columns, persistent mentor default, waypoints
- `__tests__/layout-and-dev-config.test.tsx` — tokens present in CSS, sidebar margins at different viewports
- `__tests__/sources-page.test.tsx` — filter + polling
- `__tests__/lesson-block-renderer.test.tsx` + `mermaid-*.test.tsx` — block-renderer specifics

The `next/font/google` and `next/navigation` mocks live in `src/test-setup.ts`.

## Adjacent docs

- [Design system](./design-system.md) — tokens, fonts, icons, dark-mode bridge
- [Architecture](./architecture.md) — frontend ↔ backend boundary
- [Concepts & graph](./concepts-and-graph.md) — what feeds the graph page
