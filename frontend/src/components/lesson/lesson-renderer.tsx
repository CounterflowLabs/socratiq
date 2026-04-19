"use client";

import type { LessonContent } from "@/lib/api";

import LessonBlockRenderer from "./lesson-block-renderer";

export default function LessonRenderer({
  lesson, onTimestampClick,
}: {
  lesson: LessonContent;
  onTimestampClick?: (seconds: number) => void;
}) {
  return <LessonBlockRenderer lesson={lesson} onTimestampClick={onTimestampClick} />;
}
