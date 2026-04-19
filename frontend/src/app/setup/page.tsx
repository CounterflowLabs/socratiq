"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Brain, Server, Key, ChevronDown, ChevronUp, Loader, CheckCircle, ExternalLink, AlertCircle } from "lucide-react";
import {
  getSetupStatus,
  createModel,
  testModel,
  startCodexLogin,
  getCodexLoginSession,
} from "@/lib/api";

type Step = "loading" | "ollama" | "manual" | "done";

function formatSetupError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string" && error) {
    return error;
  }
  return fallback;
}

function slugifyModelName(value: string): string {
  const normalized = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "model";
}

function openInNewWindow(url: string) {
  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (opened) {
    opened.opener = null;
  }
}

export default function SetupPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("loading");
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [selectedOllamaModel, setSelectedOllamaModel] = useState("");
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("http://localhost:11434/v1");
  const [useOllamaEmbedding, setUseOllamaEmbedding] = useState(false);
  const [ollamaEmbeddingModelId, setOllamaEmbeddingModelId] = useState("nomic-embed-text");
  const [showManual, setShowManual] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [codexAvailable, setCodexAvailable] = useState(false);
  const [codexLoggedIn, setCodexLoggedIn] = useState(false);
  const [codexStatusMessage, setCodexStatusMessage] = useState("");
  const [codexModels, setCodexModels] = useState<
    Array<{ id: string; display_name: string; description?: string }>
  >([]);
  const [selectedCodexModel, setSelectedCodexModel] = useState("");
  const [codexError, setCodexError] = useState("");
  const [codexLoginSession, setCodexLoginSession] = useState<{
    session_id?: string | null;
    status: string;
    verification_url?: string | null;
    user_code?: string | null;
    message?: string | null;
    logged_in: boolean;
  } | null>(null);
  const [startingCodexLogin, setStartingCodexLogin] = useState(false);

  // Manual form state
  const [provider, setProvider] = useState<"anthropic" | "openai" | "openai_compatible">("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [modelId, setModelId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [useManualEmbedding, setUseManualEmbedding] = useState(false);
  const [manualEmbeddingModelId, setManualEmbeddingModelId] = useState("");
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);

  async function createOrReuseModel(input: {
    name: string;
    provider_type: "anthropic" | "openai" | "openai_compatible" | "codex";
    model_id: string;
    model_type: "chat" | "embedding";
    api_key?: string;
    base_url?: string;
  }): Promise<{ name: string }> {
    try {
      const created = await createModel(input);
      return { name: created.name };
    } catch (err) {
      const message = formatSetupError(err, "");
      if (message.includes("already exists") || message.includes("已存在")) {
        return { name: input.name };
      }
      throw err;
    }
  }

  async function configureEmbeddingModel(input: {
    name: string;
    provider_type: "openai" | "openai_compatible";
    model_id: string;
    api_key?: string;
    base_url?: string;
  }): Promise<{ success: boolean; message: string }> {
    const created = await createOrReuseModel({
      ...input,
      model_type: "embedding",
    });
    return testModel(created.name);
  }

  function finishWithEmbeddingWarning(message: string) {
    setSuccess("主模型已配置成功，正在前往设置页继续处理向量模型...");
    setError(message);
    setTimeout(() => router.replace("/settings"), 1800);
  }

  function applySetupStatus(status: Awaited<ReturnType<typeof getSetupStatus>>) {
    setCodexAvailable(status.codex_available);
    setCodexLoggedIn(status.codex_logged_in);
    setCodexStatusMessage(status.codex_status_message || "");
    setCodexModels(status.codex_models || []);
    setCodexError(status.codex_error || "");
    if (status.codex_models.length > 0) {
      setSelectedCodexModel((current) =>
        current && status.codex_models.some((model) => model.id === current)
          ? current
          : status.codex_models[0].id
      );
    }
  }

  async function refreshSetupStatus() {
    const status = await getSetupStatus();
    applySetupStatus(status);
    return status;
  }

  useEffect(() => {
    refreshSetupStatus()
      .then((status) => {
        if (status.ollama_available) {
          setOllamaModels(status.ollama_models);
          if (status.ollama_base_url) {
            setOllamaBaseUrl(status.ollama_base_url);
          }
          if (status.ollama_models.length > 0) {
            setSelectedOllamaModel(status.ollama_models[0]);
          }
          setStep("ollama");
        } else {
          setStep("manual");
        }
      })
      .catch(() => {
        setStep("manual");
      });
  }, []);

  useEffect(() => {
    if (!codexLoginSession?.session_id) return;
    if (!["pending", "waiting_for_user"].includes(codexLoginSession.status)) return;

    const timer = window.setTimeout(async () => {
      try {
        const next = await getCodexLoginSession(codexLoginSession.session_id as string);
        setCodexLoginSession(next);
        if (next.status === "completed" && next.logged_in) {
          await refreshSetupStatus();
          setSuccess("Codex 已完成 ChatGPT 登录。现在可以选择模型了。");
        } else if (next.status === "failed") {
          setCodexError(next.message || "Codex 登录失败");
        }
      } catch (err) {
        setCodexError(formatSetupError(err, "无法刷新 Codex 登录状态"));
      }
    }, 1500);

    return () => window.clearTimeout(timer);
  }, [codexLoginSession]);

  async function handleOllamaSetup() {
    if (!selectedOllamaModel) return;
    setSaving(true);
    setError("");
    setSuccess("");
    setTestResult(null);
    try {
      await createOrReuseModel({
        name: `ollama-${selectedOllamaModel.replace(/[^a-zA-Z0-9]/g, "-")}`,
        provider_type: "openai_compatible",
        model_id: selectedOllamaModel,
        model_type: "chat",
        base_url: ollamaBaseUrl,
      });
      if (useOllamaEmbedding && ollamaEmbeddingModelId.trim()) {
        try {
          const embeddingResult = await configureEmbeddingModel({
            name: `ollama-embedding-${slugifyModelName(ollamaEmbeddingModelId)}`,
            provider_type: "openai_compatible",
            model_id: ollamaEmbeddingModelId.trim(),
            base_url: ollamaBaseUrl,
          });
          if (!embeddingResult.success) {
            finishWithEmbeddingWarning(embeddingResult.message);
            return;
          }
        } catch (err) {
          finishWithEmbeddingWarning(
            formatSetupError(
              err,
              "向量模型配置失败，请确认已执行 ollama pull nomic-embed-text"
            )
          );
          return;
        }
      }
      setSuccess(
        useOllamaEmbedding && ollamaEmbeddingModelId.trim()
          ? "主模型与向量模型配置成功！正在跳转..."
          : "配置成功！正在跳转..."
      );
      setTimeout(() => router.replace("/"), 1000);
    } catch (err) {
      setError(formatSetupError(err, "配置 Ollama 失败，请检查后端 API 与 Ollama 服务状态"));
    } finally {
      setSaving(false);
    }
  }

  async function handleManualSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    setTestResult(null);
    try {
      const defaultModelId = modelId ||
        (provider === "anthropic" ? "claude-haiku-4-20250414"
          : provider === "openai" ? "gpt-4o-mini"
          : "deepseek-chat");
      const created = await createOrReuseModel({
        name: `${provider}-default`,
        provider_type: provider,
        model_id: defaultModelId,
        model_type: "chat",
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
      });
      // Auto-test after creation
      setTesting(true);
      try {
        const result = await testModel(created.name);
        setTestResult(result);
        if (result.success) {
          if (useManualEmbedding && manualEmbeddingModelId.trim()) {
            if (provider === "anthropic") {
              finishWithEmbeddingWarning(
                "Anthropic 不提供 embedding API。请改用 OpenAI / OpenAI 兼容向量模型，或稍后在 Settings 中单独添加。"
              );
              return;
            }
            try {
              const embeddingResult = await configureEmbeddingModel({
                name: `${provider}-embedding-${slugifyModelName(manualEmbeddingModelId)}`,
                provider_type: provider,
                model_id: manualEmbeddingModelId.trim(),
                api_key: apiKey || undefined,
                base_url: baseUrl || undefined,
              });
              if (!embeddingResult.success) {
                finishWithEmbeddingWarning(embeddingResult.message);
                return;
              }
            } catch (err) {
              finishWithEmbeddingWarning(
                formatSetupError(
                  err,
                  "向量模型配置失败，请检查模型 ID、Base URL 和 API Key"
                )
              );
              return;
            }
          }
          setSuccess("配置成功！正在跳转...");
          setTimeout(() => router.replace("/"), 1200);
        }
      } catch (err) {
        setTestResult({
          success: false,
          message: formatSetupError(err, "连通性测试失败，请检查 Base URL、模型 ID 和 API Key"),
        });
      } finally {
        setTesting(false);
      }
    } catch (err) {
      setError(formatSetupError(err, "保存失败，请检查后端 API 状态"));
    } finally {
      setSaving(false);
    }
  }

  async function handleStartCodexLogin() {
    setStartingCodexLogin(true);
    setCodexError("");
    setSuccess("");
    try {
      const session = await startCodexLogin();
      setCodexLoginSession(session);
      if (session.status === "completed" && session.logged_in) {
        await refreshSetupStatus();
        setSuccess("Codex 已登录，可以直接选择模型。");
      }
    } catch (err) {
      setCodexError(formatSetupError(err, "无法启动 Codex 登录流程"));
    } finally {
      setStartingCodexLogin(false);
    }
  }

  async function handleCodexSetup() {
    if (!selectedCodexModel) return;
    setSaving(true);
    setError("");
    setSuccess("");
    setCodexError("");
    try {
      const created = await createOrReuseModel({
        name: `codex-${slugifyModelName(selectedCodexModel)}`,
        provider_type: "codex",
        model_id: selectedCodexModel,
        model_type: "chat",
      });
      const result = await testModel(created.name);
      if (!result.success) {
        setCodexError(result.message);
        return;
      }
      finishWithEmbeddingWarning(
        "Codex 主模型已配置成功。向量模型不能使用 Codex，请在 Settings 中单独添加 OpenAI / OpenAI 兼容 embedding 模型。"
      );
    } catch (err) {
      setCodexError(formatSetupError(err, "Codex 模型配置失败"));
    } finally {
      setSaving(false);
    }
  }

  if (step === "loading") {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex items-center gap-2 text-gray-500">
          <Loader className="w-5 h-5 animate-spin" />
          <span className="text-sm">检测环境...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-blue-50 flex items-center justify-center mx-auto mb-4">
            <Brain className="w-7 h-7 text-blue-600" />
          </div>
          <h1 className="text-xl font-bold text-gray-900">欢迎使用 Socratiq</h1>
          <p className="text-sm text-gray-500 mt-2">首先配置一个 AI 模型，才能开始学习</p>
        </div>

        {success && (
          <div className="mb-4 flex items-center gap-2 px-4 py-3 rounded-lg bg-green-50 text-green-700 text-sm">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />
            {success}
          </div>
        )}

        {codexAvailable && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center">
                <Brain className="w-4 h-4 text-slate-700" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-gray-900">使用 ChatGPT 登录 Codex</h2>
                <p className="text-xs text-gray-500">通过官方 Codex CLI / app-server 接入，不需要 API Key</p>
              </div>
            </div>

            <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-xs text-gray-600 whitespace-pre-wrap break-words">
              {codexLoggedIn ? (
                <span className="flex items-start gap-2 text-green-700">
                  <CheckCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                  已登录{codexStatusMessage ? `：${codexStatusMessage}` : ""}
                </span>
              ) : (
                codexStatusMessage || "尚未登录 Codex。"
              )}
            </div>

            {!codexLoggedIn && (
              <>
                <button
                  onClick={handleStartCodexLogin}
                  disabled={startingCodexLogin}
                  className="w-full py-2.5 text-sm font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors mb-3"
                >
                  {startingCodexLogin ? (
                    <span className="flex items-center justify-center gap-2">
                      <Loader className="w-4 h-4 animate-spin" />
                      启动登录中...
                    </span>
                  ) : "开始 ChatGPT 登录"}
                </button>

                {codexLoginSession?.verification_url && codexLoginSession?.user_code && (
                  <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-3 text-xs text-blue-900 space-y-2">
                    <div>
                      1.{" "}
                      <button
                        type="button"
                        onClick={() => openInNewWindow(codexLoginSession.verification_url as string)}
                        className="inline-flex items-center gap-1 text-blue-700 underline underline-offset-2 hover:text-blue-800"
                      >
                        在新窗口打开验证页
                        <ExternalLink className="w-3 h-3" />
                      </button>
                      <div className="mt-1 break-all text-[11px] text-blue-700/80">
                        {codexLoginSession.verification_url}
                      </div>
                    </div>
                    <div>
                      2. 输入一次性验证码：
                      <code className="ml-1 rounded bg-white px-1.5 py-0.5 font-mono text-sm">
                        {codexLoginSession.user_code}
                      </code>
                    </div>
                    <div className="text-blue-700">
                      {codexLoginSession.message || "等待你在浏览器完成登录..."}
                    </div>
                  </div>
                )}
              </>
            )}

            {codexLoggedIn && codexModels.length > 0 && (
              <>
                <label className="block text-xs text-gray-600 mb-1.5">选择 Codex 模型</label>
                <select
                  value={selectedCodexModel}
                  onChange={(e) => setSelectedCodexModel(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 mb-2"
                >
                  {codexModels.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.display_name}
                    </option>
                  ))}
                </select>
                {selectedCodexModel && (
                  <p className="text-xs text-gray-400 mb-4">
                    {codexModels.find((model) => model.id === selectedCodexModel)?.description ||
                      "Codex 会作为聊天 / 推理模型接入，embedding 仍需单独配置。"}
                  </p>
                )}
                <button
                  onClick={handleCodexSetup}
                  disabled={saving || !selectedCodexModel}
                  className="w-full py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {saving ? (
                    <span className="flex items-center justify-center gap-2">
                      <Loader className="w-4 h-4 animate-spin" />
                      配置 Codex 中...
                    </span>
                  ) : "使用 Codex"}
                </button>
              </>
            )}

            {codexLoggedIn && codexModels.length === 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-700">
                已登录 Codex，但还没拿到可用模型列表。{codexError || "请稍后刷新，或检查 backend 容器日志。"}
              </div>
            )}

            {codexError && (
              <div className="mt-3 flex items-start gap-2 text-xs text-red-600 whitespace-pre-wrap break-words">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                {codexError}
              </div>
            )}
          </div>
        )}

        {/* Ollama detected */}
        {step === "ollama" && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-9 h-9 rounded-lg bg-green-50 flex items-center justify-center">
                <Server className="w-4 h-4 text-green-600" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-gray-900">检测到本地 Ollama</h2>
                <p className="text-xs text-gray-500">免费、本地运行，数据不离开设备</p>
              </div>
            </div>

            {ollamaModels.length > 0 ? (
              <>
                <label className="block text-xs text-gray-600 mb-1.5">选择模型</label>
                <select
                  value={selectedOllamaModel}
                  onChange={(e) => setSelectedOllamaModel(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 mb-4"
                >
                  {ollamaModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </>
            ) : (
              <div className="mb-4 px-3 py-2 rounded-lg bg-amber-50 text-amber-700 text-xs">
                Ollama 已运行，但未找到已下载的模型。请先运行 <code className="font-mono">ollama pull qwen2.5</code> 下载一个模型。
              </div>
            )}

            {error && (
              <div className="mb-3 flex items-start gap-2 text-xs text-red-600 whitespace-pre-wrap break-words">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                {error}
              </div>
            )}

            <label className="flex items-start gap-2 mb-3 text-xs text-gray-700">
              <input
                type="checkbox"
                checked={useOllamaEmbedding}
                onChange={(e) => setUseOllamaEmbedding(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                同时配置向量模型（推荐，用于 RAG 检索）
              </span>
            </label>

            {useOllamaEmbedding && (
              <div className="mb-4">
                <label className="block text-xs text-gray-600 mb-1.5">
                  向量模型 ID
                </label>
                <input
                  type="text"
                  value={ollamaEmbeddingModelId}
                  onChange={(e) => setOllamaEmbeddingModelId(e.target.value)}
                  placeholder="nomic-embed-text"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-400 mt-1">
                  推荐：<code className="font-mono">nomic-embed-text</code>。如未安装，请先运行{" "}
                  <code className="font-mono">ollama pull nomic-embed-text</code>
                </p>
              </div>
            )}

            <button
              onClick={handleOllamaSetup}
              disabled={saving || ollamaModels.length === 0}
              className="w-full py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader className="w-4 h-4 animate-spin" /> 配置中...
                </span>
              ) : "使用 Ollama"}
            </button>
          </div>
        )}

        {/* Option: install Ollama (shown when not detected) */}
        {step === "manual" && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-lg bg-gray-50 flex items-center justify-center">
                <Server className="w-4 h-4 text-gray-600" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-gray-900">安装 Ollama（免费，本地运行）</h2>
                <p className="text-xs text-gray-500">无需 API Key，数据不离开设备</p>
              </div>
            </div>
            <ol className="text-xs text-gray-600 space-y-1.5 mb-4 ml-1">
              <li>1. 前往 <a href="https://ollama.ai" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-0.5">ollama.ai <ExternalLink className="w-3 h-3" /></a> 下载安装</li>
              <li>2. 运行 <code className="font-mono bg-gray-100 px-1 rounded">ollama pull qwen2.5</code> 下载模型</li>
              <li>3. 刷新此页面</li>
            </ol>
            <button
              onClick={() => window.location.reload()}
              className="w-full py-2 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
            >
              刷新检测
            </button>
          </div>
        )}

        {/* Divider + manual API Key option */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <button
            onClick={() => setShowManual(!showManual)}
            className="w-full flex items-center justify-between px-6 py-4 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
                <Key className="w-4 h-4 text-blue-600" />
              </div>
              <span className="font-medium">使用 API Key</span>
            </div>
            {showManual ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
          </button>

          {showManual && (
            <form onSubmit={handleManualSave} className="px-6 pb-6 space-y-3 border-t border-gray-100">
              <div className="pt-4">
                <label className="block text-xs text-gray-600 mb-1.5">Provider</label>
                <select
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value as "anthropic" | "openai" | "openai_compatible");
                    setModelId("");
                    setBaseUrl("");
                    setTestResult(null);
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
                  <option value="openai_compatible">OpenAI 兼容（DeepSeek / 通义千问 / Moonshot 等）</option>
                </select>
              </div>

              <div>
                <label className="block text-xs text-gray-600 mb-1.5">API Key</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={provider === "anthropic" ? "sk-ant-..." : "sk-..."}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {provider === "openai_compatible" && (
                <div>
                  <label className="block text-xs text-gray-600 mb-1.5">
                    Base URL <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="url"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://api.deepseek.com/v1"
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <p className="text-xs text-gray-400 mt-1">
                    DeepSeek: https://api.deepseek.com/v1 · 通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1 · Moonshot: https://api.moonshot.cn/v1
                  </p>
                </div>
              )}

              <div>
                <label className="block text-xs text-gray-600 mb-1.5">
                  模型 ID（可选，默认使用推荐模型）
                </label>
                <input
                  type="text"
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                  placeholder={
                    provider === "anthropic"
                      ? "claude-haiku-4-20250414"
                      : provider === "openai"
                      ? "gpt-4o-mini"
                      : "deepseek-chat"
                  }
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-3">
                <label className="flex items-start gap-2 text-xs text-gray-700">
                  <input
                    type="checkbox"
                    checked={useManualEmbedding}
                    onChange={(e) => setUseManualEmbedding(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>同时配置向量模型（推荐，用于 RAG 检索）</span>
                </label>

                {useManualEmbedding && (
                  <div className="mt-3">
                    <label className="block text-xs text-gray-600 mb-1.5">
                      向量模型 ID
                    </label>
                    <input
                      type="text"
                      value={manualEmbeddingModelId}
                      onChange={(e) => setManualEmbeddingModelId(e.target.value)}
                      placeholder={
                        provider === "openai"
                          ? "text-embedding-3-small"
                          : provider === "openai_compatible"
                          ? "nomic-embed-text / bge-m3 / text-embedding-3-small"
                          : "Anthropic 需要单独的 embedding provider"
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <p className="text-xs text-gray-400 mt-1 whitespace-pre-wrap">
                      {provider === "anthropic"
                        ? "Anthropic 不提供 embedding API。完成后可在 Settings 中单独添加 OpenAI / OpenAI 兼容向量模型。"
                        : "将复用上面的 Provider、API Key 和 Base URL 来配置 embedding 模型。"}
                    </p>
                  </div>
                )}
              </div>

              {error && (
                <div className="flex items-start gap-2 text-xs text-red-600 whitespace-pre-wrap break-words">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  {error}
                </div>
              )}

              {testResult && (
                <div
                  className={`flex items-start gap-2 text-xs px-3 py-2 rounded-lg whitespace-pre-wrap break-words ${
                    testResult.success
                      ? "bg-green-50 text-green-700"
                      : "bg-red-50 text-red-700"
                  }`}
                >
                  {testResult.success ? (
                    <CheckCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  ) : (
                    <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  )}
                  {testResult.message}
                </div>
              )}

              <button
                type="submit"
                disabled={saving || testing}
                className="w-full py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {saving || testing ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader className="w-4 h-4 animate-spin" />
                    {testing ? "测试连通性..." : "保存中..."}
                  </span>
                ) : "保存并测试"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
