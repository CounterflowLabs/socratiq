"use client";

import { useEffect, useState } from "react";
import { Loader2, Sparkles, X } from "lucide-react";

interface RegenerateDrawerProps {
  open: boolean;
  initialDirective?: string | null;
  pending: boolean;
  errorMessage?: string | null;
  onClose: () => void;
  onSubmit: (directive: string) => void | Promise<void>;
}

const MAX_DIRECTIVE_LEN = 1000;

const PLACEHOLDER_EXAMPLES = [
  "把课文写得更精炼一点。",
  "多给实战示例，少讲理论。",
  "我是初学者，请简化讲解。",
  "每个小节多放一些代码示例。",
];

export default function RegenerateDrawer({
  open,
  initialDirective,
  pending,
  errorMessage,
  onClose,
  onSubmit,
}: RegenerateDrawerProps) {
  const [directive, setDirective] = useState<string>(initialDirective ?? "");

  useEffect(() => {
    if (open) {
      setDirective(initialDirective ?? "");
    }
  }, [open, initialDirective]);

  useEffect(() => {
    if (!open) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = original;
    };
  }, [open]);

  if (!open) return null;

  const remaining = MAX_DIRECTIVE_LEN - directive.length;
  const placeholder = PLACEHOLDER_EXAMPLES.join("\n");

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/30 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="重新生成课程"
    >
      <button
        type="button"
        aria-label="关闭重新生成抽屉的遮罩"
        className="absolute inset-0 bg-transparent"
        onClick={pending ? undefined : onClose}
      />
      <div
        className="relative z-10 flex h-full w-full max-w-md flex-col overflow-y-auto shadow-2xl animate-[slideIn_0.25s_ease-out]"
        style={{ background: "var(--surface)", color: "var(--text)" }}
      >
        <div
          className="sticky top-0 flex items-center justify-between border-b px-5 py-4"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-violet-500" />
            <h2 className="text-lg font-semibold">重新生成课程</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            className="rounded-md p-1.5 transition hover:bg-gray-100 disabled:opacity-50"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 space-y-5 px-5 py-5">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            用当前的提示词和你选定的模型重跑内容管线，产出一个新版本；当前版本会被保留。
          </p>

          <label className="block">
            <span className="text-sm font-medium">自定义指令（可选）</span>
            <textarea
              value={directive}
              onChange={(e) =>
                setDirective(e.target.value.slice(0, MAX_DIRECTIVE_LEN))
              }
              disabled={pending}
              rows={6}
              placeholder={placeholder}
              className="mt-2 w-full resize-y rounded-md border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-violet-300 disabled:opacity-60"
              style={{
                borderColor: "var(--border-medium)",
                background: "var(--surface-alt)",
              }}
            />
            <p
              className="mt-1 text-xs"
              style={{ color: "var(--text-tertiary)" }}
            >
              还可输入 {remaining} 字
            </p>
          </label>

          <div
            className="rounded-md border px-3 py-2 text-xs"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface-alt)",
              color: "var(--text-secondary)",
            }}
          >
            预估消耗 10–20k tokens · 2–5 分钟。当前版本的阅读进度不会迁移到新版本。
          </div>

          {errorMessage ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {errorMessage}
            </div>
          ) : null}
        </div>

        <div
          className="sticky bottom-0 flex items-center justify-end gap-2 border-t px-5 py-4"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            className="rounded-md px-3 py-2 text-sm font-medium transition hover:bg-gray-100 disabled:opacity-50"
            style={{ color: "var(--text-secondary)" }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void onSubmit(directive.trim())}
            disabled={pending}
            className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-violet-700 disabled:opacity-60"
          >
            {pending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                启动中…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                开始重生成
              </>
            )}
          </button>
        </div>

        <style>{`
          @keyframes slideIn {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
          }
        `}</style>
      </div>
    </div>
  );
}
