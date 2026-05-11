/**
 * Custom Socratiq icon set.
 * 1.5px stroke, rounded caps, 24×24 grid, geometric.
 * Stroke uses currentColor so icons inherit text color.
 *
 * Replaces the lucide-react import that the legacy build used —
 * Lucide's letterforms gave every screen a slightly different metaphor
 * for the same idea (Mentor / Concept / Lesson). This set is purpose-built.
 */

import type { SVGProps } from "react";

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "stroke" | "width" | "height"> {
  size?: number;
  stroke?: number;
}

function Base({
  size = 18,
  stroke = 1.5,
  className,
  children,
  ...rest
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      {...(rest as SVGProps<SVGSVGElement>)}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  );
}

/* ───── Socratiq mark ─────
   Stroked Q — frame of inquiry holding a thought (the dot),
   with a tail (the answer departing). */
export function SocratiqMark({ size = 28, stroke = 1.6, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-label="Socratiq"
      {...rest}
    >
      <circle cx="14" cy="14" r="9" stroke="currentColor" strokeWidth={stroke} />
      <circle cx="18" cy="11" r="1.6" fill="currentColor" />
      <path d="M19.5 19.5 L25 25" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" />
    </svg>
  );
}

export function SocratiqMarkAccent({ size = 28, ...rest }: IconProps) {
  // The accented mark intentionally uses fixed stroke widths to keep the
  // contrast between the inquiry circle (ink) and the answer tail (accent).
  if ("stroke" in rest) delete (rest as { stroke?: number }).stroke;
  return (
    <svg
      {...(rest as SVGProps<SVGSVGElement>)}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-label="Socratiq"
    >
      <circle cx="14" cy="14" r="9" stroke="var(--ink)" strokeWidth="1.6" />
      <circle cx="18" cy="11" r="1.6" fill="var(--accent)" />
      <path d="M19.5 19.5 L25 25" stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function SocratiqLogo({
  size = 22,
  color,
}: {
  size?: number;
  color?: string;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        color: color || "var(--ink)",
      }}
    >
      <SocratiqMark size={size} />
      <span
        style={{
          fontFamily: "var(--serif)",
          fontSize: size * 0.78,
          fontWeight: 500,
          letterSpacing: "-0.01em",
          lineHeight: 1,
        }}
      >
        socratiq
      </span>
    </span>
  );
}

/* ───── Navigation ───── */
export const IcHome = (p: IconProps) => <Base {...p}><path d="M4 11 L12 4 L20 11" /><path d="M6 10 V20 H18 V10" /><path d="M10 20 V14 H14 V20" /></Base>;
export const IcSpark = (p: IconProps) => <Base {...p}><path d="M12 3 V8" /><path d="M12 16 V21" /><path d="M3 12 H8" /><path d="M16 12 H21" /><circle cx="12" cy="12" r="2.5" /></Base>;
export const IcImport = (p: IconProps) => <Base {...p}><path d="M12 3 V14" /><path d="M8 10 L12 14 L16 10" /><path d="M5 17 V20 H19 V17" /></Base>;
export const IcGraph = (p: IconProps) => <Base {...p}><circle cx="6" cy="7" r="2.5" /><circle cx="18" cy="7" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8 8 L10 16" /><path d="M16 8 L14 16" /><path d="M8 7 H16" /></Base>;
export const IcSources = (p: IconProps) => <Base {...p}><rect x="4" y="5" width="11" height="15" rx="1.5" /><path d="M8 9 H11" /><path d="M8 12 H11" /><path d="M17 8 V20 H7" /></Base>;
export const IcSettings = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="2.5" /><path d="M12 3 V5.5" /><path d="M12 18.5 V21" /><path d="M3 12 H5.5" /><path d="M18.5 12 H21" /><path d="M5.6 5.6 L7.4 7.4" /><path d="M16.6 16.6 L18.4 18.4" /><path d="M18.4 5.6 L16.6 7.4" /><path d="M7.4 16.6 L5.6 18.4" /></Base>;
export const IcDesign = (p: IconProps) => <Base {...p}><rect x="3.5" y="3.5" width="7" height="7" rx="1" /><circle cx="17" cy="7" r="3.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1" /><path d="M13.5 13.5 L20.5 20.5" /><path d="M20.5 13.5 L13.5 20.5" /></Base>;

