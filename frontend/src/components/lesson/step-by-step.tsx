"use client";
import { useState } from "react";

interface Step { label: string; detail: string; code?: string | null }

export default function StepByStep({ title, steps }: { title: string; steps: Step[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div className="my-4 border border-gray-200 rounded-lg overflow-hidden">
      <div className="bg-gray-50 px-4 py-2 text-sm font-medium text-gray-700">{title}</div>
      {steps.map((step, i) => (
        <div key={i} className="border-t border-gray-100">
          <button onClick={() => setExpanded(expanded === i ? null : i)}
            className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 min-h-[44px]">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-100 text-blue-600 text-xs flex items-center justify-center font-medium">{i + 1}</span>
            <span className="text-sm text-gray-900">{step.label}</span>
          </button>
          {expanded === i && (
            <div className="px-4 pb-3 pl-13 text-sm text-gray-600">
              <p>{step.detail}</p>
              {step.code && <pre className="mt-2 p-3 bg-gray-900 text-green-300 rounded text-xs overflow-x-auto">{step.code}</pre>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
