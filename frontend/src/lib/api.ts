/** API client for Socratiq backend. */

const API_BASE = "/api/v1";
const nativeFetch = globalThis.fetch.bind(globalThis);

function formatFetchError(url: string, error: unknown): Error {
  const reason = error instanceof Error ? error.message : String(error);
  return new Error(
    [
      `无法连接后端 API：${url}`,
      `原始错误：${reason}`,
      "请确认 Docker 中 backend 容器正在运行，并检查 /health 是否正常。",
    ].join("\n")
  );
}

async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const url = typeof input === "string" ? input : input.toString();
  try {
    return await nativeFetch(input, init);
  } catch (error) {
    throw formatFetchError(url, error);
  }
}

async function responseError(res: Response): Promise<Error> {
  const body = await res.text();
  let detail = body.trim();

  if (detail) {
    try {
      const parsed = JSON.parse(detail);
      if (typeof parsed.detail === "string") {
        detail = parsed.detail;
      } else if (parsed.detail) {
        detail = JSON.stringify(parsed.detail);
      } else {
        detail = JSON.stringify(parsed);
      }
    } catch {
      // Keep the plain response body.
    }
  }

  return new Error(
    [
      `API 请求失败：${res.status} ${res.statusText}`,
      `URL：${res.url || "unknown"}`,
      `详情：${detail || "响应体为空"}`,
    ].join("\n")
  );
}

// ─── Source APIs ───────────────────────────────────────

export interface SourceTaskSummary {
  task_type: string;
  status: string;
  stage?: string | null;
  error_summary?: string | null;
  celery_task_id?: string | null;
}

export interface SourceResponse {
  id: string;
  type: string;
  url?: string;
  title?: string;
  status: string;
  metadata_: Record<string, unknown>;
  task_id?: string;
  latest_processing_task?: SourceTaskSummary | null;
  latest_course_task?: SourceTaskSummary | null;
  course_count: number;
  latest_course_id: string | null;
  created_at: string;
  updated_at: string;
}

