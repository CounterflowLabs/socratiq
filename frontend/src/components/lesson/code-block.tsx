"use client";

import { useState, useCallback } from "react";
import { Check, Copy } from "lucide-react";

export default function CodeBlock({ language, code, context }: { language: string; code: string; context?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API may not be available
    }
  }, [code]);

  return (
    <div className="my-3">
      {context && <p className="text-xs mb-1" style={{ color: "var(--text-tertiary)" }}>{context}</p>}
      <div className="relative">
        <div className="absolute top-2 right-2 flex items-center gap-2">
          <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>{language}</span>
          <button
            type="button"
            onClick={handleCopy}
            className="rounded-md p-1.5 transition hover:opacity-80"
            style={{ background: "rgba(255,255,255,0.1)", color: "var(--text-tertiary)" }}
            aria-label="复制代码"
          >
            {copied ? <Check className="w-3.5 h-3.5" style={{ color: "var(--success)" }} /> : <Copy className="w-3.5 h-3.5" />}
          </button>
        </div>
        <pre
          className="p-4 rounded-lg text-sm overflow-x-auto"
          style={{ background: "var(--surface-alt)", color: "var(--text)", border: "1px solid var(--border)" }}
        >
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}
