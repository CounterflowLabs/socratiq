"use client";

import { Suspense } from "react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";

import {
  IcArrowLeft,
  IcArrowRight,
  IcCheck,
  IcCheckCircle,
  IcChevronRight,
  IcClock,
  IcExercise,
  IcLab,
  IcLesson,
  IcLoader,
  IcMentor,
  IcSparkle,
  SourceIcon,
} from "@/components/icons";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Progress } from "@/components/ui/progress-bar";
import { useT } from "@/lib/i18n";
import RegenerateDrawer from "@/components/learn/regenerate-drawer";
import {
  clearCourseRegeneration,
  getCourse,
  getCourseProgress,
  getRegenerationStatus,
  regenerateCourse,
  type CourseDetailResponse,
  type RegenerationStatus,
  type SectionResponse,
} from "@/lib/api";

const STAGE_LABELS_ZH: Record<string, string> = {
  analyzing: "分析内容",
  planning: "规划教学资产",
  generating_lessons: "生成课文",
  generating_labs: "生成 Lab",
  assembling: "组装课程",
  source_done: "资料处理完成",
};

const STAGE_LABELS_EN: Record<string, string> = {
  analyzing: "Analyzing",
  planning: "Planning assets",
  generating_lessons: "Generating lessons",
  generating_labs: "Generating labs",
  assembling: "Assembling",
  source_done: "Source ready",
};

const STAGE_PERCENT_RANGES: Record<string, [number, number]> = {
  pending: [0, 5],
  analyzing: [5, 25],
  generating_lessons: [25, 70],
  generating_labs: [70, 90],
  assembling: [90, 100],
};

function computeRegenPercent(status: RegenerationStatus): number {
  if (status.status === "success") return 100;
  if (status.status === "failure") return 0;
  const stage = status.stage ?? "pending";
  const [base, ceiling] = STAGE_PERCENT_RANGES[stage] ?? [0, 100];
  if (typeof status.current === "number" && typeof status.total === "number" && status.total > 0) {
    return Math.round(base + (status.current / status.total) * (ceiling - base));
  }
  return base;
}

interface SectionProgress {
  section_id: string;
  lesson_read: boolean;
  lab_completed: boolean;
  exercise_best_score: number | null;
  status: string;
}

interface UnitGroup {
  title: string;
  sections: SectionResponse[];
}

/** Section content can carry an explicit `unit` heading. Group consecutive
 *  sections that share the same unit; otherwise fall back to a single bucket. */
function groupSections(sections: SectionResponse[], lang: "zh" | "en"): UnitGroup[] {
  if (sections.length === 0) return [];
  const fallback = lang === "zh" ? "全部课文" : "All lessons";
  const groups: UnitGroup[] = [];
  let current: UnitGroup | null = null;

  for (const section of sections) {
    const content = section.content as Record<string, unknown> | undefined;
    const unitName =
      (typeof content?.unit === "string" ? content.unit : null) ??
      (typeof content?.module === "string" ? content.module : null) ??
      fallback;
    if (!current || current.title !== unitName) {
      current = { title: unitName, sections: [] };
      groups.push(current);
    }
    current.sections.push(section);
  }
  return groups;
}

