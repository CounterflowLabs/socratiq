"use client";

interface LabData {
  id: string;
  title: string;
  description: string;
  language: string;
  starter_code: Record<string, string>;
  test_code: Record<string, string>;
  run_instructions: string;
  confidence: number;
}

export default function LabViewer({ lab }: { lab: LabData }) {
  const API_BASE = "http://localhost:8000/api/v1";

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold text-gray-900">{lab.title}</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">AI 置信度: {Math.round(lab.confidence * 100)}%</span>
          <a href={`${API_BASE}/labs/${lab.id}/download`}
            className="px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
            下载 Lab
          </a>
        </div>
      </div>

      <div className="prose prose-sm max-w-none mb-6 text-gray-700"
        dangerouslySetInnerHTML={{ __html: lab.description.replace(/\n/g, "<br/>") }} />

      {/* Starter Code */}
      <h3 className="text-sm font-semibold text-gray-700 mb-2">骨架代码（填写 TODO 部分）</h3>
      {Object.entries(lab.starter_code).map(([filename, code]) => (
        <div key={filename} className="mb-4">
          <div className="text-xs text-gray-400 mb-1">{filename}</div>
          <pre className="p-4 bg-gray-900 text-gray-100 rounded-lg text-sm overflow-x-auto">
            <code>{code}</code>
          </pre>
        </div>
      ))}

      {/* Test Code */}
      <h3 className="text-sm font-semibold text-gray-700 mb-2 mt-6">测试代码</h3>
      {Object.entries(lab.test_code).map(([filename, code]) => (
        <div key={filename} className="mb-4">
          <div className="text-xs text-gray-400 mb-1">{filename}</div>
          <pre className="p-4 bg-gray-900 text-gray-100 rounded-lg text-sm overflow-x-auto">
            <code>{code}</code>
          </pre>
        </div>
      ))}

      {/* Run Instructions */}
      <h3 className="text-sm font-semibold text-gray-700 mb-2 mt-6">运行方式</h3>
      <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-700 whitespace-pre-wrap">
        {lab.run_instructions}
      </div>
    </div>
  );
}
