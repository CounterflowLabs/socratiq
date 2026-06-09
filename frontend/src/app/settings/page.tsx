"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  IcAlert,
  IcCheck,
  IcLoader,
  IcMoon,
  IcPlus,
  IcSun,
} from "@/components/icons";
import { Avatar } from "@/components/ui/avatar";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented";
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
import {
  DEEPSEEK_BASE_URL,
  DEEPSEEK_DEFAULT_CHAT_MODEL,
  DEEPSEEK_DEFAULT_MODEL_NAME,
} from "@/lib/model-provider-presets";
import { useLocaleStore, useT, type Density, type Lang } from "@/lib/i18n";

type ProviderType = "anthropic" | "openai" | "openai_compatible" | "codex";
type ModelType = "chat" | "embedding";
type ProviderPreset = ProviderType | "deepseek";

const providerPresets: Array<{
  id: ProviderPreset;
  label: string;
  providerType: ProviderType;
  chatOnly?: boolean;
  defaultName?: string;
  defaultModelId?: string;
  defaultBaseUrl?: string;
}> = [
  { id: "anthropic", label: "Anthropic", providerType: "anthropic" },
  { id: "codex", label: "Codex (ChatGPT login)", providerType: "codex", chatOnly: true },
  { id: "openai", label: "OpenAI", providerType: "openai" },
  {
    id: "deepseek",
    label: "DeepSeek",
    providerType: "openai_compatible",
    chatOnly: true,
    defaultName: DEEPSEEK_DEFAULT_MODEL_NAME,
    defaultModelId: DEEPSEEK_DEFAULT_CHAT_MODEL,
    defaultBaseUrl: DEEPSEEK_BASE_URL,
  },
  { id: "openai_compatible", label: "OpenAI compatible (custom)", providerType: "openai_compatible" },
];

function getProviderPreset(id: ProviderPreset) {
  return providerPresets.find((preset) => preset.id === id) ?? providerPresets[0];
}

type WhisperProtocol = "openai_compat" | "whispercpp" | "local";
type WhisperPresetId =
  | "groq"
  | "openai"
  | "siliconflow"
  | "whispercpp"
  | "openai_compat"
  | "local";

const whisperPresets: Array<{
  id: WhisperPresetId;
  label: string;
  protocol: WhisperProtocol;
  defaultBaseUrl?: string;
  defaultModel?: string;
  requiresKey?: boolean;
  hint?: string;
}> = [
  {
    id: "groq",
    label: "Groq · whisper-large-v3",
    protocol: "openai_compat",
    defaultBaseUrl: "https://api.groq.com/openai/v1",
    defaultModel: "whisper-large-v3",
    requiresKey: true,
  },
  {
    id: "openai",
    label: "OpenAI",
    protocol: "openai_compat",
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultModel: "whisper-1",
    requiresKey: true,
  },
  {
    id: "siliconflow",
    label: "SiliconFlow",
    protocol: "openai_compat",
    defaultBaseUrl: "https://api.siliconflow.cn/v1",
    defaultModel: "FunAudioLLM/SenseVoiceSmall",
    requiresKey: true,
  },
  {
    id: "whispercpp",
    label: "whisper.cpp (host, Metal/GPU)",
    protocol: "whispercpp",
    defaultBaseUrl: "http://host.docker.internal:8001",
    defaultModel: "",
    requiresKey: false,
    hint: "host whisper-server (see docs/whisper-setup.md). The backend container reaches it via host.docker.internal.",
  },
  {
    id: "openai_compat",
    label: "OpenAI compatible (custom URL)",
    protocol: "openai_compat",
    requiresKey: true,
  },
  {
    id: "local",
    label: "In-process Whisper ([whisper] extra)",
    protocol: "local",
    hint: "Runs in the backend image. CPU-only — not recommended for production.",
  },
];

