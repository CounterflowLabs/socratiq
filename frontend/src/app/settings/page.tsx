"use client";

import { useEffect, useState } from "react";
import { getModels, getModelRoutes, deleteModel, testModel } from "@/lib/api";
import type { ModelConfigResponse, ModelRouteResponse } from "@/lib/api";

export default function SettingsPage() {
  const [models, setModels] = useState<ModelConfigResponse[]>([]);
  const [routes, setRoutes] = useState<ModelRouteResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<
    Record<string, { success: boolean; message: string }>
  >({});

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [m, r] = await Promise.all([getModels(), getModelRoutes()]);
      setModels(m);
      setRoutes(r);
    } catch (e) {
      console.error("Failed to load settings:", e);
    } finally {
      setLoading(false);
    }
  }

  async function handleTest(name: string) {
    setTesting(name);
    try {
      const result = await testModel(name);
      setTestResult((prev) => ({ ...prev, [name]: result }));
    } catch {
      setTestResult((prev) => ({
        ...prev,
        [name]: { success: false, message: "Request failed" },
      }));
    } finally {
      setTesting(null);
    }
  }

  async function handleDelete(name: string) {
    try {
      await deleteModel(name);
      setModels((prev) => prev.filter((m) => m.name !== name));
    } catch (e) {
      console.error("Failed to delete model:", e);
    }
  }

  function getRouteLabel(taskType: string): string {
    const map: Record<string, string> = {
      mentor_chat: "主交互",
      content_analysis: "内容分析",
      evaluation: "复杂推理",
      embedding: "向量计算",
    };
    return map[taskType] || taskType;
  }

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-6">
        <h1 className="text-xl font-bold text-gray-900 mb-6">设置</h1>
        <div className="text-sm text-gray-500">加载中...</div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-6">
      <h1 className="text-xl font-bold text-gray-900 mb-6">设置</h1>

      {/* Model Routes */}
      {routes.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">
            模型路由
          </h2>
          <div className="space-y-3">
            {routes.map((r) => (
              <div
                key={r.task_type}
                className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
              >
                <span className="text-sm text-gray-700">
                  {getRouteLabel(r.task_type)}
                </span>
                <span className="text-sm font-medium text-gray-900">
                  {r.model_name}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Models */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">
          已配置模型
        </h2>
        {models.length === 0 ? (
          <p className="text-sm text-gray-500">
            暂无模型配置。请通过 API 添加模型。
          </p>
        ) : (
          <div className="space-y-4">
            {models.map((m) => (
              <div
                key={m.name}
                className="p-4 rounded-lg border border-gray-200"
              >
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="text-sm font-medium text-gray-900">
                      {m.name}
                    </span>
                    <span className="ml-2 text-xs text-gray-500">
                      {m.provider_type}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block w-2 h-2 rounded-full ${m.is_active ? "bg-green-500" : "bg-gray-300"}`}
                    />
                    <span className="text-xs text-gray-500">
                      {m.is_active ? "活跃" : "已禁用"}
                    </span>
                  </div>
                </div>
                <div className="text-xs text-gray-500 space-y-1">
                  <div>模型 ID: {m.model_id}</div>
                  {m.base_url && <div>Endpoint: {m.base_url}</div>}
                  {m.api_key_masked && <div>API Key: {m.api_key_masked}</div>}
                </div>
                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => handleTest(m.name)}
                    disabled={testing === m.name}
                    className="px-3 py-1 text-xs rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    {testing === m.name ? "测试中..." : "测试连通性"}
                  </button>
                  <button
                    onClick={() => handleDelete(m.name)}
                    className="px-3 py-1 text-xs rounded-md border border-red-200 text-red-600 hover:bg-red-50"
                  >
                    删除
                  </button>
                </div>
                {testResult[m.name] && (
                  <div
                    className={`mt-2 text-xs px-2 py-1 rounded ${testResult[m.name].success ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}
                  >
                    {testResult[m.name].message}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