/* ───── Action ───── */
export const IcPlus = (p: IconProps) => <Base {...p}><path d="M12 5 V19" /><path d="M5 12 H19" /></Base>;
export const IcSearch = (p: IconProps) => <Base {...p}><circle cx="11" cy="11" r="6" /><path d="M15.5 15.5 L20 20" /></Base>;
export const IcArrowRight = (p: IconProps) => <Base {...p}><path d="M5 12 H19" /><path d="M13 6 L19 12 L13 18" /></Base>;
export const IcArrowLeft = (p: IconProps) => <Base {...p}><path d="M19 12 H5" /><path d="M11 6 L5 12 L11 18" /></Base>;
export const IcChevronRight = (p: IconProps) => <Base {...p}><path d="M9 6 L15 12 L9 18" /></Base>;
export const IcChevronLeft = (p: IconProps) => <Base {...p}><path d="M15 6 L9 12 L15 18" /></Base>;
export const IcChevronDown = (p: IconProps) => <Base {...p}><path d="M6 9 L12 15 L18 9" /></Base>;
export const IcChevronUp = (p: IconProps) => <Base {...p}><path d="M6 15 L12 9 L18 15" /></Base>;
export const IcClose = (p: IconProps) => <Base {...p}><path d="M6 6 L18 18" /><path d="M18 6 L6 18" /></Base>;
export const IcMenu = (p: IconProps) => <Base {...p}><path d="M4 7 H20" /><path d="M4 12 H20" /><path d="M4 17 H20" /></Base>;
export const IcMore = (p: IconProps) => <Base {...p}><circle cx="6" cy="12" r="1.2" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" /><circle cx="18" cy="12" r="1.2" fill="currentColor" stroke="none" /></Base>;

/* ───── Status / signal ───── */
export const IcCheck = (p: IconProps) => <Base {...p}><path d="M5 12 L10 17 L19 7" /></Base>;
export const IcCheckCircle = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M8 12 L11 15 L16 9" /></Base>;
export const IcAlert = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8 V13" /><circle cx="12" cy="16" r=".8" fill="currentColor" stroke="none" /></Base>;
export const IcInfo = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11 V16" /><circle cx="12" cy="8" r=".8" fill="currentColor" stroke="none" /></Base>;
export const IcLoader = (p: IconProps) => <Base {...p}><path d="M12 3 V7" /><path d="M12 17 V21" /><path d="M3 12 H7" /><path d="M17 12 H21" opacity="0.4" /><path d="M5.6 5.6 L8.4 8.4" /><path d="M15.6 15.6 L18.4 18.4" opacity="0.4" /><path d="M18.4 5.6 L15.6 8.4" opacity="0.6" /><path d="M8.4 15.6 L5.6 18.4" opacity="0.8" /></Base>;

