"use client";
import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false, theme: "neutral" });

export default function MermaidDiagram({ content, title }: { content: string; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const id = `mermaid-${Math.random().toString(36).slice(2)}`;
    mermaid.render(id, content)
      .then(({ svg }) => { if (ref.current) ref.current.innerHTML = svg; })
      .catch(() => setError(true));
  }, [content]);

  if (error) return <pre className="text-xs text-gray-500 bg-gray-50 p-3 rounded">{content}</pre>;
  return (
    <div className="my-4">
      {title && <p className="text-xs font-medium text-gray-500 mb-2">{title}</p>}
      <div ref={ref} className="overflow-x-auto" />
    </div>
  );
}
