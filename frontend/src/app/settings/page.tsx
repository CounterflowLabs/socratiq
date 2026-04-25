"use client";

import { useEffect, useState } from "react";
import {
  getModels,
  getModelRoutes,
  deleteModel,
  testModel,
  createModel,
  updateModelRoutes,
  getWhisperConfig,
  updateWhisperConfig,
  getBilibiliStatus,
  generateBilibiliQrcode,
  checkBilibiliQrcode,
  logoutBilibili,
} from "@/lib/api";
import type { ModelConfigResponse, ModelRouteResponse } from "@/lib/api";

export default function SettingsPage() {
  const [models, setModels] = useState<ModelConfigResponse[]>([]);
  const [routes, setRoutes] = useState<ModelRouteResponse[]>([]);
  const [routeDrafts, setRouteDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [savingRoutes, setSavingRoutes] = useState(false);
  const [routeError, setRouteError] = useState("");
  const [routeSuccess, setRouteSuccess] = useState("");
  const [testResult, setTestResult] = useState<
    Record<string, { success: boolean; message: string }>
  >({});
  const [showAddForm, setShowAddForm] = useState(false);
  const [newModel, setNewModel] = useState({
    name: "",
    provider_type: "anthropic",
    model_type: "chat",
    model_id: "",
    api_key: "",
    base_url: "",
  });
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);
  const [biliStatus, setBiliStatus] = useState<{
    logged_in: boolean;
    dedeuserid?: string;
  } | null>(null);
  const [biliQrcode, setBiliQrcode] = useState<string | null>(null);
  const [biliQrStatus, setBiliQrStatus] = useState<string | null>(null);
  const [biliLoading, setBiliLoading] = useState(false);
  const [biliError, setBiliError] = useState("");
  const [biliSuccess, setBiliSuccess] = useState("");
  const [whisperConfig, setWhisperConfig] = useState<{
    mode: string;
    api_base_url?: string;
    api_model?: string;
    api_key_masked?: string | null;
    local_model?: string;
  } | null>(null);
  const [whisperEdits, setWhisperEdits] = useState({
    mode: "api",
    api_base_url: "",
    api_model: "",
    api_key: "",
    local_model: "base",
  });
  const [whisperSaving, setWhisperSaving] = useState(false);
  const [whisperMessage, setWhisperMessage] = useState<{
    type: "ok" | "err";
    text: string;
  } | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (!biliQrcode) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const status = await checkBilibiliQrcode();
        if (cancelled) return;

        setBiliQrStatus(status.status);

        if (status.status === "done") {
          setBiliQrcode(null);
          setBiliStatus({ logged_in: true, dedeuserid: status.dedeuserid });
          setBiliSuccess("B站登录成功，后续导入会优先使用这份登录态。");
          setBiliError("");
          return;
        }

        if (status.status === "expired") {
          setBiliQrcode(null);
          setBiliError("二维码已过期，请重新生成。");
        }
      } catch (err) {
        if (cancelled) return;
        setBiliQrcode(null);
        setBiliQrStatus(null);
        setBiliError(err instanceof Error ? err.message : "无法检查 B站登录状态");
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 1500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [biliQrcode]);

  async function loadData() {
    setLoading(true);
    try {
      const [m, r, b, w] = await Promise.all([
        getModels(),
        getModelRoutes(),
        getBilibiliStatus(),
        getWhisperConfig(),
      ]);
      setModels(m);
      setRoutes(r);
      setBiliStatus(b);
      setWhisperConfig(w);
      setWhisperEdits({
        mode: w.mode || "api",
        api_base_url: w.api_base_url || "",
        api_model: w.api_model || "",
        api_key: "",
        local_model: w.local_model || "base",
      });
      setRouteDrafts(
        Object.fromEntries(r.map((route) => [route.task_type, route.model_name]))
      );
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
    if (!window.confirm(`确定要删除模型「${name}」吗？此操作不可撤销。`)) {
      return;
    }
    try {
      await deleteModel(name);
      setModels((prev) => prev.filter((m) => m.name !== name));
    } catch (e) {
      console.error("Failed to delete model:", e);
    }
  }

  async function handleSaveRoutes() {
    setSavingRoutes(true);
    setRouteError("");
    setRouteSuccess("");
    try {
      const updated = await updateModelRoutes(
        routes.map((route) => ({
          task_type: route.task_type,
          model_name: routeDrafts[route.task_type] || route.model_name,
        }))
      );
      setRoutes(updated);
      setRouteDrafts(
        Object.fromEntries(updated.map((route) => [route.task_type, route.model_name]))
      );
      setRouteSuccess("模型路由已更新");
    } catch (err) {
      setRouteError(err instanceof Error ? err.message : "更新路由失败");
    } finally {
      setSavingRoutes(false);
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
        model_type: newModel.model_type,
        model_id: newModel.model_id,
        api_key: newModel.api_key || undefined,
        base_url: newModel.base_url || undefined,
      });
      setModels((prev) => [...prev, created]);
      setNewModel({
        name: "",
        provider_type: "anthropic",
        model_type: "chat",
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

  async function handleSaveWhisper() {
    setWhisperSaving(true);
    setWhisperMessage(null);
    try {
      const result = await updateWhisperConfig({
        mode: whisperEdits.mode,
        api_base_url: whisperEdits.api_base_url || undefined,
        api_model: whisperEdits.api_model || undefined,
        api_key: whisperEdits.api_key || undefined,
        local_model: whisperEdits.local_model || undefined,
      });
      setWhisperConfig(result);
      setWhisperEdits((prev) => ({ ...prev, api_key: "" }));
      setWhisperMessage({ type: "ok", text: "Whisper 配置已保存" });
    } catch (err) {
      setWhisperMessage({
        type: "err",
        text: err instanceof Error ? err.message : "保存 Whisper 配置失败",
      });
    } finally {
      setWhisperSaving(false);
    }
  }

  async function handleBilibiliLogin() {
    setBiliLoading(true);
    setBiliError("");
    setBiliSuccess("");
    try {
      const result = await generateBilibiliQrcode();
      setBiliQrcode(result.qrcode_base64);
      setBiliQrStatus("waiting");
    } catch (err) {
      setBiliError(err instanceof Error ? err.message : "生成 B站二维码失败");
    } finally {
      setBiliLoading(false);
    }
  }

  async function handleBilibiliLogout() {
    setBiliLoading(true);
    setBiliError("");
    setBiliSuccess("");
    try {
      await logoutBilibili();
      setBiliStatus({ logged_in: false });
      setBiliQrcode(null);
      setBiliQrStatus(null);
      setBiliSuccess("已移除 B站登录态。");
    } catch (err) {
      setBiliError(err instanceof Error ? err.message : "退出 B站登录失败");
    } finally {
      setBiliLoading(false);
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

  function getRouteOptions(taskType: string): ModelConfigResponse[] {
    if (taskType === "embedding") {
      return models.filter((model) => model.model_type === "embedding");
    }
    return models.filter((model) => model.model_type !== "embedding");
  }

  const hasRouteChanges = routes.some(
    (route) => (routeDrafts[route.task_type] || route.model_name) !== route.model_name
  );

  const requiresApiKey = newModel.provider_type !== "codex";
  const supportsBaseUrl =
    newModel.provider_type === "openai_compatible";
  const isEmbeddingOnlyOpenAI =
    newModel.model_type === "embedding" && newModel.provider_type === "anthropic";

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6">
        <h1 className="text-xl font-bold mb-6" style={{ color: "var(--text)" }}>设置</h1>
        <div className="text-sm" style={{ color: "var(--text-secondary)" }}>加载中...</div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6">
      <h1 className="text-xl font-bold mb-6" style={{ color: "var(--text)" }}>设置</h1>

      {/* Model Routes */}
      {routes.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
          <div className="flex items-center justify-between mb-4 gap-3">
            <h2 className="text-sm font-semibold text-gray-900">
              模型路由
            </h2>
            <button
              onClick={handleSaveRoutes}
              disabled={savingRoutes || !hasRouteChanges}
              className="px-3 py-2 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {savingRoutes ? "保存中..." : "保存路由"}
            </button>
          </div>
          <div className="space-y-3">
            {routes.map((r) => (
              <div
                key={r.task_type}
                className="flex flex-col gap-2 py-2 border-b border-gray-100 last:border-0 md:flex-row md:items-center md:justify-between"
              >
                <span className="text-sm text-gray-700">
                  {getRouteLabel(r.task_type)}
                </span>
                <select
                  value={routeDrafts[r.task_type] || r.model_name}
                  onChange={(e) => {
                    setRouteDrafts((prev) => ({
                      ...prev,
                      [r.task_type]: e.target.value,
                    }));
                    setRouteSuccess("");
                  }}
                  className="w-full md:w-72 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {getRouteOptions(r.task_type).map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          {routeError && (
            <div className="mt-4 text-xs text-red-600 whitespace-pre-wrap break-words">
              {routeError}
            </div>
          )}
          {routeSuccess && (
            <div className="mt-4 text-xs text-green-700">
              {routeSuccess}
            </div>
          )}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">B站登录</h2>
            <p className="mt-1 text-xs text-gray-500">
              用于抓取需要登录态才能访问的 Bilibili 字幕和视频信息。
            </p>
          </div>
          <div className="text-xs text-gray-500">
            {biliStatus?.logged_in ? "已登录" : "未登录"}
          </div>
        </div>

        {biliStatus?.logged_in ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
              已连接 B站账号
              {biliStatus.dedeuserid ? `（UID: ${biliStatus.dedeuserid}）` : ""}
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleBilibiliLogout}
                disabled={biliLoading}
                className="px-3 py-2 min-h-[44px] text-xs rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {biliLoading ? "处理中..." : "退出登录"}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleBilibiliLogin}
                disabled={biliLoading}
                className="px-3 py-2 min-h-[44px] text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {biliLoading ? "生成中..." : biliQrStatus === "expired" ? "重新生成二维码" : "扫码登录 B站"}
              </button>
            </div>

            {biliQrcode && (
              <div className="rounded-lg border border-gray-200 p-4">
                <div className="flex flex-col items-center gap-3">
                  <img
                    src={`data:image/png;base64,${biliQrcode}`}
                    alt="Bilibili QR code"
                    className="h-48 w-48 rounded-lg border border-gray-200"
                  />
                  <div className="text-xs text-center text-gray-500">
                    {biliQrStatus === "scanned"
                      ? "已扫码，请在手机上确认登录。"
                      : "请使用哔哩哔哩 App 扫码登录。"}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {biliError && (
          <div className="mt-4 text-xs text-red-600 whitespace-pre-wrap break-words">
            {biliError}
          </div>
        )}
        {biliSuccess && (
          <div className="mt-4 text-xs text-green-700">
            {biliSuccess}
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-gray-900">Whisper 语音识别</h2>
          <p className="mt-1 text-xs text-gray-500">
            当视频没有现成字幕时，会回退到这里配置的 ASR。
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs text-gray-600 mb-1">模式</label>
            <select
              value={whisperEdits.mode}
              onChange={(e) =>
                setWhisperEdits((prev) => ({ ...prev, mode: e.target.value }))
              }
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="api">API（Groq / OpenAI / SiliconFlow 等）</option>
              <option value="local">本地模型</option>
            </select>
          </div>

          {whisperEdits.mode === "api" ? (
            <>
              <div>
                <label className="block text-xs text-gray-600 mb-1">API Base URL</label>
                <input
                  type="text"
                  value={whisperEdits.api_base_url}
                  onChange={(e) =>
                    setWhisperEdits((prev) => ({
                      ...prev,
                      api_base_url: e.target.value,
                    }))
                  }
                  placeholder="https://api.groq.com/openai/v1"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">模型</label>
                <input
                  type="text"
                  value={whisperEdits.api_model}
                  onChange={(e) =>
                    setWhisperEdits((prev) => ({
                      ...prev,
                      api_model: e.target.value,
                    }))
                  }
                  placeholder="whisper-large-v3 或 whisper-1"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">API Key</label>
                <input
                  type="password"
                  value={whisperEdits.api_key}
                  onChange={(e) =>
                    setWhisperEdits((prev) => ({
                      ...prev,
                      api_key: e.target.value,
                    }))
                  }
                  placeholder={whisperConfig?.api_key_masked || "输入 API Key"}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {whisperConfig?.api_key_masked && !whisperEdits.api_key && (
                  <p className="mt-1 text-xs text-gray-400">
                    当前: {whisperConfig.api_key_masked}（留空表示不修改）
                  </p>
                )}
              </div>
            </>
          ) : (
            <div>
              <label className="block text-xs text-gray-600 mb-1">本地模型大小</label>
              <select
                value={whisperEdits.local_model}
                onChange={(e) =>
                  setWhisperEdits((prev) => ({
                    ...prev,
                    local_model: e.target.value,
                  }))
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="tiny">tiny（最快）</option>
                <option value="base">base</option>
                <option value="small">small</option>
                <option value="medium">medium</option>
                <option value="large">large（最准）</option>
              </select>
              <p className="mt-1 text-xs text-gray-400">
                当前 Docker 镜像还没有内置本地 Whisper 依赖；如果使用本地模式，需要额外安装模型运行时。
              </p>
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveWhisper}
              disabled={whisperSaving}
              className="px-3 py-2 min-h-[44px] text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {whisperSaving ? "保存中..." : "保存 Whisper 配置"}
            </button>
            {whisperMessage && (
              <span
                className={`text-xs ${
                  whisperMessage.type === "ok" ? "text-green-600" : "text-red-600"
                }`}
              >
                {whisperMessage.text}
              </span>
            )}
          </div>
        </div>
      </div>

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
                模型类型
              </label>
              <select
                value={newModel.model_type}
                onChange={(e) =>
                  setNewModel({
                    ...newModel,
                    model_type: e.target.value,
                    provider_type:
                      e.target.value === "embedding"
                        ? "openai_compatible"
                        : newModel.provider_type,
                  })
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="chat">聊天 / 推理模型</option>
                <option value="embedding">Embedding / 向量模型</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                Provider 类型
              </label>
              <select
                value={newModel.provider_type}
                onChange={(e) =>
                  setNewModel({
                    ...newModel,
                    provider_type: e.target.value,
                    model_type:
                      e.target.value === "codex" ? "chat" : newModel.model_type,
                  })
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="anthropic" disabled={newModel.model_type === "embedding"}>
                  Anthropic
                </option>
                <option value="codex" disabled={newModel.model_type === "embedding"}>
                  Codex（ChatGPT 登录）
                </option>
                <option value="openai">OpenAI</option>
                <option value="openai_compatible">OpenAI 兼容</option>
              </select>
              {newModel.provider_type === "codex" && (
                <p className="mt-1 text-xs text-gray-400">
                  Codex 通过 backend 容器里的官方 CLI 登录，不需要 API Key 和 Base URL。
                </p>
              )}
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
                placeholder={
                  newModel.model_type === "embedding"
                    ? "例如 text-embedding-3-small 或 nomic-embed-text"
                    : newModel.provider_type === "codex"
                    ? "例如 gpt-5-codex"
                    : "例如 claude-sonnet-4-20250514"
                }
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            {requiresApiKey && (
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
            )}
            {supportsBaseUrl && (
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
            )}
            {isEmbeddingOnlyOpenAI && (
              <p className="text-xs text-amber-600">
                embedding 需要 OpenAI / OpenAI 兼容 provider，已自动切换。
              </p>
            )}
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
                    <span className="ml-2 text-xs text-gray-500">
                      {m.model_type === "embedding" ? "Embedding" : "Chat"}
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