function PathContent() {
  const { t, lang } = useT();
  const searchParams = useSearchParams();
  const courseId = searchParams.get("courseId");
  const router = useRouter();

  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [progressMap, setProgressMap] = useState<Map<string, SectionProgress>>(new Map());
  const [loading, setLoading] = useState(!!courseId);
  const [error, setError] = useState<string | null>(courseId ? null : (lang === "zh" ? "未提供课程 ID" : "No course id"));

  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [regenerateBusy, setRegenerateBusy] = useState(false);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);
  const [regenTaskId, setRegenTaskId] = useState<string | null>(null);
  const [regenStatus, setRegenStatus] = useState<RegenerationStatus | null>(null);

  useEffect(() => {
    if (!courseId) return;
    Promise.all([getCourse(courseId), getCourseProgress(courseId)])
      .then(([courseData, progressData]) => {
        setCourse(courseData);
        const map = new Map<string, SectionProgress>();
        for (const p of progressData) map.set(p.section_id, p);
        setProgressMap(map);
      })
      .catch((e) => setError(e instanceof Error ? e.message : (lang === "zh" ? "加载课程失败" : "Failed to load course")))
      .finally(() => setLoading(false));
  }, [courseId, lang]);

  useEffect(() => {
    const persisted = course?.active_regeneration_task_id;
    if (persisted && persisted !== regenTaskId) {
      setRegenTaskId(persisted);
      setRegenStatus({ status: "pending" });
    }
  }, [course?.active_regeneration_task_id, regenTaskId]);

  useEffect(() => {
    if (!regenTaskId) return;
    if (regenStatus?.status === "success" || regenStatus?.status === "failure") return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const update = await getRegenerationStatus(regenTaskId);
        if (cancelled) return;
        setRegenStatus(update);
        if (update.status !== "success" && update.status !== "failure") {
          setTimeout(tick, 3000);
        }
      } catch (err) {
        if (cancelled) return;
        setRegenStatus({
          status: "failure",
          error: err instanceof Error ? err.message : "Polling failed",
        });
      }
    };
    void tick();
    return () => {
      cancelled = true;
    };
  }, [regenTaskId, regenStatus?.status]);

  const sections = useMemo(
    () =>
      [...(course?.sections ?? [])].sort(
        (a, b) => (a.order_index ?? 0) - (b.order_index ?? 0),
      ),
    [course?.sections],
  );

  const groups = useMemo(() => groupSections(sections, lang), [sections, lang]);
  const total = sections.length;
  const completed = sections.filter((section) => {
    const p = progressMap.get(section.id);
    return Boolean(p?.lesson_read || (p?.exercise_best_score ?? 0) > 0 || p?.lab_completed);
  }).length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const currentSection = useMemo(() => {
    return (
      sections.find((section) => {
        const p = progressMap.get(section.id);
        return p && !p.lesson_read && !(p.exercise_best_score ?? 0) && !p.lab_completed;
      }) ??
      sections.find((section) => !progressMap.has(section.id)) ??
      sections[0] ??
      null
    );
  }, [progressMap, sections]);

  const versionIndex = course?.version_index ?? 1;
  const parentHref = course?.parent_id ? `/path?courseId=${course.parent_id}` : null;

  const banner: { state: "running" | "ready" | "failed"; status: RegenerationStatus } | null =
    regenStatus
      ? {
          state:
            regenStatus.status === "success"
              ? "ready"
              : regenStatus.status === "failure"
                ? "failed"
                : "running",
          status: regenStatus,
        }
      : null;

  function dismissBanner() {
    if (courseId) void clearCourseRegeneration(courseId).catch(() => {});
    setRegenStatus(null);
    setRegenTaskId(null);
    setCourse((prev) =>
      prev ? { ...prev, active_regeneration_task_id: null } : prev,
    );
  }

  function openNewVersion() {
    const newCourseId = regenStatus?.course_id;
    if (!newCourseId) return;
    if (courseId) void clearCourseRegeneration(courseId).catch(() => {});
    setRegenStatus(null);
    setRegenTaskId(null);
    setCourse((prev) =>
      prev ? { ...prev, active_regeneration_task_id: null } : prev,
    );
    router.push(`/path?courseId=${newCourseId}`);
  }

  if (loading) {
    return (
      <div
        style={{
          minHeight: "60vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--ink-3)",
          gap: 8,
        }}
      >
        <IcLoader size={16} className="spin" />
        <span>{t("common.loading")}</span>
      </div>
    );
  }

  if (error || !course) {
    return (
      <div
        style={{
          minHeight: "60vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--error)",
          fontSize: 13,
        }}
      >
        {error ?? (lang === "zh" ? "课程未找到" : "Course not found")}
      </div>
    );
  }

  return (
    <div style={{ padding: "24px 40px 80px", maxWidth: 1280, margin: "0 auto", width: "100%" }}>
      <Link href="/" className="btn btn-ghost btn-sm" style={{ marginLeft: -10, marginBottom: 16, color: "var(--ink-3)" }}>
        <IcArrowLeft size={12} />
        <span>{t("common.back")}</span>
      </Link>

      <header
        style={{
          marginBottom: "var(--gap-xl)",
          display: "grid",
          gridTemplateColumns: "1fr 280px",
          gap: 32,
          alignItems: "flex-end",
        }}
      >
        <div>
          <Eyebrow>
            {t("path.eyebrow")} · {lang === "zh" ? `共 ${total} 节` : `${total} lessons`}
          </Eyebrow>
          <h1
            className="display"
            style={{
              fontSize: 44,
              margin: "8px 0 12px",
              fontWeight: 400,
              letterSpacing: "-0.02em",
            }}
          >
            {course.title}
          </h1>
          {/* Source · concept count · est. duration — per PRD §5.4. */}
          {(() => {
            const sources = course.sources ?? [];
            const primarySource = sources[0];
            const conceptCount = sections.reduce((acc, section) => {
              const content = section.content as Record<string, unknown> | undefined;
              const keyTerms = Array.isArray(content?.key_terms) ? content!.key_terms.length : 0;
              return acc + keyTerms;
            }, 0);
            const estMinutes = sections.reduce(
              (acc, s) => acc + Math.max(5, Math.round(s.difficulty * 4)),
              0,
            );
            const estLabel =
              estMinutes >= 60
                ? `~${(estMinutes / 60).toFixed(1)}h`
                : `~${estMinutes}m`;
            return (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  color: "var(--ink-3)",
                  fontSize: 13,
                  marginBottom: 10,
                }}
              >
                {primarySource ? (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <SourceIcon type={primarySource.type} size={14} />
                    <span>{primarySource.type.toUpperCase()}</span>
                  </span>
                ) : null}
                {conceptCount > 0 ? (
                  <>
                    <span>·</span>
                    <span>{conceptCount} {t("common.concepts")}</span>
                  </>
                ) : null}
                <span>·</span>
                <span className="mono">{estLabel}</span>
              </div>
            );
          })()}
          {course.description ? (
            <p
              style={{
                margin: 0,
                fontSize: 15,
                color: "var(--ink-2)",
                lineHeight: 1.6,
                maxWidth: 640,
              }}
            >
              {course.description}
            </p>
          ) : null}
          {versionIndex > 1 ? (
            <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
              <span className="chip chip-accent">
                {lang === "zh" ? `第 ${versionIndex} 版` : `v${versionIndex}`}
              </span>
              {parentHref ? (
                <Link
                  href={parentHref}
                  style={{ fontSize: 12, color: "var(--ink-3)", textDecoration: "underline" }}
                >
                  {lang === "zh" ? "查看上一版" : "View previous version"}
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span
              className="mono num"
              style={{ fontSize: 32, color: "var(--ink)", fontWeight: 500, fontFamily: "var(--serif)" }}
            >
              {pct}
            </span>
            <span className="mono" style={{ fontSize: 14, color: "var(--ink-3)" }}>%</span>
          </div>
          <Progress value={pct} color="var(--accent)" height={3} />
          <div className="mono num" style={{ fontSize: 12, color: "var(--ink-3)" }}>
            {completed} / {total} {t("common.lessons")}
          </div>
          <button
            type="button"
            onClick={() => setRegenerateOpen(true)}
            disabled={banner?.state === "running"}
            className="btn btn-outline btn-sm"
            style={{ marginTop: 8 }}
          >
            <IcSparkle size={12} />
            <span>{t("path.regenerate")}</span>
          </button>
        </div>
      </header>

      {banner ? (
        <div
          className="card-quiet"
          style={{
            marginBottom: 24,
            padding: 14,
            borderColor:
              banner.state === "running"
                ? "rgba(201, 100, 66, 0.4)"
                : banner.state === "ready"
                  ? "rgba(107, 125, 91, 0.4)"
                  : "rgba(179, 66, 47, 0.4)",
            background:
              banner.state === "running"
                ? "var(--accent-soft)"
                : banner.state === "ready"
                  ? "var(--sage-soft)"
                  : "var(--error-soft)",
            color:
              banner.state === "running"
                ? "var(--accent-ink)"
                : banner.state === "ready"
                  ? "var(--sage-ink)"
                  : "var(--error)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
              {banner.state === "running" ? (
                <IcLoader size={14} className="spin" />
              ) : banner.state === "ready" ? (
                <IcCheckCircle size={14} />
              ) : null}
              <span>
                {banner.state === "running" ? (
                  <>
                    {lang === "zh" ? "重新生成中" : "Regenerating"} ·{" "}
                    {(lang === "zh" ? STAGE_LABELS_ZH : STAGE_LABELS_EN)[banner.status.stage ?? ""] ??
                      banner.status.stage ??
                      (lang === "zh" ? "进行中" : "running")}
                    {typeof banner.status.current === "number" &&
                    typeof banner.status.total === "number" &&
                    banner.status.total > 1
                      ? ` (${banner.status.current}/${banner.status.total})`
                      : ""}
                    {" · "}
                    {computeRegenPercent(banner.status)}%
                  </>
                ) : banner.state === "ready" ? (
                  lang === "zh"
                    ? "新版本已生成完毕。"
                    : "New version is ready."
                ) : (
                  banner.status.error ?? (lang === "zh" ? "重新生成失败。" : "Regeneration failed.")
                )}
              </span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {banner.state === "ready" && banner.status.course_id ? (
                <button type="button" onClick={openNewVersion} className="btn btn-accent btn-sm">
                  {lang === "zh" ? "打开新版本" : "Open new version"}
                </button>
              ) : null}
              {banner.state !== "running" ? (
                <button type="button" onClick={dismissBanner} className="btn btn-ghost btn-sm">
                  {t("common.close")}
                </button>
              ) : null}
            </div>
          </div>
          {banner.state === "running" ? (
            <div style={{ marginTop: 10 }}>
              <Progress value={computeRegenPercent(banner.status)} color="var(--accent)" height={2} />
            </div>
          ) : null}
        </div>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 280px",
          gap: 40,
          alignItems: "flex-start",
        }}
      >
        <div>
          {groups.map((group, ui) => (
            <UnitBlock
              key={`${group.title}-${ui}`}
              unit={group}
              index={ui}
              total={groups.length}
              progressMap={progressMap}
              currentId={currentSection?.id ?? null}
              courseId={course.id}
            />
          ))}
        </div>

        <aside style={{ position: "sticky", top: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          {currentSection ? (
            <div
              className="card"
              style={{ background: "var(--accent-soft)", border: "1px solid transparent" }}
            >
              <Eyebrow color="var(--accent-ink)">{t("path.youAreHere")}</Eyebrow>
              <div
                className="serif"
                style={{
                  fontSize: 18,
                  fontWeight: 500,
                  margin: "6px 0 12px",
                  color: "var(--accent-ink)",
                }}
              >
                {currentSection.title}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  style={{ justifyContent: "flex-start" }}
                  onClick={() =>
                    router.push(`/learn?courseId=${course.id}&sectionId=${currentSection.id}`)
                  }
                >
                  <IcLesson size={14} />
                  <span>{t("path.readLesson")}</span>
                  <IcArrowRight size={12} style={{ marginLeft: "auto" }} />
                </button>
                <button
                  type="button"
                  className="btn btn-outline"
                  style={{ justifyContent: "flex-start" }}
                  onClick={() => router.push(`/exercise?sectionId=${currentSection.id}`)}
                >
                  <IcExercise size={14} />
                  <span>{t("path.doExercise")}</span>
                </button>
                <button
                  type="button"
                  className="btn btn-outline"
                  style={{ justifyContent: "flex-start" }}
                >
                  <IcLab size={14} />
                  <span>{t("path.runLab")}</span>
                </button>
                <button
                  type="button"
                  className="btn btn-outline"
                  style={{ justifyContent: "flex-start" }}
                  onClick={() =>
                    router.push(`/learn?courseId=${course.id}&sectionId=${currentSection.id}&mentor=open`)
                  }
                >
                  <IcMentor size={14} />
                  <span>{t("path.mentorChat")}</span>
                </button>
              </div>
            </div>
          ) : null}

          <div className="card-quiet">
            <Eyebrow>{t("path.thisWeek")}</Eyebrow>
            <div style={{ display: "flex", gap: 4, marginTop: 12, alignItems: "flex-end" }}>
              {/* Until the back-end exposes a real session log we render a
                  shaped placeholder so the rail keeps its rhythm. */}
              {[2, 5, 1, 4, 6, 3, 0].map((v, i) => (
                <div key={i} style={{ flex: 1 }}>
                  <div
                    style={{
                      height: 4 + v * 8,
                      background: i === 6 ? "var(--accent)" : "var(--ink-4)",
                      borderRadius: 2,
                      opacity: i === 6 ? 1 : 0.4 + i * 0.08,
                    }}
                  />
                  <div
                    className="mono"
                    style={{ fontSize: 9, textAlign: "center", color: "var(--ink-4)", marginTop: 4 }}
                  >
                    {(lang === "zh"
                      ? ["一", "二", "三", "四", "五", "六", "日"]
                      : ["M", "T", "W", "T", "F", "S", "S"])[i]}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 12, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.5 }}>
              <span className="num mono" style={{ color: "var(--ink)", fontWeight: 500 }}>
                {completed}
              </span>{" "}
              {lang === "zh" ? "节课，已完成" : "lessons completed"}
            </div>
          </div>
        </aside>
      </div>

      <RegenerateDrawer
        open={regenerateOpen}
        initialDirective={course.regeneration_directive ?? ""}
        pending={regenerateBusy}
        errorMessage={regenerateError}
        onClose={() => {
          if (!regenerateBusy) {
            setRegenerateOpen(false);
            setRegenerateError(null);
          }
        }}
        onSubmit={async (directive) => {
          if (!courseId) return;
          setRegenerateBusy(true);
          setRegenerateError(null);
          try {
            const res = await regenerateCourse(courseId, directive || undefined);
            setRegenTaskId(res.task_id);
            setRegenStatus({ status: "pending" });
            setRegenerateOpen(false);
          } catch (err) {
            setRegenerateError(
              err instanceof Error ? err.message : lang === "zh" ? "无法启动重新生成" : "Could not start regeneration",
            );
          } finally {
            setRegenerateBusy(false);
          }
        }}
      />
    </div>
  );
}

function UnitBlock({
  unit,
  index,
  total,
  progressMap,
  currentId,
  courseId,
}: {
  unit: UnitGroup;
  index: number;
  total: number;
  progressMap: Map<string, SectionProgress>;
  currentId: string | null;
  courseId: string;
}) {
  return (
    <section style={{ marginBottom: "var(--gap-xl)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 16 }}>
        <span
          className="mono num"
          style={{ fontSize: 13, color: "var(--ink-4)", fontWeight: 500 }}
        >
          {String(index + 1).padStart(2, "0")}
          <span style={{ color: "var(--ink-4)", opacity: 0.5 }}>
            {" "}
            / {String(total).padStart(2, "0")}
          </span>
        </span>
        <h2
          className="serif"
          style={{ fontSize: 22, margin: 0, fontWeight: 500, color: "var(--ink)" }}
        >
          {unit.title}
        </h2>
        <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {unit.sections.map((section, idx) => (
          <LessonRow
            key={section.id}
            section={section}
            index={idx}
            progress={progressMap.get(section.id)}
            isCurrent={section.id === currentId}
            courseId={courseId}
          />
        ))}
      </div>
    </section>
  );
}

function LessonRow({
  section,
  index,
  progress,
  isCurrent,
  courseId,
}: {
  section: SectionResponse;
  index: number;
  progress: SectionProgress | undefined;
  isCurrent: boolean;
  courseId: string;
}) {
  const router = useRouter();
  const { t, lang } = useT();
  const isDone = Boolean(progress?.lesson_read || (progress?.exercise_best_score ?? 0) > 0 || progress?.lab_completed);
  const status = isDone ? "done" : isCurrent ? "current" : "next";
  const content = section.content as Record<string, unknown> | undefined;
  const hasCode = Boolean(content?.has_code);
  const hasExercise = Boolean(content?.has_exercise) || progress?.exercise_best_score != null;

  function statusDot() {
    if (status === "done") {
      return (
        <span
          style={{
            width: 18,
            height: 18,
            borderRadius: "50%",
            background: "var(--sage)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
          }}
        >
          <IcCheck size={11} />
        </span>
      );
    }
    if (status === "current") {
      return (
        <span
          style={{
            width: 18,
            height: 18,
            borderRadius: "50%",
            background: "var(--accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
          }}
        >
          <IcArrowRight size={11} />
        </span>
      );
    }
    return (
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          border: "1.5px solid var(--border-strong)",
          background: "var(--surface)",
        }}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => router.push(`/learn?courseId=${courseId}&sectionId=${section.id}`)}
      style={{
        display: "grid",
        gridTemplateColumns: "32px 1fr auto",
        alignItems: "center",
        gap: 12,
        padding: "14px 4px",
        background: "transparent",
        border: "none",
        borderBottom: "1px solid var(--border)",
        textAlign: "left",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
        transition: "background var(--duration-fast) ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--surface-2)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
    >
      <div style={{ display: "flex", justifyContent: "center" }}>{statusDot()}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span
            className="mono num"
            style={{ fontSize: 11, color: "var(--ink-4)" }}
          >
            L{String(index + 1).padStart(2, "0")}
          </span>
          <span
            style={{
              fontSize: 15,
              fontFamily: "var(--serif)",
              color: "var(--ink)",
              fontWeight: status === "current" ? 500 : 400,
            }}
          >
            {section.title}
          </span>
          {status === "current" ? (
            <span className="chip chip-accent" style={{ marginLeft: 8 }}>
              {lang === "zh" ? "当前" : "now"}
            </span>
          ) : null}
        </div>
        <div
          style={{
            marginTop: 4,
            display: "flex",
            gap: 10,
            fontSize: 11,
            color: "var(--ink-3)",
            alignItems: "center",
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <IcClock size={11} />
            <span className="mono num">~{Math.max(5, Math.round(section.difficulty * 4))}m</span>
          </span>
          {hasExercise ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <IcExercise size={11} />
              <span>{t("common.doExercise")}</span>
            </span>
          ) : null}
          {hasCode ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <IcLab size={11} />
              <span>lab</span>
            </span>
          ) : null}
          {progress?.exercise_best_score != null ? (
            <span style={{ color: "var(--sage)", fontWeight: 500 }}>
              {Math.round(progress.exercise_best_score)}%
            </span>
          ) : null}
        </div>
      </div>
      <IcChevronRight size={14} style={{ color: "var(--ink-4)" }} />
    </button>
  );
}

export default function PathPage() {
  return (
    <Suspense
      fallback={
        <div
          style={{
            minHeight: "60vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--ink-3)",
            gap: 8,
          }}
        >
          <IcLoader size={16} className="spin" />
          <span>加载中…</span>
        </div>
      }
    >
      <PathContent />
    </Suspense>
  );
}