function getWhisperPreset(id: string) {
  return (
    whisperPresets.find((preset) => preset.id === id) ??
    whisperPresets.find((preset) => preset.id === "openai_compat")!
  );
}

function guessLegacyPreset(baseUrl: string): WhisperPresetId {
  const url = baseUrl.toLowerCase();
  if (url.includes("groq.com")) return "groq";
  if (url.includes("openai.com")) return "openai";
  if (url.includes("siliconflow")) return "siliconflow";
  return "openai_compat";
}

const SECTIONS = [
  { id: "appearance", labelZh: "外观", labelEn: "Appearance" },
  { id: "llm", labelZh: "LLM 提供商", labelEn: "LLM providers" },
  { id: "routes", labelZh: "模型路由", labelEn: "Model routing" },
  { id: "sources", labelZh: "数据源", labelEn: "Data sources" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

export default function SettingsPage() {
  // useSearchParams() requires a Suspense boundary in the App Router.
  return (
    <Suspense fallback={null}>
      <SettingsPageContent />
    </Suspense>
  );
}

function SettingsPageContent() {
  const { t, lang } = useT();
  const searchParams = useSearchParams();
  const setLang = useLocaleStore((s) => s.setLang);
  const setDensity = useLocaleStore((s) => s.setDensity);
  const setTheme = useLocaleStore((s) => s.setTheme);
  const density = useLocaleStore((s) => s.density);
  const themePreference = useLocaleStore((s) => s.theme);

  const [activeSection, setActiveSection] = useState<SectionId>(() => {
    const requested = searchParams.get("section");
    return SECTIONS.some((s) => s.id === requested)
      ? (requested as SectionId)
      : "appearance";
  });

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
  const [providerPreset, setProviderPreset] = useState<ProviderPreset>("anthropic");
  const [newModel, setNewModel] = useState({
    name: "",
    provider_type: "anthropic" as ProviderType,
    model_type: "chat" as ModelType,
    model_id: "",
    api_key: "",
    base_url: "",
  });
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);

  const [biliStatus, setBiliStatus] = useState<{
    logged_in: boolean;
    dedeuserid?: string | null;
    source?: "db" | "env" | null;
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
    mode: "groq" as string,
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
          setBiliSuccess(
            lang === "zh"
              ? "B站登录成功，后续导入会优先使用这份登录态。"
              : "Bilibili logged in. Future imports will reuse this session.",
          );
          setBiliError("");
          return;
        }
        if (status.status === "expired") {
          setBiliQrcode(null);
          setBiliError(lang === "zh" ? "二维码已过期，请重新生成。" : "QR code expired. Regenerate to retry.");
        }
      } catch (err) {
        if (cancelled) return;
        setBiliQrcode(null);
        setBiliQrStatus(null);
        setBiliError(err instanceof Error ? err.message : "Bilibili check failed");
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), 1500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [biliQrcode, lang]);

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
      const storedMode = w.mode || "groq";
      const initialPreset =
        storedMode === "api"
          ? guessLegacyPreset(w.api_base_url || "")
          : (storedMode as WhisperPresetId);
      setWhisperEdits({
        mode: initialPreset,
        api_base_url: w.api_base_url || "",
        api_model: w.api_model || "",
        api_key: "",
        local_model: w.local_model || "base",
      });
      setRouteDrafts(
        Object.fromEntries(r.map((route) => [route.task_type, route.model_name])),
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
    if (!window.confirm(lang === "zh" ? `确定要删除模型「${name}」吗？此操作不可撤销。` : `Delete model "${name}"? This cannot be undone.`)) return;
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
        })),
      );
      setRoutes(updated);
      setRouteDrafts(
        Object.fromEntries(updated.map((route) => [route.task_type, route.model_name])),
      );
      setRouteSuccess(lang === "zh" ? "模型路由已更新" : "Model routes updated");
    } catch (err) {
      setRouteError(err instanceof Error ? err.message : "Failed to update routes");
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
      setProviderPreset("anthropic");
      setShowAddForm(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to add model");
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
      setWhisperMessage({ type: "ok", text: lang === "zh" ? "Whisper 配置已保存" : "Whisper config saved" });
    } catch (err) {
      setWhisperMessage({
        type: "err",
        text: err instanceof Error ? err.message : "Failed to save Whisper",
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
      setBiliError(err instanceof Error ? err.message : "QR generation failed");
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
      setBiliSuccess(lang === "zh" ? "已移除 B站登录态。" : "Bilibili session cleared.");
    } catch (err) {
      setBiliError(err instanceof Error ? err.message : "Logout failed");
    } finally {
      setBiliLoading(false);
    }
  }

  function getRouteLabel(taskType: string): string {
    const map: Record<string, { zh: string; en: string }> = {
      mentor_chat: { zh: "主交互", en: "Mentor chat" },
      content_analysis: { zh: "内容分析", en: "Content analysis" },
      evaluation: { zh: "复杂推理", en: "Evaluation" },
      embedding: { zh: "向量计算", en: "Embeddings" },
    };
    const entry = map[taskType];
    return entry ? entry[lang] : taskType;
  }

  function getRouteOptions(taskType: string): ModelConfigResponse[] {
    if (taskType === "embedding") {
      return models.filter((m) => m.model_type === "embedding");
    }
    return models.filter((m) => m.model_type !== "embedding");
  }

  function handleModelTypeChange(modelType: ModelType) {
    const nextPreset =
      modelType === "embedding" && getProviderPreset(providerPreset).chatOnly
        ? "openai_compatible"
        : providerPreset;
    const preset = getProviderPreset(nextPreset);
    setProviderPreset(nextPreset);
    setNewModel((prev) => ({
      ...prev,
      model_type: modelType,
      provider_type: preset.providerType,
      base_url:
        preset.defaultBaseUrl ??
        (preset.providerType === "openai_compatible" ? prev.base_url : ""),
    }));
  }

  function handleProviderPresetChange(presetId: ProviderPreset) {
    const preset = getProviderPreset(presetId);
    setProviderPreset(presetId);
    setNewModel((prev) => ({
      ...prev,
      name: preset.defaultName ?? prev.name,
      provider_type: preset.providerType,
      model_type: preset.chatOnly ? "chat" : prev.model_type,
      model_id: preset.defaultModelId ?? "",
      base_url: preset.defaultBaseUrl ?? "",
    }));
  }

  const hasRouteChanges = routes.some(
    (route) => (routeDrafts[route.task_type] || route.model_name) !== route.model_name,
  );

  const requiresApiKey = newModel.provider_type !== "codex";
  const supportsBaseUrl = newModel.provider_type === "openai_compatible";
  const isEmbeddingOnlyOpenAI =
    newModel.model_type === "embedding" && newModel.provider_type === "anthropic";

  return (
    <div style={{ padding: "32px 40px 80px", maxWidth: 1100, margin: "0 auto", width: "100%" }}>
      <PageHeader title={t("settings.title")} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "200px 1fr",
          gap: 40,
          alignItems: "flex-start",
        }}
      >
        <nav
          style={{
            position: "sticky",
            top: 24,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {SECTIONS.map((section) => {
            const active = activeSection === section.id;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => setActiveSection(section.id)}
                className="nav-item"
                style={{
                  fontSize: 13,
                  color: active ? "var(--ink)" : "var(--ink-3)",
                  fontWeight: active ? 500 : 400,
                  background: active ? "var(--surface-2)" : "transparent",
                }}
              >
                {lang === "zh" ? section.labelZh : section.labelEn}
              </button>
            );
          })}
        </nav>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-xl)" }}>
          {activeSection === "appearance" ? (
            <section>
              <h2
                className="serif"
                style={{ fontSize: 22, margin: "0 0 6px", fontWeight: 500 }}
              >
                {t("settings.sections.appearance")}
              </h2>
              <p style={{ fontSize: 13, color: "var(--ink-2)", margin: "0 0 20px", maxWidth: 560 }}>
                {lang === "zh"
                  ? "主题、语言、密度都会立即生效，并保存在浏览器本地。"
                  : "Theme, language, and density apply instantly and persist in this browser."}
              </p>

              <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                <SettingRow
                  label={t("settings.themeLabel")}
                  hint={lang === "zh" ? "系统主题会跟随操作系统设置" : "System follows your OS preference"}
                >
                  <SegmentedControl
                    ariaLabel={t("settings.themeLabel")}
                    value={themePreference}
                    onChange={(next) => setTheme(next)}
                    options={[
                      { v: "light", label: t("settings.themeLight"), icon: IcSun },
                      { v: "dark", label: t("settings.themeDark"), icon: IcMoon },
                      { v: "system", label: t("settings.themeSystem") },
                    ]}
                  />
                </SettingRow>

                <SettingRow label={t("settings.langLabel")}>
                  <SegmentedControl
                    ariaLabel={t("settings.langLabel")}
                    value={lang}
                    onChange={(next: Lang) => setLang(next)}
                    options={[
                      { v: "zh", label: "中文" },
                      { v: "en", label: "English" },
                    ]}
                  />
                </SettingRow>

                <SettingRow label={t("settings.densityLabel")}>
                  <SegmentedControl
                    ariaLabel={t("settings.densityLabel")}
                    value={density}
                    onChange={(next: Density) => setDensity(next)}
                    options={[
                      { v: "spacious", label: t("settings.densitySpacious") },
                      { v: "balanced", label: t("settings.densityBalanced") },
                      { v: "dense", label: t("settings.densityDense") },
                    ]}
                  />
                </SettingRow>
              </div>
            </section>
          ) : null}

          {activeSection === "llm" ? (
            <section>
              <h2
                className="serif"
                style={{ fontSize: 22, margin: "0 0 6px", fontWeight: 500 }}
              >
                {t("settings.sections.llm")}
              </h2>
              <p style={{ fontSize: 13, color: "var(--ink-2)", margin: "0 0 16px", maxWidth: 560 }}>
                {t("settings.llmDesc")}
              </p>

              {loading ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--ink-3)", fontSize: 13 }}>
                  <IcLoader size={14} className="spin" />
                  <span>{t("common.loading")}</span>
                </div>
              ) : (
                <>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {models.map((model) => (
                      <ProviderRow
                        key={model.name}
                        model={model}
                        testing={testing === model.name}
                        result={testResult[model.name]}
                        onTest={() => handleTest(model.name)}
                        onDelete={() => handleDelete(model.name)}
                      />
                    ))}
                  </div>

                  {showAddForm ? (
                    <form
                      onSubmit={handleAddModel}
                      className="card"
                      style={{
                        marginTop: 16,
                        padding: 18,
                        display: "flex",
                        flexDirection: "column",
                        gap: 12,
                        background: "var(--accent-soft)",
                        borderColor: "transparent",
                      }}
                    >
                      <Field label={lang === "zh" ? "名称" : "Name"}>
                        <input
                          className="input"
                          value={newModel.name}
                          onChange={(e) => setNewModel({ ...newModel, name: e.target.value })}
                          placeholder={lang === "zh" ? "例如 my-claude-sonnet" : "e.g. my-claude-sonnet"}
                          required
                        />
                      </Field>
                      <Field label={lang === "zh" ? "模型类型" : "Model type"}>
                        <select
                          className="input"
                          value={newModel.model_type}
                          onChange={(e) => handleModelTypeChange(e.target.value as ModelType)}
                        >
                          <option value="chat">{lang === "zh" ? "聊天 / 推理" : "Chat / reasoning"}</option>
                          <option value="embedding">{lang === "zh" ? "Embedding / 向量" : "Embedding"}</option>
                        </select>
                      </Field>
                      <Field label={lang === "zh" ? "Provider 预设" : "Provider preset"}>
                        <select
                          aria-label={lang === "zh" ? "Provider 预设" : "Provider preset"}
                          className="input"
                          value={providerPreset}
                          onChange={(e) =>
                            handleProviderPresetChange(e.target.value as ProviderPreset)
                          }
                        >
                          {providerPresets.map((preset) => (
                            <option
                              key={preset.id}
                              value={preset.id}
                              disabled={newModel.model_type === "embedding" && preset.chatOnly}
                            >
                              {preset.label}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label={lang === "zh" ? "模型 ID" : "Model ID"}>
                        <input
                          className="input"
                          value={newModel.model_id}
                          onChange={(e) => setNewModel({ ...newModel, model_id: e.target.value })}
                          placeholder={
                            newModel.model_type === "embedding"
                              ? "text-embedding-3-small"
                              : providerPreset === "deepseek"
                                ? DEEPSEEK_DEFAULT_CHAT_MODEL
                                : "claude-sonnet-4-20250514"
                          }
                          required
                        />
                      </Field>
                      {requiresApiKey ? (
                        <Field label="API Key">
                          <input
                            className="input"
                            type="password"
                            value={newModel.api_key}
                            onChange={(e) => setNewModel({ ...newModel, api_key: e.target.value })}
                            placeholder="sk-…"
                          />
                        </Field>
                      ) : null}
                      {supportsBaseUrl ? (
                        <Field label="Base URL">
                          <input
                            className="input"
                            value={newModel.base_url}
                            onChange={(e) => setNewModel({ ...newModel, base_url: e.target.value })}
                            placeholder="https://api.deepseek.com/v1"
                          />
                        </Field>
                      ) : null}
                      {isEmbeddingOnlyOpenAI ? (
                        <p style={{ fontSize: 12, color: "var(--warn)" }}>
                          {lang === "zh"
                            ? "embedding 需要 OpenAI 兼容 provider，已自动切换。"
                            : "Embedding requires an OpenAI-compatible provider; switched for you."}
                        </p>
                      ) : null}
                      {addError ? (
                        <p style={{ fontSize: 12, color: "var(--error)" }}>{addError}</p>
                      ) : null}
                      <div style={{ display: "flex", gap: 8 }}>
                        <button type="submit" disabled={adding} className="btn btn-accent btn-sm">
                          {adding ? t("common.loading") : t("common.save")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => setShowAddForm(false)}
                        >
                          {t("common.cancel")}
                        </button>
                      </div>
                    </form>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      style={{ marginTop: 16 }}
                      onClick={() => setShowAddForm(true)}
                    >
                      <IcPlus size={12} />
                      <span>{t("settings.addProvider")}</span>
                    </button>
                  )}
                </>
              )}
            </section>
          ) : null}

          {activeSection === "routes" ? (
            <section>
              <h2
                className="serif"
                style={{ fontSize: 22, margin: "0 0 6px", fontWeight: 500 }}
              >
                {lang === "zh" ? "模型路由" : "Model routing"}
              </h2>
              <p style={{ fontSize: 13, color: "var(--ink-2)", margin: "0 0 16px", maxWidth: 560 }}>
                {lang === "zh"
                  ? "为每类任务挑一个具体模型 — 主交互/分析/复杂推理/向量。"
                  : "Pick a model per task type — chat / analysis / reasoning / embeddings."}
              </p>

              <div className="card" style={{ padding: 18 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {routes.map((route) => (
                    <div
                      key={route.task_type}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr auto",
                        gap: 12,
                        alignItems: "center",
                      }}
                    >
                      <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
                        {getRouteLabel(route.task_type)}
                      </span>
                      <select
                        className="input"
                        style={{ width: 280 }}
                        value={routeDrafts[route.task_type] || route.model_name}
                        onChange={(e) => {
                          setRouteDrafts((prev) => ({
                            ...prev,
                            [route.task_type]: e.target.value,
                          }));
                          setRouteSuccess("");
                        }}
                      >
                        {getRouteOptions(route.task_type).map((m) => (
                          <option key={m.name} value={m.name}>
                            {m.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
                <div
                  style={{
                    marginTop: 16,
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <button
                    type="button"
                    onClick={handleSaveRoutes}
                    disabled={savingRoutes || !hasRouteChanges}
                    className="btn btn-accent btn-sm"
                  >
                    {savingRoutes
                      ? lang === "zh"
                        ? "保存中…"
                        : "Saving…"
                      : lang === "zh"
                        ? "保存路由"
                        : "Save routes"}
                  </button>
                  {routeError ? (
                    <span style={{ fontSize: 12, color: "var(--error)" }}>{routeError}</span>
                  ) : null}
                  {routeSuccess ? (
                    <span style={{ fontSize: 12, color: "var(--sage)" }}>{routeSuccess}</span>
                  ) : null}
                </div>
              </div>
            </section>
          ) : null}

          {activeSection === "sources" ? (
            <section style={{ display: "flex", flexDirection: "column", gap: 28 }}>
              <div>
                <h2
                  className="serif"
                  style={{ fontSize: 22, margin: "0 0 6px", fontWeight: 500 }}
                >
                  {lang === "zh" ? "B站登录" : "Bilibili"}
                </h2>
                <p
                  style={{
                    fontSize: 13,
                    color: "var(--ink-2)",
                    margin: "0 0 16px",
                    maxWidth: 560,
                  }}
                >
                  {lang === "zh"
                    ? "用于抓取需要登录态才能访问的 Bilibili 字幕和视频信息。"
                    : "Used to fetch subtitles and metadata that Bilibili gates behind login."}
                </p>

                <div className="card" style={{ padding: 18 }}>
                  {biliStatus?.logged_in ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      <div
                        className="card-quiet"
                        style={{
                          background: "var(--sage-soft)",
                          color: "var(--sage-ink)",
                          borderColor: "transparent",
                          padding: "10px 14px",
                          fontSize: 13,
                        }}
                      >
                        {lang === "zh" ? "已连接 B站账号" : "Connected to Bilibili"}
                        {biliStatus.dedeuserid ? `（UID: ${biliStatus.dedeuserid}）` : ""}
                      </div>
                      <div>
                        <button
                          type="button"
                          onClick={handleBilibiliLogout}
                          disabled={biliLoading}
                          className="btn btn-danger btn-sm"
                        >
                          {biliLoading
                            ? t("common.loading")
                            : lang === "zh"
                              ? "退出登录"
                              : "Sign out"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      <div>
                        <button
                          type="button"
                          onClick={handleBilibiliLogin}
                          disabled={biliLoading}
                          className="btn btn-accent btn-sm"
                        >
                          {biliLoading
                            ? lang === "zh"
                              ? "生成中…"
                              : "Generating…"
                            : biliQrStatus === "expired"
                              ? lang === "zh"
                                ? "重新生成二维码"
                                : "Regenerate QR"
                              : lang === "zh"
                                ? "扫码登录 B站"
                                : "Scan to sign in"}
                        </button>
                      </div>
                      {biliQrcode ? (
                        <div className="card-quiet" style={{ padding: 18 }}>
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              alignItems: "center",
                              gap: 12,
                            }}
                          >
                            <img
                              src={`data:image/png;base64,${biliQrcode}`}
                              alt="Bilibili QR code"
                              style={{
                                width: 192,
                                height: 192,
                                borderRadius: "var(--r)",
                                border: "1px solid var(--border)",
                              }}
                            />
                            <div style={{ fontSize: 12, color: "var(--ink-3)", textAlign: "center" }}>
                              {biliQrStatus === "scanned"
                                ? lang === "zh"
                                  ? "已扫码，请在手机上确认登录。"
                                  : "Scanned. Confirm on your phone."
                                : lang === "zh"
                                  ? "请使用哔哩哔哩 App 扫码登录。"
                                  : "Scan with the Bilibili app to sign in."}
                            </div>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  )}
                  {biliError ? (
                    <p style={{ marginTop: 12, fontSize: 12, color: "var(--error)" }}>
                      {biliError}
                    </p>
                  ) : null}
                  {biliSuccess ? (
                    <p style={{ marginTop: 12, fontSize: 12, color: "var(--sage)" }}>
                      {biliSuccess}
                    </p>
                  ) : null}
                </div>
              </div>

              <div>
                <h2
                  className="serif"
                  style={{ fontSize: 22, margin: "0 0 6px", fontWeight: 500 }}
                >
                  Whisper
                </h2>
                <p
                  style={{
                    fontSize: 13,
                    color: "var(--ink-2)",
                    margin: "0 0 16px",
                    maxWidth: 560,
                  }}
                >
                  {lang === "zh"
                    ? "当视频没有现成字幕时，会回退到这里配置的 ASR。"
                    : "Used as the ASR fallback when a source ships no subtitles."}
                </p>
                <div
                  className="card"
                  style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}
                >
                  <Field label="Provider">
                    <select
                      className="input"
                      value={whisperEdits.mode}
                      onChange={(e) => {
                        const next = getWhisperPreset(e.target.value);
                        setWhisperEdits((prev) => {
                          const isAutoUrl =
                            !prev.api_base_url ||
                            whisperPresets.some((p) => p.defaultBaseUrl === prev.api_base_url);
                          const isAutoModel =
                            !prev.api_model ||
                            whisperPresets.some((p) => p.defaultModel === prev.api_model);
                          return {
                            ...prev,
                            mode: next.id,
                            api_base_url: isAutoUrl ? next.defaultBaseUrl ?? "" : prev.api_base_url,
                            api_model: isAutoModel ? next.defaultModel ?? "" : prev.api_model,
                          };
                        });
                      }}
                    >
                      {whisperPresets.map((preset) => (
                        <option key={preset.id} value={preset.id}>
                          {preset.label}
                        </option>
                      ))}
                    </select>
                    {getWhisperPreset(whisperEdits.mode).hint ? (
                      <p style={{ marginTop: 6, fontSize: 11, color: "var(--ink-3)" }}>
                        {getWhisperPreset(whisperEdits.mode).hint}
                      </p>
                    ) : null}
                  </Field>

                  {getWhisperPreset(whisperEdits.mode).protocol === "local" ? (
                    <Field label={lang === "zh" ? "本地模型大小" : "Local model size"}>
                      <select
                        className="input"
                        value={whisperEdits.local_model}
                        onChange={(e) =>
                          setWhisperEdits((prev) => ({ ...prev, local_model: e.target.value }))
                        }
                      >
                        <option value="tiny">tiny</option>
                        <option value="base">base</option>
                        <option value="small">small</option>
                        <option value="medium">medium</option>
                        <option value="large">large</option>
                      </select>
                    </Field>
                  ) : (
                    <>
                      <Field
                        label={
                          getWhisperPreset(whisperEdits.mode).protocol === "whispercpp"
                            ? "Server URL"
                            : "API Base URL"
                        }
                      >
                        <input
                          className="input"
                          value={whisperEdits.api_base_url}
                          onChange={(e) =>
                            setWhisperEdits((prev) => ({
                              ...prev,
                              api_base_url: e.target.value,
                            }))
                          }
                          placeholder={
                            getWhisperPreset(whisperEdits.mode).defaultBaseUrl ||
                            "https://example.com/v1"
                          }
                        />
                      </Field>
                      {getWhisperPreset(whisperEdits.mode).protocol === "openai_compat" ? (
                        <Field label={lang === "zh" ? "模型" : "Model"}>
                          <input
                            className="input"
                            value={whisperEdits.api_model}
                            onChange={(e) =>
                              setWhisperEdits((prev) => ({
                                ...prev,
                                api_model: e.target.value,
                              }))
                            }
                            placeholder={
                              getWhisperPreset(whisperEdits.mode).defaultModel || "whisper-large-v3"
                            }
                          />
                        </Field>
                      ) : null}
                      {getWhisperPreset(whisperEdits.mode).requiresKey ? (
                        <Field label="API Key">
                          <input
                            className="input"
                            type="password"
                            value={whisperEdits.api_key}
                            onChange={(e) =>
                              setWhisperEdits((prev) => ({ ...prev, api_key: e.target.value }))
                            }
                            placeholder={whisperConfig?.api_key_masked || "sk-…"}
                          />
                          {whisperConfig?.api_key_masked && !whisperEdits.api_key ? (
                            <p
                              style={{
                                marginTop: 4,
                                fontSize: 11,
                                color: "var(--ink-4)",
                              }}
                            >
                              {lang === "zh"
                                ? `当前: ${whisperConfig.api_key_masked}（留空表示不修改）`
                                : `Current: ${whisperConfig.api_key_masked} (leave blank to keep)`}
                            </p>
                          ) : null}
                        </Field>
                      ) : null}
                    </>
                  )}

                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <button
                      type="button"
                      onClick={handleSaveWhisper}
                      disabled={whisperSaving}
                      className="btn btn-accent btn-sm"
                    >
                      {whisperSaving
                        ? t("common.loading")
                        : lang === "zh"
                          ? "保存 Whisper 配置"
                          : "Save Whisper"}
                    </button>
                    {whisperMessage ? (
                      <span
                        style={{
                          fontSize: 12,
                          color:
                            whisperMessage.type === "ok" ? "var(--sage)" : "var(--error)",
                        }}
                      >
                        {whisperMessage.text}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 24,
        alignItems: "center",
      }}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--ink)" }}>{label}</div>
        {hint ? (
          <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 2 }}>{hint}</div>
        ) : null}
      </div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12, color: "var(--ink-2)", fontWeight: 500 }}>{label}</span>
      {children}
    </label>
  );
}

function ProviderRow({
  model,
  testing,
  result,
  onTest,
  onDelete,
}: {
  model: ModelConfigResponse;
  testing: boolean;
  result?: { success: boolean; message: string };
  onTest: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className="card"
      style={{
        padding: 14,
        display: "grid",
        gridTemplateColumns: "32px 1fr auto",
        alignItems: "center",
        gap: 14,
      }}
    >
      <Avatar name={model.name.slice(0, 1)} size={32} accent="ink" />
      <div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{model.name}</div>
        <div
          style={{
            fontSize: 11,
            color: "var(--ink-3)",
            display: "flex",
            gap: 8,
            marginTop: 2,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <span className="mono">{model.model_id}</span>
          <span className="chip chip-mono">{model.provider_type}</span>
          <span className="chip chip-mono">
            {model.model_type === "embedding" ? "embed" : "chat"}
          </span>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              color: model.is_active ? "var(--sage)" : "var(--ink-3)",
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: model.is_active ? "var(--sage)" : "var(--ink-3)",
              }}
            />
            {model.is_active ? "active" : "off"}
          </span>
        </div>
        {model.api_key_masked ? (
          <Eyebrow>{model.api_key_masked}</Eyebrow>
        ) : null}
        {result ? (
          <div
            style={{
              marginTop: 6,
              fontSize: 11,
              color: result.success ? "var(--sage)" : "var(--error)",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {result.success ? <IcCheck size={11} /> : <IcAlert size={11} />}
            <span>{result.message}</span>
          </div>
        ) : null}
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <button
          type="button"
          onClick={onTest}
          disabled={testing}
          className="btn btn-outline btn-sm"
        >
          {testing
            ? "…"
            : "test"}
        </button>
        <button type="button" onClick={onDelete} className="btn btn-danger btn-sm">
          ×
        </button>
      </div>
    </div>
  );
}
