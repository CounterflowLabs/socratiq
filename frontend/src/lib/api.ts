/** API client for LearnMentor backend. */

const API_BASE = "http://localhost:8000/api/v1";

function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const token = localStorage.getItem("access_token");
    if (token) return { Authorization: `Bearer ${token}` };
  } catch {
    // localStorage may not be available in some environments
  }
  return {};
}

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
    headers: getAuthHeaders(),
    body: form,
  });
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
    headers: getAuthHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listSources(): Promise<{
  items: SourceResponse[];
  total: number;
}> {
  const res = await fetch(`${API_BASE}/sources`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSource(id: string): Promise<SourceResponse> {
  const res = await fetch(`${API_BASE}/sources/${id}`, { headers: getAuthHeaders() });
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
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ source_ids: sourceIds, title }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listCourses(): Promise<{
  items: CourseResponse[];
  total: number;
}> {
  const res = await fetch(`${API_BASE}/courses`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getCourse(id: string): Promise<CourseDetailResponse> {
  const res = await fetch(`${API_BASE}/courses/${id}`, { headers: getAuthHeaders() });
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
  const res = await fetch(`${API_BASE}/conversations`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getConversationMessages(
  conversationId: string
): Promise<MessageResponse[]> {
  const res = await fetch(
    `${API_BASE}/conversations/${conversationId}/messages`,
    { headers: getAuthHeaders() }
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

export interface ModelRouteResponse {
  task_type: string;
  model_name: string;
}

export async function getModels(): Promise<ModelConfigResponse[]> {
  const res = await fetch(`${API_BASE}/models`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getModelRoutes(): Promise<ModelRouteResponse[]> {
  const res = await fetch(`${API_BASE}/model-routes`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getTaskStatus(taskId: string): Promise<{
  task_id: string;
  state: string;
  result?: unknown;
  error?: string;
  progress?: unknown;
}> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/status`, { headers: getAuthHeaders() });
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
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteModel(name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/models/${name}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
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
    headers: getAuthHeaders(),
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
    headers: getAuthHeaders(),
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
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
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
  const res = await fetch(`${API_BASE}/exercises/section/${sectionId}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitExercise(exerciseId: string, answer: string): Promise<SubmissionResult> {
  const res = await fetch(`${API_BASE}/exercises/${exerciseId}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
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
  const res = await fetch(`${API_BASE}/reviews/due`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function completeReview(reviewId: string, quality: number): Promise<unknown> {
  const res = await fetch(`${API_BASE}/reviews/${reviewId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ quality }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getReviewStats(): Promise<{ due_today: number; completed_today: number }> {
  const res = await fetch(`${API_BASE}/reviews/stats`, { headers: getAuthHeaders() });
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
  const res = await fetch(`${API_BASE}/sections/${sectionId}/translate/estimate?target=${target}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function translateSection(sectionId: string, target: string = "zh"): Promise<{
  translations: { chunk_id: string; translated_text: string | null }[];
  total: number;
}> {
  const res = await fetch(`${API_BASE}/sections/${sectionId}/translate?target=${target}`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
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
  const res = await fetch(`${API_BASE}/courses/${courseId}/knowledge-graph?max_depth=${maxDepth}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