export async function createSourceFromURL(
  url: string,
  sourceType?: string,
  title?: string
): Promise<SourceResponse> {
  const form = new FormData();
  form.append("url", url);
  if (sourceType) form.append("source_type", sourceType);
  if (title) form.append("title", title);

  const res = await apiFetch(`${API_BASE}/sources`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function createSourceFromFile(
  file: File,
  title?: string
): Promise<SourceResponse> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);

  const res = await apiFetch(`${API_BASE}/sources`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function listSources(): Promise<{
  items: SourceResponse[];
  total: number;
}> {
  const res = await apiFetch(`${API_BASE}/sources`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getSource(id: string): Promise<SourceResponse> {
  const res = await apiFetch(`${API_BASE}/sources/${id}`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Course APIs ───────────────────────────────────────

export interface SectionResponse {
  id: string;
  title: string;
  order_index?: number;
  source_id?: string;
  source_start?: string;
  source_end?: string;
  content: Record<string, unknown>;
  difficulty: number;
}

export interface SourceSummary {
  id: string;
  url: string | null;
  type: string;
}

export interface CourseResponse {
  id: string;
  title: string;
  description?: string;
  parent_id?: string | null;
  regeneration_directive?: string | null;
  version_index: number;
  created_at: string;
  updated_at: string;
}

export interface CourseDetailResponse extends CourseResponse {
  sources: SourceSummary[];
  sections: SectionResponse[];
  active_regeneration_task_id?: string | null;
}

export interface RegenerateCourseResponse {
  task_id: string;
  parent_course_id: string;
}

export interface RegenerationStatus {
  status: "pending" | "running" | "success" | "failure";
  stage?: string | null;
  current?: number | null;
  total?: number | null;
  course_id?: string;
  parent_course_id?: string;
  error?: string;
}

export interface LessonConcept {
  label: string;
  description?: string | null;
}

export interface GraphCard {
  current: string[];
  prerequisites: string[];
  unlocks: string[];
  section_anchor?: string | number | null;
}

export type LabMode = "inline" | "none";

export interface LessonBlock {
  type:
    | "intro_card"
    | "prose"
    | "diagram"
    | "code_example"
    | "concept_relation"
    | "practice_trigger"
    | "recap"
    | "next_step";
  title?: string | null;
  body?: string | null;
  concepts?: LessonConcept[];
  code?: string | null;
  language?: string | null;
  diagram_type?: string | null;
  diagram_content?: string | null;
  metadata?: Record<string, string | number | boolean | null>;
}

export interface LessonSectionContent {
  heading: string;
  content: string;
  timestamp: number;
  code_snippets: Array<{ language: string; code: string; context: string }>;
  key_concepts: string[];
  diagrams: Array<{ type: string; title: string; content: string }>;
  interactive_steps: {
    title: string;
    steps: Array<{ label: string; detail: string; code?: string | null }>;
  } | null;
}

export interface LessonContent {
  title: string;
  summary: string;
  sections: LessonSectionContent[];
  blocks?: LessonBlock[] | null;
}

export async function generateCourse(
  sourceIds: string[],
  title?: string
): Promise<CourseResponse> {
  const res = await apiFetch(`${API_BASE}/courses/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_ids: sourceIds, title }),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function listCourses(): Promise<{
  items: CourseResponse[];
  total: number;
}> {
  const res = await apiFetch(`${API_BASE}/courses`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getCourse(id: string): Promise<CourseDetailResponse> {
  const res = await apiFetch(`${API_BASE}/courses/${id}`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function regenerateCourse(
  courseId: string,
  directive?: string
): Promise<RegenerateCourseResponse> {
  const res = await apiFetch(`${API_BASE}/courses/${courseId}/regenerate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directive: directive ?? null }),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getRegenerationStatus(
  taskId: string
): Promise<RegenerationStatus> {
  const res = await apiFetch(`${API_BASE}/courses/regenerations/${taskId}`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function clearCourseRegeneration(courseId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/courses/${courseId}/regeneration`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404) throw await responseError(res);
}

// ─── Chat APIs (SSE) ──────────────────────────────────

export interface Citation {
  chunk_id: string;
  source_id: string | null;
  source_title: string | null;
  source_type: string | null;
  source_url: string | null;
  text: string;
  start_time: number | null;
  end_time: number | null;
  page_start: number | null;
}

export interface ChatStreamEvent {
  event: "text_delta" | "tool_start" | "tool_end" | "message_end" | "citations" | "error";
  text?: string;
  conversation_id?: string;
  message?: string;
  tool?: string;
  citations?: Citation[];
}

interface StreamChatOptions {
  message: string;
  conversationId?: string;
  courseId?: string;
  sectionId?: string;
  signal?: AbortSignal;
}

export async function* streamChat(opts: StreamChatOptions): AsyncGenerator<ChatStreamEvent> {
  const { streamSSE } = await import("./sse");

  for await (const evt of streamSSE(
    `${API_BASE}/chat`,
    {
      message: opts.message,
      conversation_id: opts.conversationId,
      course_id: opts.courseId,
      section_id: opts.sectionId,
    },
    opts.signal
  )) {
    try {
      const data = JSON.parse(evt.data);
      yield { event: evt.event as ChatStreamEvent["event"], ...data };
    } catch {
      // skip malformed events
    }
  }
}

// ─── Conversation APIs ────────────────────────────────

export interface ConversationResponse {
  id: string;
  course_id?: string;
  mode: string;
  created_at: string;
  message_count: number;
}

export interface MessageResponse {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export async function listConversations(): Promise<{
  items: ConversationResponse[];
  total: number;
}> {
  const res = await apiFetch(`${API_BASE}/conversations`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getConversationMessages(
  conversationId: string
): Promise<MessageResponse[]> {
  const res = await apiFetch(
    `${API_BASE}/conversations/${conversationId}/messages`
  );
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Model Config APIs ────────────────────────────────

export interface ModelConfigResponse {
  name: string;
  provider_type: string;
  model_id: string;
  model_type: string;
  api_key_masked?: string;
  base_url?: string;
  supports_tool_use: boolean;
  supports_streaming: boolean;
  max_tokens_limit: number;
  is_active: boolean;
}

export interface ModelRouteResponse {
  task_type: string;
  model_name: string;
}

export interface WhisperConfigResponse {
  mode: string;
  api_base_url?: string;
  api_model?: string;
  api_key_masked?: string | null;
  local_model?: string;
}

export async function getModels(): Promise<ModelConfigResponse[]> {
  const res = await apiFetch(`${API_BASE}/models`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getModelRoutes(): Promise<ModelRouteResponse[]> {
  const res = await apiFetch(`${API_BASE}/model-routes`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function updateModelRoutes(
  routes: Array<{ task_type: string; model_name: string }>
): Promise<ModelRouteResponse[]> {
  const res = await apiFetch(`${API_BASE}/model-routes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(routes),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getWhisperConfig(): Promise<WhisperConfigResponse> {
  const res = await apiFetch(`${API_BASE}/setup/whisper`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function updateWhisperConfig(data: {
  mode?: string;
  api_base_url?: string;
  api_model?: string;
  api_key?: string;
  local_model?: string;
}): Promise<WhisperConfigResponse> {
  const res = await apiFetch(`${API_BASE}/setup/whisper`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getTaskStatus(taskId: string): Promise<{
  task_id: string;
  state: string;
  result?: unknown;
  error?: string;
  progress?: unknown;
}> {
  const res = await apiFetch(`${API_BASE}/tasks/${taskId}/status`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function createModel(data: {
  name: string;
  provider_type: string;
  model_id: string;
  model_type?: string;
  api_key?: string;
  base_url?: string;
}): Promise<ModelConfigResponse> {
  const res = await apiFetch(`${API_BASE}/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function deleteModel(name: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/models/${name}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await responseError(res);
}

export async function testModel(name: string): Promise<{
  success: boolean;
  message: string;
  model?: string;
}> {
  const res = await apiFetch(`${API_BASE}/models/${name}/test`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Diagnostic APIs ────────────────────────────────
export interface DiagnosticQuestion {
  id: string;
  concept_id: string;
  question: string;
  options: string[];
  correct_index: number;
  difficulty: number;
}

export interface DiagnosticResult {
  level: string;
  mastered_concepts: string[];
  gaps: string[];
  score: number;
}

export async function generateDiagnostic(courseId: string): Promise<{
  questions: DiagnosticQuestion[];
  concept_map: Record<string, string>;
}> {
  const res = await apiFetch(`${API_BASE}/courses/${courseId}/diagnostic/generate`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function submitDiagnostic(
  courseId: string,
  questions: { id: string; correct_index: number; concept_name: string }[],
  answers: { question_id: string; selected_answer: number; time_spent_seconds: number }[],
): Promise<DiagnosticResult> {
  const res = await apiFetch(`${API_BASE}/courses/${courseId}/diagnostic/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ questions, answers }),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Exercise APIs ──────────────────────────────────
export interface ExerciseResponse {
  id: string;
  type: "mcq" | "code" | "open";
  question: string;
  options?: string[];
  difficulty: number;
  section_id: string;
}

export interface SubmissionResult {
  submission_id: string;
  score: number | null;
  feedback: string | null;
  explanation: string | null;
}

export async function getSectionExercises(sectionId: string): Promise<{ exercises: ExerciseResponse[] }> {
  const res = await apiFetch(`${API_BASE}/exercises/section/${sectionId}`);
  if (!res.ok) throw new Error("Failed to fetch exercises");
  const data = await res.json();
  return { exercises: data.items ?? [] };
}

export async function submitExercise(exerciseId: string, answer: string): Promise<SubmissionResult> {
  const res = await apiFetch(`${API_BASE}/exercises/${exerciseId}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Review APIs ────────────────────────────────────
export interface ReviewItemDetail {
  id: string;
  concept_name: string;
  concept_description: string;
  review_question: string | null;
  review_answer: string | null;
  easiness: number;
  interval_days: number;
  repetitions: number;
  review_at: string;
}

export async function getDueReviews(): Promise<{ items: ReviewItemDetail[]; total: number }> {
  const res = await apiFetch(`${API_BASE}/reviews/due`);
  if (!res.ok) throw new Error("Failed to fetch reviews");
  return res.json();
}

export async function completeReview(reviewId: string, quality: number): Promise<unknown> {
  const res = await apiFetch(`${API_BASE}/reviews/${reviewId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quality }),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getReviewStats(): Promise<{ due_today: number; completed_today: number }> {
  const res = await apiFetch(`${API_BASE}/reviews/stats`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Translation APIs ───────────────────────────────
export async function estimateTranslation(sectionId: string, target: string = "zh"): Promise<{
  chunks_total: number;
  chunks_cached: number;
  chunks_to_translate: number;
  estimated_tokens: number;
  estimated_cost_usd: number;
}> {
  const res = await apiFetch(`${API_BASE}/sections/${sectionId}/translate/estimate?target=${target}`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function translateSection(sectionId: string, target: string = "zh"): Promise<{
  translations: { chunk_id: string; translated_text: string | null }[];
  total: number;
}> {
  const res = await apiFetch(`${API_BASE}/sections/${sectionId}/translate?target=${target}`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Setup APIs ─────────────────────────────────────

export async function getSetupStatus(): Promise<{
  has_models: boolean;
  ollama_available: boolean;
  ollama_models: string[];
  ollama_base_url?: string;
  codex_available: boolean;
  codex_logged_in: boolean;
  codex_auth_mode?: string | null;
  codex_status_message?: string;
  codex_models: Array<{
    id: string;
    display_name: string;
    description?: string;
  }>;
  codex_error?: string | null;
}> {
  const res = await apiFetch(`${API_BASE}/setup/status`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getBilibiliStatus(): Promise<{
  logged_in: boolean;
  dedeuserid?: string;
}> {
  const res = await apiFetch(`${API_BASE}/setup/bilibili/status`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function generateBilibiliQrcode(): Promise<{
  status: string;
  qrcode_base64: string;
}> {
  const res = await apiFetch(`${API_BASE}/setup/bilibili/qrcode`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function checkBilibiliQrcode(): Promise<{
  status: string;
  dedeuserid?: string;
}> {
  const res = await apiFetch(`${API_BASE}/setup/bilibili/qrcode/status`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function logoutBilibili(): Promise<{
  status: string;
}> {
  const res = await apiFetch(`${API_BASE}/setup/bilibili`, {
    method: "DELETE",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function startCodexLogin(): Promise<{
  session_id?: string | null;
  status: string;
  verification_url?: string | null;
  user_code?: string | null;
  message?: string | null;
  logged_in: boolean;
}> {
  const res = await apiFetch(`${API_BASE}/setup/codex/login/start`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getCodexLoginSession(sessionId: string): Promise<{
  session_id?: string | null;
  status: string;
  verification_url?: string | null;
  user_code?: string | null;
  message?: string | null;
  logged_in: boolean;
}> {
  const res = await apiFetch(`${API_BASE}/setup/codex/login/${sessionId}`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Lab APIs ───────────────────────────────────────

export interface LabResponse {
  id: string;
  section_id: string;
  title: string;
  description: string;
  language: string;
  starter_code: Record<string, string>;
  test_code: Record<string, string>;
  run_instructions: string;
  confidence: number;
}

export async function getSectionLab(sectionId: string): Promise<LabResponse | null> {
  const res = await apiFetch(`${API_BASE}/labs/section/${sectionId}`);
  if (res.status === 404) return null;
  if (!res.ok) throw await responseError(res);
  const data = await res.json();
  return data || null;
}

// ─── Knowledge Graph API ────────────────────────────
export interface KnowledgeGraphNode {
  id: string;
  label: string;
  category: string | null;
  mastery: number;
  section_id: string | null;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  relationship: string;
}

export async function getKnowledgeGraph(courseId: string, maxDepth: number = 2): Promise<{
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}> {
  const res = await apiFetch(`${API_BASE}/courses/${courseId}/knowledge-graph?max_depth=${maxDepth}`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

// ─── Progress APIs ───────────────────────────────────

export async function getCourseProgress(courseId: string): Promise<
  Array<{ section_id: string; lesson_read: boolean; lab_completed: boolean; exercise_best_score: number | null; status: string }>
> {
  const res = await apiFetch(`${API_BASE}/courses/${courseId}/progress`);
  if (!res.ok) throw new Error("Failed to fetch progress");
  return res.json();
}

export async function recordProgress(sectionId: string, event: "lesson_read" | "lab_completed"): Promise<void> {
  await apiFetch(`${API_BASE}/sections/${sectionId}/progress`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
}