/* ───── Domain ───── */
export const IcLesson = (p: IconProps) => <Base {...p}><path d="M4 6 V19 L12 17 L20 19 V6 L12 8 L4 6 Z" /><path d="M12 8 V17" /></Base>;
export const IcConcept = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="1.5" /><circle cx="19" cy="6" r="1.5" /><circle cx="5" cy="18" r="1.5" /><circle cx="19" cy="18" r="1.5" /><path d="M9.5 10 L6.5 7" /><path d="M14.5 10 L17.5 7" /><path d="M9.5 14 L6.5 17" /><path d="M14.5 14 L17.5 17" /></Base>;
export const IcMentor = (p: IconProps) => <Base {...p}><path d="M4 5 H20 V16 H13 L9 20 V16 H4 V5 Z" /><circle cx="12" cy="11" r=".9" fill="currentColor" stroke="none" /><path d="M10 8.5 Q12 7 14 8.5" /></Base>;
export const IcExercise = (p: IconProps) => <Base {...p}><rect x="5" y="5" width="14" height="16" rx="1.5" /><path d="M9 4 H15 V7 H9 Z" /><path d="M8.5 12 L10.5 14 L15 9.5" /></Base>;
export const IcLab = (p: IconProps) => <Base {...p}><path d="M9 3 H15" /><path d="M10 3 V10 L5 19 Q5 21 7 21 H17 Q19 21 19 19 L14 10 V3" /><path d="M7.2 15 H16.8" /></Base>;
export const IcReview = (p: IconProps) => <Base {...p}><path d="M5 12 A7 7 0 0 1 18 8" /><path d="M18 4 V8 H14" /><path d="M19 12 A7 7 0 0 1 6 16" /><path d="M6 20 V16 H10" /></Base>;
export const IcDiagnostic = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M5 12 H8 L10 8 L13 16 L15 12 H19" /></Base>;
export const IcCite = (p: IconProps) => <Base {...p}><path d="M6 8 H10 V12 H6 V10 Q6 8 8 7" /><path d="M14 8 H18 V12 H14 V10 Q14 8 16 7" /><path d="M5 16 H19" /></Base>;
export const IcPath = (p: IconProps) => <Base {...p}><circle cx="5" cy="6" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="18" r="2" /><path d="M6.4 7.4 Q9 9 10.6 10.6" /><path d="M13.4 13.4 Q16 15 17.6 16.6" /></Base>;

/* ───── Source types ───── */
export const IcVideo = (p: IconProps) => <Base {...p}><rect x="3" y="6" width="18" height="13" rx="2.5" /><path d="M11 10.5 L14.5 12.5 L11 14.5 Z" fill="currentColor" stroke="none" /></Base>;
export const IcDoc = (p: IconProps) => <Base {...p}><path d="M6 3 H14 L18 7 V21 H6 V3 Z" /><path d="M14 3 V7 H18" /><path d="M9 13 H15" /><path d="M9 16 H15" /><path d="M9 10 H12" /></Base>;
export const IcBookmark = (p: IconProps) => <Base {...p}><path d="M6 4 H18 V21 L12 17 L6 21 Z" /></Base>;
export const IcTV = (p: IconProps) => <Base {...p}><rect x="3" y="8" width="18" height="12" rx="2" /><path d="M8 4 L11 8" /><path d="M16 4 L13 8" /><circle cx="9" cy="14" r=".9" fill="currentColor" stroke="none" /><circle cx="15" cy="14" r=".9" fill="currentColor" stroke="none" /></Base>;
export const IcFolder = (p: IconProps) => <Base {...p}><path d="M3 7 V19 H21 V9 H12 L10 7 Z" /></Base>;

