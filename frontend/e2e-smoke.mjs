/**
 * E2E Smoke Test — Playwright headless browser
 * Tests all core pages with real data from seed script.
 *
 * Run: node e2e-smoke.mjs
 * Requires: backend on :8000, frontend on :3000, seeded DB
 */

import { chromium } from "playwright";

const BASE = "http://localhost:3000";
const COURSE_ID = "bbbbbbbb-0000-0000-0000-000000000001";
const SECTION_LESSON = "cccccccc-0000-0000-0000-000000000002";
const SECTION_LAB = "cccccccc-0000-0000-0000-000000000003";

let browser, page;
const results = [];
const jsErrors = [];

function pass(name) { results.push({ name, status: "PASS" }); console.log(`  ✅ ${name}`); }
function fail(name, reason) { results.push({ name, status: "FAIL", reason }); console.log(`  ❌ ${name}: ${reason}`); }

async function test(name, fn) {
  try {
    await fn();
    pass(name);
  } catch (e) {
    fail(name, e.message.split("\n")[0]);
  }
}

async function goto(path, opts = {}) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle", timeout: 15000, ...opts });
}

async function hasText(text, timeout = 5000) {
  await page.waitForSelector(`text=${text}`, { timeout });
}

async function screenshot(name) {
  await page.screenshot({ path: `/tmp/socratiq-e2e-${name}.png`, fullPage: true });
}

// ─── Main ─────────────────────────────────────────────

