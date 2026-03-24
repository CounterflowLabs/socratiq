"use client";

import { useRouter } from "next/navigation";

export default function ExercisePage() {
  const router = useRouter();

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-6">
      <div className="bg-white rounded-xl border border-gray-200 p-8 max-w-md w-full text-center">
        <div className="w-16 h-16 rounded-full bg-blue-100 flex items-center justify-center mx-auto mb-4">
          <span className="text-2xl">{"\u{1F4DD}"}</span>
        </div>
        <h2 className="text-xl font-bold text-gray-900 mb-2">
          练习功能开发中
        </h2>
        <p className="text-sm text-gray-500 mb-6">
          导师会根据你的学习内容和薄弱点自动生成针对性练习题。此功能即将上线。
        </p>
        <button
          onClick={() => router.back()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"
        >
          返回学习
        </button>
      </div>
    </div>
  );
}
