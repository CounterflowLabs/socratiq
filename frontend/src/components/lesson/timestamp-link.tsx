"use client";

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function TimestampLink({ seconds, onClick }: { seconds: number; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 font-mono text-xs text-blue-600 hover:bg-blue-100">
      &#9654; {formatTime(seconds)}
    </button>
  );
}
