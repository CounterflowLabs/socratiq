"use client";

import MentorPanel from "@/components/learn/mentor-panel";

interface TutorDrawerProps {
  open: boolean;
  onClose: () => void;
  courseId: string | null;
  sectionId: string | null;
}

/**
 * Thin compatibility wrapper. The actual chat UI lives in MentorPanel so
 * the Learn shell can mount it inline as a persistent right rail while
 * legacy callers (dashboard "Mentor" CTA, mobile fallback) keep the
 * slide-in drawer.
 */
export default function TutorDrawer({ open, onClose, courseId, sectionId }: TutorDrawerProps) {
  return (
    <MentorPanel
      variant="overlay"
      open={open}
      onClose={onClose}
      courseId={courseId}
      sectionId={sectionId}
      fillHeight={false}
    />
  );
}