/* ───── Misc ───── */
export const IcSend = (p: IconProps) => <Base {...p}><path d="M4 12 L20 5 L17 20 L11 13 Z" /><path d="M4 12 L11 13" /></Base>;
export const IcTrash = (p: IconProps) => <Base {...p}><path d="M5 7 H19" /><path d="M9 7 V5 H15 V7" /><path d="M7 7 L8 21 H16 L17 7" /></Base>;
export const IcEdit = (p: IconProps) => <Base {...p}><path d="M4 20 L4 17 L16 5 L19 8 L7 20 Z" /><path d="M14 7 L17 10" /></Base>;
export const IcFilter = (p: IconProps) => <Base {...p}><path d="M3 5 H21 L14 13 V19 L10 21 V13 Z" /></Base>;
export const IcClock = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7 V12 L15 14" /></Base>;
export const IcMemory = (p: IconProps) => <Base {...p}><path d="M4 7 L12 4 L20 7 L12 10 Z" /><path d="M4 12 L12 15 L20 12" /><path d="M4 17 L12 20 L20 17" /></Base>;
export const IcSun = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="4" /><path d="M12 3 V5" /><path d="M12 19 V21" /><path d="M3 12 H5" /><path d="M19 12 H21" /><path d="M5.6 5.6 L7 7" /><path d="M17 17 L18.4 18.4" /><path d="M18.4 5.6 L17 7" /><path d="M7 17 L5.6 18.4" /></Base>;
export const IcMoon = (p: IconProps) => <Base {...p}><path d="M20 14 A8 8 0 1 1 10 4 A6 6 0 0 0 20 14 Z" /></Base>;
export const IcLang = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12 H21" /><path d="M12 3 Q17 8 17 12 Q17 16 12 21 Q7 16 7 12 Q7 8 12 3 Z" /></Base>;
export const IcLink = (p: IconProps) => <Base {...p}><path d="M9 15 L15 9" /><path d="M11 6 L13 4 Q17 0 21 4 Q24 7 21 11 L19 13" /><path d="M13 18 L11 20 Q7 24 3 20 Q0 17 3 13 L5 11" /></Base>;
export const IcArrowUp = (p: IconProps) => <Base {...p}><path d="M12 19 V5" /><path d="M6 11 L12 5 L18 11" /></Base>;
export const IcSparkle = (p: IconProps) => <Base {...p}><path d="M12 3 L13.5 9 L19.5 10.5 L13.5 12 L12 18 L10.5 12 L4.5 10.5 L10.5 9 Z" /></Base>;
export const IcUser = (p: IconProps) => <Base {...p}><circle cx="12" cy="9" r="3.5" /><path d="M5 20 Q5 14 12 14 Q19 14 19 20" /></Base>;
export const IcRegen = (p: IconProps) => <Base {...p}><path d="M5 12 A7 7 0 1 0 8 6.5" /><path d="M5 4 V8 H9" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /></Base>;
export const IcExternal = (p: IconProps) => <Base {...p}><path d="M14 4 H20 V10" /><path d="M20 4 L11 13" /><path d="M19 14 V19 H5 V5 H10" /></Base>;
export const IcPanelLeftClose = (p: IconProps) => <Base {...p}><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M9.5 4.5 V19.5" /><path d="M16 9 L13 12 L16 15" /></Base>;
export const IcPanelLeftOpen = (p: IconProps) => <Base {...p}><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M9.5 4.5 V19.5" /><path d="M13 9 L16 12 L13 15" /></Base>;
export const IcUpload = (p: IconProps) => <Base {...p}><path d="M12 4 V15" /><path d="M7 9 L12 4 L17 9" /><path d="M5 17 V20 H19 V17" /></Base>;
export const IcMessage = (p: IconProps) => <Base {...p}><path d="M4 5 H20 V17 H13 L9 21 V17 H4 V5 Z" /></Base>;
export const IcPlay = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M10 8 L16 12 L10 16 Z" fill="currentColor" stroke="none" /></Base>;
export const IcBarChart = (p: IconProps) => <Base {...p}><path d="M4 20 V10" /><path d="M10 20 V4" /><path d="M16 20 V14" /><path d="M22 20 H2" /></Base>;

/* Map a backend source-type string to the right icon. */
export function SourceIcon({ type, size = 16, ...rest }: IconProps & { type?: string }) {
  switch (type) {
    case "youtube":
      return <IcVideo size={size} {...rest} />;
    case "bilibili":
      return <IcTV size={size} {...rest} />;
    case "pdf":
      return <IcDoc size={size} {...rest} />;
    case "markdown":
    case "md":
    case "article":
      return <IcDoc size={size} {...rest} />;
    case "url":
      return <IcLink size={size} {...rest} />;
    default:
      return <IcFolder size={size} {...rest} />;
  }
}
