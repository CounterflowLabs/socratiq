"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";

function DiagnosticInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const courseId = searchParams.get("courseId");

  useEffect(() => {
    // Diagnostic is now handled by the MentorAgent in chat.
    // Redirect to learn page where the mentor will conduct the assessment.
    if (courseId) {
      router.replace(`/learn?courseId=${courseId}`);
    } else {
      router.replace("/");
    }
  }, [courseId, router]);

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-sm text-gray-500">正在准备学习环境...</div>
    </div>
  );
}

export default function DiagnosticPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-sm text-gray-500">正在准备学习环境...</div>
        </div>
      }
    >
      <DiagnosticInner />
    </Suspense>
  );
}