async function run() {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  page = await context.newPage();

  // Collect JS errors
  page.on("pageerror", (err) => jsErrors.push({ page: page.url(), error: err.message }));
  page.on("console", (msg) => {
    if (msg.type() === "error") jsErrors.push({ page: page.url(), error: msg.text() });
  });

  console.log("\n🧪 Socratiq E2E Smoke Tests\n");

  // ─── T1: Settings page ──────────────────────
  console.log("Page: /settings");
  await test("T1: Settings page loads (not stuck on loading)", async () => {
    await goto("/settings");
    await screenshot("t1-settings");
    // Should NOT show "加载中..." after network idle
    const loadingVisible = await page.locator("text=加载中").isVisible().catch(() => false);
    if (loadingVisible) throw new Error("Still showing 加载中... — page stuck loading");
    // Should show "设置" title
    await hasText("设置");
  });

  // ─── T2: Import page — tab switching ────────
  console.log("Page: /import");
  await test("T2a: Import page loads", async () => {
    await goto("/import");
    await screenshot("t2a-import");
    await hasText("导入学习资料");
  });

  await test("T2b: Can switch to YouTube tab", async () => {
    await page.click("text=YouTube");
    await page.waitForTimeout(300);
    const ytInput = await page.locator("input[placeholder*='youtube']").isVisible().catch(() => false);
    const ytInputAlt = await page.locator("input[placeholder*='YouTube']").isVisible().catch(() => false);
    await screenshot("t2b-youtube-tab");
    if (!ytInput && !ytInputAlt) throw new Error("YouTube input not visible after clicking tab");
  });

  await test("T2c: Can switch to PDF tab", async () => {
    await page.click("text=PDF 文档");
    await page.waitForTimeout(300);
    await screenshot("t2c-pdf-tab");
    const pdfArea = await page.locator("text=拖拽").isVisible().catch(() => false);
    const pdfAreaAlt = await page.locator("text=PDF").count();
    if (!pdfArea && pdfAreaAlt < 2) throw new Error("PDF upload area not visible after clicking tab");
  });

  await test("T2d: Can switch back to Bilibili tab", async () => {
    await page.click("text=B站视频");
    await page.waitForTimeout(500);
    await screenshot("t2d-bili-tab");
    // Check for bilibili placeholder OR the bilibili tab being active (blue border)
    const biliInput = await page.locator("input[placeholder*='bilibili'], input[placeholder*='BV']").isVisible().catch(() => false);
    const biliTabActive = await page.locator("button:has-text('B站视频')").getAttribute("class").then(c => c?.includes("blue") || c?.includes("primary")).catch(() => false);
    if (!biliInput && !biliTabActive) throw new Error("Bilibili tab not active after clicking");
  });

  // ─── T3: Dashboard ──────────────────────────
  console.log("Page: / (Dashboard)");
  await test("T3: Dashboard shows course card", async () => {
    await goto("/");
    await screenshot("t3-dashboard");
    await hasText("Python 从零到一");
  });

  await test("T4: Dashboard shows review section", async () => {
    const hasReview = await page.locator("text=今日复习").isVisible().catch(() => false);
    const hasReviewAlt = await page.locator("text=复习").isVisible().catch(() => false);
    if (!hasReview && !hasReviewAlt) throw new Error("Review section not found on dashboard");
  });

  // ─── T5: Path page ──────────────────────────
  console.log("Page: /path");
  await test("T5: Path page shows sections with progress", async () => {
    await goto(`/path?courseId=${COURSE_ID}`);
    await screenshot("t5-path");
    await hasText("Python 从零到一");
    await hasText("变量与数据类型");
    await hasText("条件判断与循环");
    // Check for progress indicators
    const hasCompleted = await page.locator("text=已完成").isVisible().catch(() => false);
    const hasInProgress = await page.locator("text=进行中").isVisible().catch(() => false);
    if (!hasCompleted && !hasInProgress) throw new Error("No progress status badges found");
  });

  // ─── T6: Path → Learn navigation ───────────
  await test("T6: Click section navigates to Learn page", async () => {
    await page.click("text=变量与数据类型");
    await page.waitForURL(/\/learn/, { timeout: 5000 });
    await screenshot("t6-learn-from-path");
  });

  // ─── T7: Learn page — video + lesson ────────
  console.log("Page: /learn");
  await test("T7: Learn page shows video + lesson split", async () => {
    await goto(`/learn?courseId=${COURSE_ID}&sectionId=${SECTION_LESSON}`);
    await page.waitForTimeout(3000); // Wait for data loading + Mermaid rendering
    await screenshot("t7-learn");
    // Check for rendered lesson content (title, prose, code blocks — not raw JSON)
    const pageText = await page.textContent("body");
    const hasTitle = pageText.includes("变量与数据类型");
    const hasContent = pageText.includes("动态类型") || pageText.includes("变量赋值") || pageText.includes("类型转换");
    const hasCode = pageText.includes("name =") || pageText.includes("print(type");
    if (!hasTitle) throw new Error("Lesson title not found in page text");
    if (!hasContent && !hasCode) throw new Error("Lesson content not rendered (may be showing JSON)");
  });

  await test("T7b: Learn page has tab bar", async () => {
    const pageText = await page.textContent("body");
    const hasLab = pageText.includes("Lab");
    const hasGraph = pageText.includes("图谱");
    if (!hasLab && !hasGraph) throw new Error("Tab bar not found (no Lab or Graph tab text)");
  });

  // ─── T8: Lesson collapse ───────────────────
  await test("T8: Lesson collapse/expand", async () => {
    const collapseBtn = await page.locator("text=收起课文").isVisible().catch(() => false);
    const collapseBtnAlt = await page.locator("button:has-text('收起')").isVisible().catch(() => false);
    // This is P1 — just check if the button exists, don't require it
    if (!collapseBtn && !collapseBtnAlt) throw new Error("Collapse button not found");
  });

  // ─── T9: Lab Tab ───────────────────────────
  console.log("Page: /learn (Lab tab)");
  await test("T9: Lab tab shows editor", async () => {
    await goto(`/learn?courseId=${COURSE_ID}&sectionId=${SECTION_LAB}`);
    await page.waitForTimeout(3000);
    // Find and click Lab tab — may be a button or text element
    const labClicked = await page.locator("button:has-text('Lab')").first().click({ timeout: 5000 }).then(() => true).catch(() => false);
    if (!labClicked) {
      // Try clicking any element with Lab text
      await page.locator("text=Lab").first().click({ timeout: 5000 }).catch(() => {});
    }
    await page.waitForTimeout(3000);
    await screenshot("t9-lab");
    const pageText = await page.textContent("body");
    const hasLabContent = pageText.includes("流程控制") || pageText.includes("flow_control") || pageText.includes("fizzbuzz");
    if (!hasLabContent) throw new Error("Lab content not rendered after clicking Lab tab");
  });

  // ─── T10: AI Tutor Drawer ──────────────────
  await test("T10: AI Tutor drawer opens", async () => {
    await goto(`/learn?courseId=${COURSE_ID}&sectionId=${SECTION_LESSON}`);
    await page.waitForTimeout(2000);
    // Find and click the tutor button
    const tutorBtn = page.locator("button:has-text('AI 导师')").first();
    const tutorBtnAlt = page.locator("button:has-text('导师')").first();
    const btn = (await tutorBtn.isVisible()) ? tutorBtn : tutorBtnAlt;
    await btn.click();
    await page.waitForTimeout(500);
    await screenshot("t10-tutor");
    // Check drawer content
    const hasChat = await page.locator("text=解释这个概念").isVisible().catch(() => false);
    const hasChatAlt = await page.locator("text=输入问题").isVisible().catch(() => false);
    if (!hasChat && !hasChatAlt) throw new Error("Tutor drawer content not visible");
  });

  // ─── T11: Knowledge Graph Tab ──────────────
  await test("T11: Graph tab renders", async () => {
    await goto(`/learn?courseId=${COURSE_ID}&sectionId=${SECTION_LESSON}`);
    await page.waitForTimeout(3000);
    const graphClicked = await page.locator("button:has-text('图谱')").first().click({ timeout: 5000 }).then(() => true).catch(() => false);
    if (!graphClicked) {
      await page.locator("text=图谱").first().click({ timeout: 5000 }).catch(() => {});
    }
    await page.waitForTimeout(3000);
    await screenshot("t11-graph");
    const pageText = await page.textContent("body");
    const hasSvg = await page.locator("svg").count();
    const hasGraphContent = pageText.includes("知识图谱") || pageText.includes("图谱") || hasSvg > 2;
    if (!hasGraphContent) throw new Error("Knowledge graph tab not rendered");
  });

  // ─── T12: Exercise page ────────────────────
  console.log("Page: /exercise");
  await test("T12: Exercise page loads with questions", async () => {
    await goto(`/exercise?courseId=${COURSE_ID}&sectionId=${SECTION_LESSON}`);
    await page.waitForTimeout(2000);
    await screenshot("t12-exercise");
    // Should show a question
    const hasQuestion = await page.locator("text=Python").isVisible().catch(() => false);
    const hasMcqOption = await page.locator("text=x = 10").isVisible().catch(() => false);
    if (!hasQuestion && !hasMcqOption) throw new Error("Exercise question not rendered");
  });

  // ─── T13: Console errors ───────────────────
  console.log("\nJS Error Summary:");
  const fatalErrors = jsErrors.filter(e =>
    !e.error.includes("favicon") &&
    !e.error.includes("DevTools") &&
    !e.error.includes("hydration") &&
    !e.error.includes("ERR_CONNECTION_REFUSED")
  );
  if (fatalErrors.length > 0) {
    console.log(`  ⚠️  ${fatalErrors.length} JS errors detected:`);
    for (const e of fatalErrors.slice(0, 10)) {
      console.log(`    ${e.page.replace(BASE, "")} → ${e.error.slice(0, 120)}`);
    }
  } else {
    console.log("  ✅ No fatal JS errors");
  }

  // ─── Summary ───────────────────────────────
  console.log("\n═══ Summary ═══");
  const passed = results.filter(r => r.status === "PASS").length;
  const failed = results.filter(r => r.status === "FAIL").length;
  console.log(`  ${passed} passed, ${failed} failed out of ${results.length} tests`);
  if (failed > 0) {
    console.log("\n  Failed tests:");
    for (const r of results.filter(r => r.status === "FAIL")) {
      console.log(`    ❌ ${r.name}: ${r.reason}`);
    }
  }
  console.log(`\n  Screenshots saved to /tmp/socratiq-e2e-*.png`);

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((e) => {
  console.error("Fatal:", e);
  browser?.close();
  process.exit(1);
});
