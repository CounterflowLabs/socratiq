"use client";

import Link from "next/link";
import { Brain, Sparkles, ArrowRight, Zap, Target } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function WelcomePage() {
  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg)" }}>
      <header
        className="flex items-center justify-between px-6 h-14 border-b"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "var(--primary)" }}>
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold" style={{ color: "var(--text)" }}>Socratiq</span>
        </div>
        <Button variant="secondary" size="sm">登录</Button>
      </header>

      <main className="flex-1 flex items-center justify-center px-6">
        <div className="max-w-2xl text-center">
          <div
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium mb-6"
            style={{ background: "var(--primary-light)", color: "var(--primary)" }}
          >
            <Sparkles className="w-3 h-3" aria-hidden="true" /> AI 驱动的个性化学习
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4" style={{ color: "var(--text)", lineHeight: 1.2 }}>
            把任何学习资料，变成你的
            <span style={{ color: "var(--primary)" }}> 私人导师</span>
          </h1>
          <p className="text-base sm:text-lg mb-8 max-w-lg mx-auto" style={{ color: "var(--text-secondary)", lineHeight: 1.6 }}>
            粘贴一个 B站视频链接或上传 PDF，Socratiq 会为你生成个性化学习路径，用苏格拉底式引导帮你真正学会。
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-12">
            <Link href="/import">
              <Button size="lg">
                开始学习 <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </Button>
            </Link>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6 text-left">
            {[
              { icon: Zap, title: "3 分钟生成路径", desc: "粘贴链接后自动分析内容，按难度编排学习路径" },
              { icon: Brain, title: "它知道你哪里不会", desc: "练习中识别知识缺口，回溯前置知识重新讲解" },
              { icon: Target, title: "推着你往前走", desc: "苏格拉底式引导，不只回答问题，而是推进学习" },
            ].map((f, i) => (
              <div
                key={i}
                className="p-4 rounded-xl border"
                style={{ background: "var(--surface-alt)", borderColor: "var(--border)" }}
              >
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center mb-3"
                  style={{ background: "var(--primary-light)" }}
                >
                  <f.icon className="w-4 h-4" style={{ color: "var(--primary)" }} aria-hidden="true" />
                </div>
                <h3 className="font-semibold text-sm mb-1" style={{ color: "var(--text)" }}>{f.title}</h3>
                <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
