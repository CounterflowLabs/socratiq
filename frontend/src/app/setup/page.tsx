"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Brain, Server, Key, ChevronDown, ChevronUp, Loader, CheckCircle, ExternalLink, AlertCircle } from "lucide-react";
import { getSetupStatus, createModel, testModel } from "@/lib/api";

type Step = "loading" | "ollama" | "manual" | "done";

export default function SetupPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("loading");
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [selectedOllamaModel, setSelectedOllamaModel] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Manual form state
  const [provider, setProvider] = useState<"anthropic" | "openai">("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [modelId, setModelId] = useState("");
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    getSetupStatus()
      .then((status) => {
        if (status.has_models) {
          router.replace("/");
          return;
        }
        if (status.ollama_available) {
          setOllamaModels(status.ollama_models);
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
  }, [router]);

  async function handleOllamaSetup() {
    if (!selectedOllamaModel) return;
    setSaving(true);
    setError("");
    try {
      await createModel({
        name: `ollama-${selectedOllamaModel.replace(/[^a-zA-Z0-9]/g, "-")}`,
        provider_type: "openai_compatible",
        model_id: selectedOllamaModel,
        base_url: "http://localhost:11434/v1",
      });
      setSuccess("配置成功！正在跳转...");
      setTimeout(() => router.replace("/"), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "配置失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  async function handleManualSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setTestResult(null);
    try {
      const defaultModelId = modelId ||
        (provider === "anthropic" ? "claude-haiku-4-20250414" : "gpt-4o-mini");
      const created = await createModel({
        name: `${provider}-default`,
        provider_type: provider,
        model_id: defaultModelId,
        api_key: apiKey || undefined,
      });
      // Auto-test after creation
      setTesting(true);
      try {
        const result = await testModel(created.name);
        setTestResult(result);
        if (result.success) {
          setSuccess("配置成功！正在跳转...");
          setTimeout(() => router.replace("/"), 1200);
        }
      } catch {
        setTestResult({ success: false, message: "连通性测试失败" });
      } finally {
        setTesting(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
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
          <h1 className="text-xl font-bold text-gray-900">欢迎使用 LearnMentor</h1>
          <p className="text-sm text-gray-500 mt-2">首先配置一个 AI 模型，才能开始学习</p>
        </div>

        {success && (
          <div className="mb-4 flex items-center gap-2 px-4 py-3 rounded-lg bg-green-50 text-green-700 text-sm">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />
            {success}
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
              <div className="mb-3 flex items-center gap-2 text-xs text-red-600">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                {error}
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
                    setProvider(e.target.value as "anthropic" | "openai");
                    setModelId("");
                    setTestResult(null);
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
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
                      : "gpt-4o-mini"
                  }
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {error && (
                <div className="flex items-center gap-2 text-xs text-red-600">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  {error}
                </div>
              )}

              {testResult && (
                <div
                  className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg ${
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
