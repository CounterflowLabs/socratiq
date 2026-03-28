"use client";

import { useEffect, useState } from "react";
import {
  getModels,
  getModelTiers,
  updateModelTiers,
  deleteModel,
  testModel,
  createModel,
  getWhisperConfig,
  updateWhisperConfig,
  getBilibiliStatus,
  generateBilibiliQrcode,
  checkBilibiliQrcode,
  logoutBilibili,
} from "@/lib/api";
import type { ModelConfigResponse, ModelTierResponse, ModelTier, WhisperConfigResponse } from "@/lib/api";

const TIER_INFO: { tier: ModelTier; label: string; description: string }[] = [
  { tier: "primary", label: "主交互模型", description: "对话教学、工具调用" },
  { tier: "light", label: "轻量任务模型", description: "内容分析、翻译、摘要" },
  { tier: "strong", label: "复杂推理模型", description: "评估、诊断（可选，未配置时回退到主交互模型）" },
  { tier: "embedding", label: "向量计算模型", description: "RAG 检索、语义搜索" },
];

export default function SettingsPage() {
  const [models, setModels] = useState<ModelConfigResponse[]>([]);
  const [tiers, setTiers] = useState<ModelTierResponse[]>([]);
  const [tierEdits, setTierEdits] = useState<Record<ModelTier, string>>({
    primary: "",
    light: "",
    strong: "",
    embedding: "",
  });
  const [tierSaving, setTierSaving] = useState(false);
  const [tierMessage, setTierMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);
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
    model_type: "chat",
  });
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);
  const [whisperConfig, setWhisperConfig] = useState<WhisperConfigResponse | null>(null);
  const [whisperEdits, setWhisperEdits] = useState({
    mode: "api",
    api_base_url: "",
    api_model: "",
    api_key: "",
    local_model: "base",
  });
  const [whisperSaving, setWhisperSaving] = useState(false);
  const [whisperMessage, setWhisperMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [biliStatus, setBiliStatus] = useState<{ logged_in: boolean; dedeuserid?: string } | null>(null);
  const [biliQrcode, setBiliQrcode] = useState<string | null>(null);
  const [biliQrStatus, setBiliQrStatus] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [m, t, w, b] = await Promise.all([getModels(), getModelTiers(), getWhisperConfig(), getBilibiliStatus()]);
      setModels(m);
      setTiers(t);
      setWhisperConfig(w);
      setBiliStatus(b);
      setWhisperEdits({
        mode: w.mode || "api",
        api_base_url: w.api_base_url || "",
        api_model: w.api_model || "",
        api_key: "", // Don't populate - show placeholder with masked key
        local_model: w.local_model || "base",
      });
      // Initialize tier edits from current config
      const edits: Record<string, string> = { primary: "", light: "", strong: "", embedding: "" };
      for (const c of t) edits[c.tier] = c.model_name;
      setTierEdits(edits as Record<ModelTier, string>);
    } catch (e) {
      console.error("Failed to load settings:", e);
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveTiers() {
    setTierSaving(true);
    setTierMessage(null);
    try {
      const updates = TIER_INFO
        .filter(({ tier }) => tierEdits[tier])
        .map(({ tier }) => ({ tier, model_name: tierEdits[tier] }));
      const result = await updateModelTiers(updates);
      setTiers(result);
      setTierMessage({ type: "ok", text: "保存成功" });
    } catch (err) {
      setTierMessage({ type: "err", text: err instanceof Error ? err.message : "保存失败" });
    } finally {
      setTierSaving(false);
    }
  }

  async function handleSaveWhisper() {
    setWhisperSaving(true);
    setWhisperMessage(null);
    try {
      const updates: Record<string, string> = {};
      if (whisperEdits.mode) updates.mode = whisperEdits.mode;
      if (whisperEdits.api_base_url) updates.api_base_url = whisperEdits.api_base_url;
      if (whisperEdits.api_model) updates.api_model = whisperEdits.api_model;
      if (whisperEdits.api_key) updates.api_key = whisperEdits.api_key;
      if (whisperEdits.local_model) updates.local_model = whisperEdits.local_model;
      const result = await updateWhisperConfig(updates);
      setWhisperConfig(result);
      setWhisperEdits(prev => ({ ...prev, api_key: "" })); // Clear key field after save
      setWhisperMessage({ type: "ok", text: "保存成功" });
    } catch (err) {
      setWhisperMessage({ type: "err", text: err instanceof Error ? err.message : "保存失败" });
    } finally {
      setWhisperSaving(false);
    }
  }

  async function handleBiliLogin() {
    try {
      const result = await generateBilibiliQrcode();
      setBiliQrcode(result.qrcode_base64);
      setBiliQrStatus("waiting");
      // Start polling
      const poll = setInterval(async () => {
        try {
          const status = await checkBilibiliQrcode();
          setBiliQrStatus(status.status);
          if (status.status === "done") {
            clearInterval(poll);
            setBiliQrcode(null);
            setBiliQrStatus(null);
            setBiliStatus({ logged_in: true, dedeuserid: status.dedeuserid });
          } else if (status.status === "expired") {
            clearInterval(poll);
            setBiliQrcode(null);
            setBiliQrStatus("expired");
          }
        } catch {
          clearInterval(poll);
          setBiliQrcode(null);
          setBiliQrStatus(null);
        }
      }, 2000);
    } catch (e) {
      console.error("Failed to generate QR code:", e);
    }
  }

  async function handleBiliLogout() {
    try {
      await logoutBilibili();
      setBiliStatus({ logged_in: false });
    } catch (e) {
      console.error("Failed to logout:", e);
    }
  }

  const tiersChanged = TIER_INFO.some(({ tier }) => {
    const current = tiers.find((t) => t.tier === tier)?.model_name ?? "";
    return tierEdits[tier] !== current;
  });

  const modelsForTier = (tier: ModelTier) =>
    models.filter((m) =>
      tier === "embedding" ? m.model_type === "embedding" : m.model_type !== "embedding"
    );

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
        model_type: newModel.model_type,
      });
      setModels((prev) => [...prev, created]);
      setNewModel({
        name: "",
        provider_type: "anthropic",
        model_id: "",
        api_key: "",
        base_url: "",
        model_type: "chat",
      });
      setShowAddForm(false);
      // Reload tiers in case backend auto-assigned
      const t = await getModelTiers();
      setTiers(t);
      const edits: Record<string, string> = { ...tierEdits };
      for (const c of t) edits[c.tier] = c.model_name;
      setTierEdits(edits as Record<ModelTier, string>);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setAdding(false);
    }
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

      {/* Model Tiers */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">
          模型分级
        </h2>
        <div className="space-y-4">
          {TIER_INFO.map(({ tier, label, description }) => (
            <div key={tier}>
              {tier === "embedding" && (
                <div className="border-t border-gray-200 my-4 pt-2">
                  <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">向量模型</span>
                </div>
              )}
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm text-gray-700">{label}</label>
                {tier === "strong" && (
                  <span className="text-xs text-gray-400">可选</span>
                )}
              </div>
              <select
                value={tierEdits[tier]}
                onChange={(e) =>
                  setTierEdits((prev) => ({ ...prev, [tier]: e.target.value }))
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">
                  {tier === "strong" ? "未配置（回退到主交互模型）" : "未配置"}
                </option>
                {modelsForTier(tier).filter((m) => m.is_active).map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name} ({m.model_id})
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-400 mt-0.5">{description}</p>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={handleSaveTiers}
            disabled={tierSaving || !tiersChanged}
            className="px-4 py-2 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {tierSaving ? "保存中..." : "保存分级"}
          </button>
          {tierMessage && (
            <span
              className={`text-xs ${tierMessage.type === "ok" ? "text-green-600" : "text-red-600"}`}
            >
              {tierMessage.text}
            </span>
          )}
        </div>
      </div>

      {/* Whisper ASR Config */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">语音识别 (Whisper ASR)</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-700 mb-1">模式</label>
            <select
              value={whisperEdits.mode}
              onChange={(e) => setWhisperEdits(prev => ({ ...prev, mode: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="api">API（Groq / OpenAI 等）</option>
              <option value="local">本地模型</option>
            </select>
          </div>

          {whisperEdits.mode === "api" ? (
            <>
              <div>
                <label className="block text-sm text-gray-700 mb-1">API Base URL</label>
                <input
                  type="text"
                  value={whisperEdits.api_base_url}
                  onChange={(e) => setWhisperEdits(prev => ({ ...prev, api_base_url: e.target.value }))}
                  placeholder="https://api.groq.com/openai/v1"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-700 mb-1">模型</label>
                <input
                  type="text"
                  value={whisperEdits.api_model}
                  onChange={(e) => setWhisperEdits(prev => ({ ...prev, api_model: e.target.value }))}
                  placeholder="whisper-large-v3"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-700 mb-1">API Key</label>
                <input
                  type="password"
                  value={whisperEdits.api_key}
                  onChange={(e) => setWhisperEdits(prev => ({ ...prev, api_key: e.target.value }))}
                  placeholder={whisperConfig?.api_key_masked || "输入 API Key"}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {whisperConfig?.api_key_masked && !whisperEdits.api_key && (
                  <p className="text-xs text-gray-400 mt-1">当前: {whisperConfig.api_key_masked}（留空则不修改）</p>
                )}
              </div>
            </>
          ) : (
            <div>
              <label className="block text-sm text-gray-700 mb-1">本地模型大小</label>
              <select
                value={whisperEdits.local_model}
                onChange={(e) => setWhisperEdits(prev => ({ ...prev, local_model: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="tiny">tiny (最快)</option>
                <option value="base">base</option>
                <option value="small">small</option>
                <option value="medium">medium</option>
                <option value="large">large (最准)</option>
              </select>
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveWhisper}
              disabled={whisperSaving}
              className="px-4 py-2 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {whisperSaving ? "保存中..." : "保存配置"}
            </button>
            {whisperMessage && (
              <span className={`text-xs ${whisperMessage.type === "ok" ? "text-green-600" : "text-red-600"}`}>
                {whisperMessage.text}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Bilibili Account */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">B站账号</h2>
        <p className="text-xs text-gray-500 mb-4">登录 B 站账号以获取视频字幕（AI 字幕需要登录才能访问）</p>

        {biliStatus?.logged_in ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
              <span className="text-sm text-gray-700">已登录 {biliStatus.dedeuserid && `(UID: ${biliStatus.dedeuserid})`}</span>
            </div>
            <button
              onClick={handleBiliLogout}
              className="px-3 py-1.5 text-xs rounded-md border border-red-200 text-red-600 hover:bg-red-50"
            >
              退出登录
            </button>
          </div>
        ) : biliQrcode ? (
          <div className="text-center">
            <p className="text-sm text-gray-600 mb-3">
              {biliQrStatus === "waiting" && "请使用 B 站 App 扫描二维码"}
              {biliQrStatus === "scanned" && "已扫码，请在手机上确认登录"}
              {biliQrStatus === "expired" && "二维码已过期，请重新生成"}
            </p>
            {biliQrStatus !== "expired" && (
              <img
                src={`data:image/png;base64,${biliQrcode}`}
                alt="Bilibili QR Code"
                className="w-48 h-48 mx-auto border border-gray-200 rounded-lg"
              />
            )}
            {biliQrStatus === "expired" && (
              <button
                onClick={handleBiliLogin}
                className="px-4 py-2 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                重新生成
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={handleBiliLogin}
            className="px-4 py-2 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            扫码登录
          </button>
        )}
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
              <label className="block text-xs font-medium text-gray-600 mb-1">模型类型</label>
              <div className="flex gap-3">
                <label className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input type="radio" name="model_type" value="chat"
                    checked={newModel.model_type === "chat"}
                    onChange={() => setNewModel({ ...newModel, model_type: "chat" })}
                    className="accent-blue-600"
                  />
                  对话模型
                </label>
                <label className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input type="radio" name="model_type" value="embedding"
                    checked={newModel.model_type === "embedding"}
                    onChange={() => setNewModel({ ...newModel, model_type: "embedding" })}
                    className="accent-blue-600"
                  />
                  向量模型
                </label>
              </div>
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
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">
                      {m.name}
                    </span>
                    <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${
                      m.model_type === "embedding"
                        ? "bg-purple-50 text-purple-600"
                        : "bg-blue-50 text-blue-600"
                    }`}>
                      {m.model_type === "embedding" ? "向量" : "对话"}
                    </span>
                    <span className="text-xs text-gray-500">
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
