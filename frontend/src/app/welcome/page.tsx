"use client";

import Link from "next/link";
import { Brain, Sparkles, ArrowRight, Play, Zap, Target } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function WelcomePage() {
  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="flex items-center justify-between px-6 h-14 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900">Socratiq</span>
        </div>
        <Button variant="secondary" size="sm">登录</Button>
      </header>

      <main className="flex-1 flex items-center justify-center px-6">
        <div className="max-w-2xl text-center">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-medium mb-6">
            <Sparkles className="w-3 h-3" /> AI 驱动的个性化学习
          </div>
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight mb-4" style={{ lineHeight: 1.2 }}>
            把任何学习资料，<br />变成你的<span className="text-blue-600">私人导师</span>
          </h1>
          <p className="text-lg text-gray-500 mb-8 max-w-lg mx-auto" style={{ lineHeight: 1.6 }}>
            粘贴一个 B站视频链接或上传 PDF，Socratiq 会为你生成个性化学习路径，用苏格拉底式引导帮你真正学会。
          </p>

          <div className="flex items-center justify-center gap-3 mb-12">
            <Link href="/import">
              <Button size="lg">
                开始学习 <ArrowRight className="w-4 h-4" />
              </Button>
            </Link>
            <Button variant="secondary" size="lg">
              <Play className="w-4 h-4" /> 观看演示
            </Button>
          </div>

          <div className="grid grid-cols-3 gap-6 text-left">
            {[
              { icon: Zap, title: "3 分钟生成路径", desc: "粘贴链接后自动分析内容，按难度编排学习路径" },
              { icon: Brain, title: "它知道你哪里不会", desc: "练习中识别知识缺口，回溯前置知识重新讲解" },
              { icon: Target, title: "推着你往前走", desc: "苏格拉底式引导，不只回答问题，而是推进学习" },
            ].map((f, i) => (
              <div key={i} className="p-4 rounded-xl bg-gray-50 border border-gray-100">
                <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center mb-3">
                  <f.icon className="w-4 h-4 text-blue-600" />
                </div>
                <h3 className="font-semibold text-gray-900 text-sm mb-1">{f.title}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
