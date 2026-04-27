"use client";

import type { GraphCard, LabMode, LessonContent } from "@/lib/api";

import LessonBlockRenderer from "./lesson-block-renderer";

export default function LessonRenderer({
  lesson,
  onTimestampClick,
  sectionId,
  courseId,
  labMode,
  graphCard,
}: {
  lesson: LessonContent;
  onTimestampClick?: (seconds: number) => void;
  sectionId?: string | null;
  courseId?: string | null;
  labMode?: LabMode | null;
  graphCard?: GraphCard | null;
}) {
  return (
    <LessonBlockRenderer
      lesson={lesson}
      onTimestampClick={onTimestampClick}
      sectionId={sectionId}
      courseId={courseId}
      labMode={labMode}
      graphCard={graphCard}
    />
  );
}
