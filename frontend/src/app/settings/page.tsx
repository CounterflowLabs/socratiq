"use client";

import { useEffect, useState } from "react";
import {
  getModels,
  getModelRoutes,
  deleteModel,
  testModel,
  createModel,
} from "@/lib/api";
import type { ModelConfigResponse, ModelRouteResponse } from "@/lib/api";

export default function SettingsPage() {
  const [models, setModels] = useState<ModelConfigResponse[]>([]);
  const [routes, setRoutes] = useState<ModelRouteResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<
    Record<string, { success: boolean; message: string }>
  >({});
  const [showAddForm, setShowAddForm] = useState(false);
  const [newModel, setNewModel] = useState({
    name: "",
    provider_type: "anthropic",
    model_id: "",
    api_key: "",
    base_url: "",
  });
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [m, r] = await Promise.all([
        getModels(),
        getModelRoutes(),
      ]);
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

  async function handleAddModel(e: React.FormEvent) {
    e.preventDefault();
    setAddError("");
    setAdding(true);
    try {
      const created = await createModel({
        name: newModel.name,
        provider_type: newModel.provider_type,
        model_id: newModel.model_id,
        api_key: newModel.api_key || undefined,
        base_url: newModel.base_url || undefined,
      });
      setModels((prev) => [...prev, created]);
      setNewModel({
        name: "",
        provider_type: "anthropic",
        model_id: "",
        api_key: "",
        base_url: "",
      });
      setShowAddForm(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setAdding(false);
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
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6">
        <h1 className="text-xl font-bold text-gray-900 mb-6">设置</h1>
        <div className="text-sm text-gray-500">加载中...</div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6">
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
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">已配置模型</h2>
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            {showAddForm ? "取消" : "添加模型"}
          </button>
        </div>

        {/* Add Model Form */}
        {showAddForm && (
          <form
            onSubmit={handleAddModel}
            className="mb-4 p-4 rounded-lg border border-blue-200 bg-blue-50 space-y-3"
          >
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                名称
              </label>
              <input
                type="text"
                value={newModel.name}
                onChange={(e) =>
                  setNewModel({ ...newModel, name: e.target.value })
                }
                placeholder="例如 my-claude-sonnet"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                Provider 类型
              </label>
              <select
                value={newModel.provider_type}
                onChange={(e) =>
                  setNewModel({ ...newModel, provider_type: e.target.value })
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="anthropic">Anthropic</option>
                <option value="openai">OpenAI</option>
                <option value="openai_compatible">OpenAI 兼容</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                模型 ID
              </label>
              <input
                type="text"
                value={newModel.model_id}
                onChange={(e) =>
                  setNewModel({ ...newModel, model_id: e.target.value })
                }
                placeholder="例如 claude-sonnet-4-20250514"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                API Key（可选）
              </label>
              <input
                type="password"
                value={newModel.api_key}
                onChange={(e) =>
                  setNewModel({ ...newModel, api_key: e.target.value })
                }
                placeholder="sk-..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                Base URL（可选，用于 OpenAI 兼容 Provider）
              </label>
              <input
                type="text"
                value={newModel.base_url}
                onChange={(e) =>
                  setNewModel({ ...newModel, base_url: e.target.value })
                }
                placeholder="https://api.deepseek.com/v1"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            {addError && <p className="text-xs text-red-500">{addError}</p>}
            <button
              type="submit"
              disabled={adding}
              className="px-4 py-2 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {adding ? "添加中..." : "保存"}
            </button>
          </form>
        )}

        {models.length === 0 && !showAddForm ? (
          <p className="text-sm text-gray-500">
            暂无模型配置。点击「添加模型」开始配置。
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
                    className="px-3 py-2 min-h-[44px] text-xs rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    {testing === m.name ? "测试中..." : "测试连通性"}
                  </button>
                  <button
                    onClick={() => handleDelete(m.name)}
                    className="px-3 py-2 min-h-[44px] text-xs rounded-md border border-red-200 text-red-600 hover:bg-red-50"
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
