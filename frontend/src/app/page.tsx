"use client";

import Link from "next/link";
import { Flame, Clock, Target, TrendingUp, Brain, ArrowRight, CheckCircle, RotateCcw, Plus, Play, ChevronRight, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress-bar";
import { clsx } from "clsx";

const STATS = [
  { icon: Flame, label: "连续天数", value: "3 天", color: "text-orange-500", bg: "bg-orange-50" },
  { icon: Clock, label: "本周学习", value: "2.5 h", color: "text-blue-500", bg: "bg-blue-50" },
  { icon: Target, label: "概念掌握", value: "4 / 12", color: "text-green-500", bg: "bg-green-50" },
  { icon: TrendingUp, label: "正确率", value: "72%", color: "text-violet-500", bg: "bg-violet-50" },
];

const WEEKLY = [
  { day: "一", height: 40 },
  { day: "二", height: 65 },
  { day: "三", height: 30 },
  { day: "四", height: 80 },
  { day: "五", height: 50 },
  { day: "六", height: 0 },
  { day: "日", height: 0 },
];

export default function DashboardPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-6 py-6">
        {/* Greeting */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-gray-900">欢迎回来 👋</h1>
          <p className="text-sm text-gray-500 mt-1">你已经连续学习 3 天了，继续保持！</p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {STATS.map((stat, i) => (
            <Card key={i} className="p-4">
              <div className={clsx("w-8 h-8 rounded-lg flex items-center justify-center mb-2", stat.bg)}>
                <stat.icon className={clsx("w-4 h-4", stat.color)} />
              </div>
              <p className="text-xl font-bold text-gray-900">{stat.value}</p>
              <p className="text-xs text-gray-500">{stat.label}</p>
            </Card>
          ))}
        </div>

        {/* Today's suggestion */}
        <Card className="p-4 mb-6 border-blue-200 bg-gradient-to-r from-blue-50 to-white">
          <div className="flex items-center justify-between">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
                <Brain className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">今日建议</p>
                <p className="text-sm text-gray-600 mt-0.5">继续学习「Tokenization 基础」— 你上次学到了 BPE 算法部分。今天完成这一章的练习后，我们就可以进入 Embedding 了。</p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="text-xs text-gray-400 flex items-center gap-1"><Clock className="w-3 h-3" /> 预计 15 分钟</span>
                  <span className="text-xs text-gray-400 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> 2 道练习待完成</span>
                </div>
              </div>
            </div>
            <Link href="/path">
              <Button>继续学习 <ArrowRight className="w-4 h-4" /></Button>
            </Link>
          </div>
        </Card>

        {/* Spaced repetition reminder */}
        <Card className="p-4 mb-6 border-amber-200 bg-amber-50">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <RotateCcw className="w-5 h-5 text-amber-600" />
              <div>
                <p className="text-sm font-medium text-amber-800">间隔复习提醒</p>
                <p className="text-xs text-amber-700 mt-0.5">「BPE 算法原理」的知识点即将进入遗忘期，建议今天复习</p>
              </div>
            </div>
            <Button variant="secondary" size="sm">开始复习</Button>
          </div>
        </Card>

        {/* Active courses */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">进行中的课程</h2>
          <Link href="/import">
            <Button variant="ghost" size="sm"><Plus className="w-3.5 h-3.5" /> 导入新资料</Button>
          </Link>
        </div>

        <Link href="/path" className="no-underline">
          <Card className="p-4 mb-6" hover>
            <div className="flex items-center gap-4">
              <div className="w-16 h-10 rounded-lg bg-gray-900 flex items-center justify-center flex-shrink-0">
                <Play className="w-4 h-4 text-white" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-semibold text-gray-900">深度学习之数学原理</h3>
                <p className="text-xs text-gray-500">3Blue1Brown · Bilibili · 5 章节 · 12 概念</p>
                <div className="mt-2 flex items-center gap-2">
                  <ProgressBar value={20} className="flex-1" />
                  <span className="text-xs text-gray-400">20%</span>
                </div>
              </div>
              <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
            </div>
          </Card>
        </Link>

        {/* Weekly activity */}
        <h2 className="text-sm font-semibold text-gray-900 mb-4">本周学习活动</h2>
        <Card className="p-4">
          <div className="flex items-end justify-between gap-2 h-24">
            {WEEKLY.map((item, i) => {
              const isToday = i === 3;
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1">
                  <div className="w-full flex items-end justify-center" style={{ height: 80 }}>
                    <div
                      className={clsx(
                        "w-full max-w-[24px] rounded-t-md transition-all",
                        isToday ? "bg-blue-500" : item.height > 0 ? "bg-blue-200" : "bg-gray-100"
                      )}
                      style={{ height: item.height || 4 }}
                    />
                  </div>
                  <span className={clsx("text-xs", isToday ? "text-blue-600 font-medium" : "text-gray-400")}>
                    {item.day}
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </div>
  );
}
