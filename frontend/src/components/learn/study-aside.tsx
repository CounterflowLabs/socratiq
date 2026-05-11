"use client";

import { useEffect, useMemo } from "react";
import { clsx } from "clsx";

import {
  IcDoc,
  IcExternal,
  IcMentor,
  IcSources,
  IcVideo,
} from "@/components/icons";
import MentorPanel from "@/components/learn/mentor-panel";

import type { SourceSummary } from "@/lib/api";

export type AsidePanelId = "video" | "pdf" | "references" | "tutor";

interface StudyAsideProps {
  courseId: string | null;
  sectionId: string | null;
  onClose?: () => void;
  videoEmbed: { src: string } | null;
  pdfSource: SourceSummary | null;
  referenceSources: SourceSummary[];
  activePanel: AsidePanelId;
  onPanelChange: (panel: AsidePanelId) => void;
}

function getSourceHref(source: SourceSummary): string | null {
  if (source.url) return source.url;
  if (source.type === "pdf") return `/api/v1/sources/${source.id}/file`;
  return null;
}

export default function StudyAside({
  courseId,
  sectionId,
  videoEmbed,
  pdfSource,
  referenceSources,
  activePanel,
  onPanelChange,
}: StudyAsideProps) {
  const pdfHref = pdfSource ? getSourceHref(pdfSource) : null;
  const hasMaterials = Boolean(videoEmbed || pdfSource || referenceSources.length > 0);
  const panels = useMemo(() => {
    // Mentor first — the redesign promotes it from a hidden CTA to the default
    // panel (PRD §5.5). Other materials remain accessible via the tab strip.
    const next: AsidePanelId[] = ["tutor"];
    if (videoEmbed) next.push("video");
    if (pdfSource) next.push("pdf");
    if (referenceSources.length > 0) next.push("references");
    return next;
  }, [pdfSource, referenceSources, videoEmbed]);

  useEffect(() => {
    if (!panels.includes(activePanel)) onPanelChange(panels[0]);
  }, [activePanel, onPanelChange, panels]);

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        height: "calc(100vh - 110px)",
        maxHeight: "calc(100vh - 110px)",
      }}
    >
      {hasMaterials ? (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <PanelButton
            active={activePanel === "tutor"}
            onClick={() => onPanelChange("tutor")}
            icon={<IcMentor size={14} />}
            label="AI 导师"
          />
          {panels.includes("video") ? (
            <PanelButton
              active={activePanel === "video"}
              onClick={() => onPanelChange("video")}
              icon={<IcVideo size={14} />}
              label="原视频"
            />
          ) : null}
          {panels.includes("pdf") ? (
            <PanelButton
              active={activePanel === "pdf"}
              onClick={() => onPanelChange("pdf")}
              icon={<IcDoc size={14} />}
              label="原 PDF"
            />
          ) : null}
          {panels.includes("references") ? (
            <PanelButton
              active={activePanel === "references"}
              onClick={() => onPanelChange("references")}
              icon={<IcSources size={14} />}
              label="参考资料"
            />
          ) : null}
        </div>
      ) : null}

      {activePanel === "tutor" ? (
        <div style={{ flex: 1, minHeight: 0 }}>
          <MentorPanel
            variant="inline"
            courseId={courseId}
            sectionId={sectionId}
            fillHeight={false}
          />
        </div>
      ) : (
        <section
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-lg)",
            padding: 14,
            flex: 1,
            minHeight: 0,
            overflowY: "auto",
          }}
        >
          {activePanel === "video" && videoEmbed ? (
            <>
              <h3 className="serif" style={{ fontSize: 14, fontWeight: 500, margin: "0 0 10px" }}>
                原视频
              </h3>
              <div
                style={{
                  background: "#0c0a08",
                  borderRadius: "var(--r)",
                  overflow: "hidden",
                }}
              >
                <div style={{ position: "relative", width: "100%", paddingBottom: "56.25%" }}>
                  <iframe
                    title="课程原视频"
                    src={videoEmbed.src}
                    allowFullScreen
                    sandbox="allow-scripts allow-same-origin allow-popups"
                    style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: 0 }}
                  />
                </div>
              </div>
            </>
          ) : null}

          {activePanel === "pdf" && pdfSource ? (
            <>
              <h3 className="serif" style={{ fontSize: 14, fontWeight: 500, margin: "0 0 10px" }}>
                原 PDF
              </h3>
              {pdfHref ? (
                <a
                  href={pdfHref}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-outline"
                  style={{ justifyContent: "space-between", width: "100%" }}
                >
                  <span>打开原 PDF</span>
                  <IcExternal size={14} />
                </a>
              ) : (
                <p style={{ fontSize: 12, color: "var(--ink-3)" }}>当前 PDF 暂不可直接打开。</p>
              )}
            </>
          ) : null}

          {activePanel === "references" ? (
            <>
              <h3 className="serif" style={{ fontSize: 14, fontWeight: 500, margin: "0 0 10px" }}>
                参考资料
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {referenceSources.map((source) => {
                  const href = getSourceHref(source);
                  if (!href) {
                    return (
                      <div
                        key={source.id}
                        className="card-quiet"
                        style={{
                          padding: 12,
                          fontSize: 12,
                          color: "var(--ink-3)",
                          borderStyle: "dashed",
                        }}
                      >
                        <div>{source.type === "pdf" ? "PDF 资料" : "参考资料"}</div>
                        <div style={{ marginTop: 4, fontSize: 11, color: "var(--ink-4)" }}>
                          当前资料暂不可直接打开。
                        </div>
                      </div>
                    );
                  }
                  return (
                    <a
                      key={source.id}
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-outline"
                      style={{ justifyContent: "space-between", width: "100%" }}
                    >
                      <span>{source.type === "pdf" ? "PDF 资料" : "参考链接"}</span>
                      <IcExternal size={14} />
                    </a>
                  );
                })}
              </div>
            </>
          ) : null}
        </section>
      )}
    </aside>
  );
}

function PanelButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx("btn", active ? "btn-primary" : "btn-outline", "btn-sm")}
      style={{ justifyContent: "center", gap: 6 }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
