"use client";

import { useState, useMemo } from "react";
import dynamic from "next/dynamic";
import { FileCode, FileText, FlaskConical, RotateCcw, Download, ChevronDown } from "lucide-react";
import { clsx } from "clsx";
import type { LabResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

function langFromExt(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python",
    js: "javascript",
    ts: "typescript",
    tsx: "typescript",
    jsx: "javascript",
    go: "go",
    rs: "rust",
    java: "java",
    c: "c",
    cpp: "cpp",
    rb: "ruby",
    sh: "shell",
    json: "json",
    md: "markdown",
    html: "html",
    css: "css",
  };
  return map[ext] || "plaintext";
}

interface LabEditorProps {
  lab: LabResponse;
  embedded?: boolean;
}

export default function LabEditor({ lab, embedded = false }: LabEditorProps) {
  const starterFiles = useMemo(() => Object.keys(lab.starter_code), [lab.starter_code]);
  const testFiles = useMemo(() => Object.keys(lab.test_code), [lab.test_code]);

  const [selectedFile, setSelectedFile] = useState<string>(starterFiles[0] ?? testFiles[0] ?? "");
  const [editedCode, setEditedCode] = useState<Record<string, string>>({ ...lab.starter_code });
  const [instructionsOpen, setInstructionsOpen] = useState(false);

  const isTestFile = testFiles.includes(selectedFile);
  const currentCode = isTestFile
    ? lab.test_code[selectedFile]
    : (editedCode[selectedFile] ?? lab.starter_code[selectedFile] ?? "");
  const currentLang = langFromExt(selectedFile);

  function handleReset() {
    if (confirm("重置所有代码？这将丢失你的修改。")) {
      setEditedCode({ ...lab.starter_code });
    }
  }

  async function handleDownload() {
    const JSZip = (await import("jszip")).default;
    const zip = new JSZip();

    // Add edited starter code
    for (const [name, code] of Object.entries(editedCode)) {
      zip.file(name, code);
    }
    // Add test code
    for (const [name, code] of Object.entries(lab.test_code)) {
      zip.file(name, code);
    }
    // Add README
    zip.file("README.md", `# ${lab.title}\n\n${lab.description}\n\n## Run Instructions\n\n${lab.run_instructions}`);

    const blob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${lab.title.replace(/\s+/g, "-").toLowerCase()}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div
      className={clsx(
        "overflow-hidden",
        embedded
          ? "flex min-h-[520px] flex-col rounded-2xl border border-gray-200 bg-white lg:flex-row"
          : "flex h-full"
      )}
    >
      {/* File tree sidebar */}
      <div
        className={clsx(
          "flex flex-col overflow-y-auto bg-gray-50/50",
          embedded
            ? "border-b border-gray-200 lg:w-[220px] lg:flex-shrink-0 lg:border-b-0 lg:border-r"
            : "w-[220px] flex-shrink-0 border-r border-gray-200"
        )}
      >
        {/* Title + confidence */}
        <div className="px-3 py-3 border-b border-gray-200">
          <h3 className="text-xs font-semibold text-gray-700 truncate mb-1">{lab.title}</h3>
          <Badge color={lab.confidence >= 0.7 ? "green" : lab.confidence >= 0.4 ? "orange" : "red"}>
            AI {Math.round(lab.confidence * 100)}%
          </Badge>
        </div>

        {/* Source files */}
        <div className="px-2 pt-3">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-1 mb-1">Source</p>
          {starterFiles.map((f) => (
            <button
              key={f}
              onClick={() => setSelectedFile(f)}
              className={clsx(
                "flex items-center gap-1.5 px-2 py-1.5 w-full text-left rounded text-xs transition-colors bg-transparent",
                selectedFile === f
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : "text-gray-600 hover:bg-gray-100"
              )}
            >
              <FileCode className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="truncate">{f}</span>
            </button>
          ))}
        </div>

        {/* Test files */}
        {testFiles.length > 0 && (
          <div className="px-2 pt-3">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-1 mb-1">Tests (read-only)</p>
            {testFiles.map((f) => (
              <button
                key={f}
                onClick={() => setSelectedFile(f)}
                className={clsx(
                  "flex items-center gap-1.5 px-2 py-1.5 w-full text-left rounded text-xs transition-colors bg-transparent",
                  selectedFile === f
                    ? "bg-gray-200 text-gray-700 font-medium"
                    : "text-gray-500 hover:bg-gray-100"
                )}
              >
                <FlaskConical className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="truncate">{f}</span>
              </button>
            ))}
          </div>
        )}

        {/* Run instructions */}
        {lab.run_instructions && (
          <div className="px-2 pt-3 mt-auto">
            <details open={instructionsOpen} onToggle={(e) => setInstructionsOpen((e.target as HTMLDetailsElement).open)}>
              <summary className="flex items-center gap-1.5 px-1 py-1 text-[10px] font-semibold text-gray-400 uppercase tracking-wider cursor-pointer select-none">
                <ChevronDown className={clsx("w-3 h-3 transition-transform", instructionsOpen && "rotate-180")} />
                Run Instructions
              </summary>
              <div className="px-1 py-2 text-xs text-gray-600 whitespace-pre-wrap leading-relaxed">
                {lab.run_instructions}
              </div>
            </details>
          </div>
        )}

        {/* Actions */}
        <div className="px-2 py-3 border-t border-gray-200 flex gap-2 mt-auto">
          <button
            onClick={handleReset}
            className="flex items-center gap-1 px-2 py-1.5 rounded text-xs text-gray-500 hover:bg-gray-100 transition-colors bg-transparent"
            title="重置代码"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            重置
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-1 px-2 py-1.5 rounded text-xs text-gray-500 hover:bg-gray-100 transition-colors bg-transparent"
            title="下载 ZIP"
          >
            <Download className="w-3.5 h-3.5" />
            下载
          </button>
        </div>
      </div>

      {/* Editor */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* File tab bar */}
        <div className="flex items-center px-3 py-1.5 border-b border-gray-200 bg-white gap-2">
          <FileText className="w-3.5 h-3.5 text-gray-400" />
          <span className="text-xs font-medium text-gray-700">{selectedFile}</span>
          {isTestFile && (
            <span className="text-[10px] text-gray-400 ml-1">(read-only)</span>
          )}
        </div>

        {/* Monaco editor */}
        <div className={clsx(embedded ? "min-h-[360px] flex-1" : "flex-1", isTestFile && "bg-gray-50")}>
          <MonacoEditor
            height="100%"
            language={currentLang}
            value={currentCode}
            onChange={(value) => {
              if (!isTestFile && value !== undefined) {
                setEditedCode((prev) => ({ ...prev, [selectedFile]: value }));
              }
            }}
            options={{
              readOnly: isTestFile,
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              padding: { top: 12 },
              renderLineHighlight: "gutter",
            }}
            theme="vs-dark"
          />
        </div>
      </div>
    </div>
  );
}
