/** API client for Socratiq backend. */

const API_BASE = "http://localhost:8000/api/v1";

// ─── Source APIs ───────────────────────────────────────

export interface SourceResponse {
  id: string;
  type: string;
  url?: string;
  title?: string;
  status: string;
  metadata_: Record<string, unknown>;
  task_id?: string;
  created_at: string;
  updated_at: string;
}

export class DuplicateSourceError extends Error {
  existingSource: SourceResponse | null;
  constructor(message: string, existingSource: SourceResponse | null) {
    super(message);
    this.name = "DuplicateSourceError";
    this.existingSource = existingSource;
  }
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

  const res = await fetch(`${API_BASE}/sources`, {
    method: "POST",
    body: form,
  });
  if (res.status === 409) {
    const body = await res.json();
    throw new DuplicateSourceError(
      body.detail?.message || "该资源已导入或正在处理中",
      body.detail?.existing_source ?? null,
    );
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createSourceFromFile(
  file: File,
  title?: string
): Promise<SourceResponse> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);

  const res = await fetch(`${API_BASE}/sources`, {
    method: "POST",
    body: form,
  });
  if (res.status === 409) {
    const body = await res.json();
    throw new DuplicateSourceError(
      body.detail?.message || "该资源已导入或正在处理中",
      body.detail?.existing_source ?? null,
    );
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listSources(): Promise<{
  items: SourceResponse[];
  total: number;
}> {
  const res = await fetch(`${API_BASE}/sources`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSource(id: string): Promise<SourceResponse> {
  const res = await fetch(`${API_BASE}/sources/${id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listActiveSources(): Promise<SourceResponse[]> {
  const res = await fetch(`${API_BASE}/sources/active`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Course APIs ───────────────────────────────────────

export interface SectionResponse {
  id: string;
  title: string;
  order_index?: number;
  source_start?: string;
  source_end?: string;
  content: Record<string, unknown>;
  difficulty: number;
}

export interface CourseResponse {
  id: string;
  title: string;
  description?: string;
  created_at: string;
  updated_at: string;
}

export interface CourseDetailResponse extends CourseResponse {
  source_ids: string[];
  sections: SectionResponse[];
}

export async function generateCourse(
  sourceIds: string[],
  title?: string
): Promise<CourseResponse> {
  const res = await fetch(`${API_BASE}/courses/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_ids: sourceIds, title }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listCourses(): Promise<{
  items: CourseResponse[];
  total: number;
}> {
  const res = await fetch(`${API_BASE}/courses`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getCourse(id: string): Promise<CourseDetailResponse> {
  const res = await fetch(`${API_BASE}/courses/${id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Chat APIs (SSE) ──────────────────────────────────

export interface ChatStreamEvent {
  event: "text_delta" | "tool_start" | "tool_end" | "message_end" | "error";
  text?: string;
  conversation_id?: string;
  message?: string;
  tool?: string;
}

export async function* streamChat(
  message: string,
  conversationId?: string,
  courseId?: string,
  signal?: AbortSignal
): AsyncGenerator<ChatStreamEvent> {
  const { streamSSE } = await import("./sse");

  for await (const evt of streamSSE(
    `${API_BASE}/chat`,
    {
      message,
      conversation_id: conversationId,
      course_id: courseId,
    },
    signal
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
  const res = await fetch(`${API_BASE}/conversations`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getConversationMessages(
  conversationId: string
): Promise<MessageResponse[]> {
  const res = await fetch(
    `${API_BASE}/conversations/${conversationId}/messages`
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Model Config APIs ────────────────────────────────

export interface ModelConfigResponse {
  name: string;
  provider_type: string;
  model_id: string;
  api_key_masked?: string;
  base_url?: string;
  supports_tool_use: boolean;
  supports_streaming: boolean;
  max_tokens_limit: number;
  is_active: boolean;
}

export type ModelTier = "primary" | "light" | "strong" | "embedding";

export interface ModelTierResponse {
  tier: ModelTier;
  model_name: string;
}

// Backwards compat alias
export type ModelRouteResponse = ModelTierResponse;

export async function getModels(): Promise<ModelConfigResponse[]> {
  const res = await fetch(`${API_BASE}/models`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getModelTiers(): Promise<ModelTierResponse[]> {
  const res = await fetch(`${API_BASE}/model-tiers`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateModelTiers(
  tiers: { tier: ModelTier; model_name: string }[],
): Promise<ModelTierResponse[]> {
  const res = await fetch(`${API_BASE}/model-tiers`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(tiers),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// Backwards compat alias
export const getModelRoutes = getModelTiers;

export async function getTaskStatus(taskId: string): Promise<{
  task_id: string;
  state: string;
  result?: unknown;
  error?: string;
  progress?: unknown;
  stage?: string;
  estimated_remaining_seconds?: number;
}> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/status`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createModel(data: {
  name: string;
  provider_type: string;
  model_id: string;
  api_key?: string;
  base_url?: string;
}): Promise<ModelConfigResponse> {
  const res = await fetch(`${API_BASE}/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteModel(name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/models/${name}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function testModel(name: string): Promise<{
  success: boolean;
  message: string;
  model?: string;
}> {
  const res = await fetch(`${API_BASE}/models/${name}/test`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
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
  const res = await fetch(`${API_BASE}/courses/${courseId}/diagnostic/generate`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitDiagnostic(
  courseId: string,
  questions: { id: string; correct_index: number; concept_name: string }[],
  answers: { question_id: string; selected_answer: number; time_spent_seconds: number }[],
): Promise<DiagnosticResult> {
  const res = await fetch(`${API_BASE}/courses/${courseId}/diagnostic/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ questions, answers }),
  });
  if (!res.ok) throw new Error(await res.text());
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
  feedback: string;
  explanation: string;
}

export async function getSectionExercises(sectionId: string): Promise<{ exercises: ExerciseResponse[] }> {
  const res = await fetch(`${API_BASE}/exercises/section/${sectionId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitExercise(exerciseId: string, answer: string): Promise<SubmissionResult> {
  const res = await fetch(`${API_BASE}/exercises/${exerciseId}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Review APIs ────────────────────────────────────
export async function getDueReviews(): Promise<{
  items: { id: string; concept_id: string; easiness: number; interval_days: number; repetitions: number; review_at: string }[];
  count: number;
}> {
  const res = await fetch(`${API_BASE}/reviews/due`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function completeReview(reviewId: string, quality: number): Promise<unknown> {
  const res = await fetch(`${API_BASE}/reviews/${reviewId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quality }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getReviewStats(): Promise<{ due_today: number; completed_today: number }> {
  const res = await fetch(`${API_BASE}/reviews/stats`);
  if (!res.ok) throw new Error(await res.text());
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
  const res = await fetch(`${API_BASE}/sections/${sectionId}/translate/estimate?target=${target}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function translateSection(sectionId: string, target: string = "zh"): Promise<{
  translations: { chunk_id: string; translated_text: string | null }[];
  total: number;
}> {
  const res = await fetch(`${API_BASE}/sections/${sectionId}/translate?target=${target}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Setup APIs ─────────────────────────────────────

export async function getSetupStatus(): Promise<{
  has_models: boolean;
  ollama_available: boolean;
  ollama_models: string[];
}> {
  const res = await fetch(`${API_BASE}/setup/status`);
  if (!res.ok) throw new Error(await res.text());
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
  const res = await fetch(`${API_BASE}/labs/section/${sectionId}`);
  if (!res.ok) return null;
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
  const res = await fetch(`${API_BASE}/courses/${courseId}/knowledge-graph?max_depth=${maxDepth}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
