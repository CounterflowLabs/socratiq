"use client";

import Link from "next/link";
import { ChevronRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const models = [
  { label: "主交互模型", value: "Claude Sonnet 4", desc: "用于导师对话" },
  { label: "轻量模型", value: "Claude Haiku 4", desc: "用于内容分析" },
  { label: "Embedding 模型", value: "text-embedding-3-small", desc: "用于向量检索" },
];

export default function SettingsPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-6">
      <h1 className="text-xl font-bold text-gray-900 mb-6">设置</h1>
      <Card className="p-6 mb-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">LLM 模型配置</h2>
        <div className="space-y-4">
          {models.map((item, i) => (
            <div key={i} className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
              <div>
                <p className="text-sm font-medium text-gray-900">{item.label}</p>
                <p className="text-xs text-gray-500">{item.desc}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-700">{item.value}</span>
                <ChevronRight className="w-4 h-4 text-gray-400" />
              </div>
            </div>
          ))}
        </div>
        <Button variant="secondary" size="sm" className="mt-4">
          <Plus className="w-3.5 h-3.5" /> 添加 Provider
        </Button>
      </Card>
    </div>
  );
}
