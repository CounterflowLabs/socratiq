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

export class ApiError extends Error {
  status: number;
  detail: unknown;
  code?: string;

  constructor(
    message: string,
    options: { status: number; detail: unknown; code?: string }
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.detail = options.detail;
    this.code = options.code;
  }
}

async function responseError(res: Response): Promise<ApiError> {
  const body = await res.text();
  let detail: unknown = body.trim() || null;
  let detailText = body.trim();
  let code: string | undefined;

  if (detailText) {
    try {
      const parsed = JSON.parse(detailText);
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        detail = (parsed as { detail: unknown }).detail;
        if (typeof detail === "string") {
          detailText = detail;
        } else if (detail && typeof detail === "object") {
          const obj = detail as Record<string, unknown>;
          if (typeof obj.code === "string") code = obj.code;
          if (typeof obj.message === "string") detailText = obj.message;
          else detailText = JSON.stringify(detail);
        } else {
          detailText = JSON.stringify(detail);
        }
      } else {
        detail = parsed;
        detailText = JSON.stringify(parsed);
      }
    } catch {
      // Keep the plain response body.
    }
  }

  const message = [
    `API 请求失败：${res.status} ${res.statusText}`,
    `URL：${res.url || "unknown"}`,
    `详情：${detailText || "响应体为空"}`,
  ].join("\n");

  return new ApiError(message, { status: res.status, detail, code });
}

// ─── Source APIs ───────────────────────────────────────

export interface SourceTaskSummary {
  id?: string;
  task_type: string;
  status: string;
  stage?: string | null;
  error_summary?: string | null;
  celery_task_id?: string | null;
  metadata_?: Record<string, unknown>;
}

export interface SourceEmbed {
  status: "ready" | "running" | "queued" | "failed" | "stale" | "cancelled";
  model?: string | null;
  chunks?: number | null;
  vectors?: number | null;
  progress?: number | null;
  eta_seconds?: number | null;
  error?: string | null;
  reason?: string | null;
}

export interface SectionPlannerStats {
  tier_used: "skeleton" | "windowed" | "embedding_only" | "fallback";
  planner_version: string;
  bucket_count: number;
  avg_chunks_per_bucket: number;
  min_chunks_per_bucket: number;
  max_chunks_per_bucket: number;
  topic_uniqueness: number;
  planning_duration_ms: number;
  llm_input_tokens: number;
  llm_output_tokens: number;
  short_circuit: boolean;
  error: string | null;
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
  duplicate_of_source_id?: string | null;
  duplicate_reason?: "user_existing" | "global_existing_reused" | string | null;
  embed?: SourceEmbed | null;
  created_at: string;
  updated_at: string;
}

export interface IngestOptions {
  chunk_size?: 256 | 512 | 1024;
  transcript?: "reuse" | "force_whisper";
  ocr?: "auto" | "force" | "off";
}

export async function createSourceFromURL(
  url: string,
  sourceType?: string,
  title?: string,
  ingestOptions?: IngestOptions,
): Promise<SourceResponse> {
  const form = new FormData();
  form.append("url", url);
  if (sourceType) form.append("source_type", sourceType);
  if (title) form.append("title", title);
  if (ingestOptions && Object.keys(ingestOptions).length > 0) {
    form.append("ingest_options_json", JSON.stringify(ingestOptions));
  }

  const res = await apiFetch(`${API_BASE}/sources`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function createSourceFromFile(
  file: File,
  title?: string,
  ingestOptions?: IngestOptions,
): Promise<SourceResponse> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  if (ingestOptions && Object.keys(ingestOptions).length > 0) {
    form.append("ingest_options_json", JSON.stringify(ingestOptions));
  }

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

export interface LessonReference {
  title: string;
  source?: string | null;
  year?: string | null;
  kind?: "classic" | "frontier";
  url?: string | null;
  note?: string | null;
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
    | "exercise_trigger"
    | "recap"
    | "next_step"
    | "further_reading";
  title?: string | null;
  body?: string | null;
  concepts?: LessonConcept[];
  references?: LessonReference[];
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

export interface GenerateIncludes {
  exercises: boolean;
  lab: boolean;
  review: boolean;
}

export interface GenerateCourseConfig {
  source_ids: string[];
  title?: string;
  brief?: string;
  depth?: number;
  audience?: "intro" | "mid" | "adv";
  tier?: "fast" | "smart";
  language?: "source" | "zh" | "en";
  includes?: GenerateIncludes;
  /** PRD §10 — per-source weight overrides keyed by source_id.
   *  Absent entries default to 1.0. Persists in the task metadata for
   *  weighted-chunk synthesis when it lands. */
  source_weights?: Record<string, number>;
}

export interface GenerateCourseResponse {
  task_id: string;
  source_ids: string[];
  status: "dispatched" | "already_dispatched";
}

/** Async multi-source course generation (PRD §5.4). Returns a task id; the
 *  course id appears on the unified Tasks queue when generation completes. */
export async function generateCourse(
  config: GenerateCourseConfig,
): Promise<GenerateCourseResponse> {
  const res = await apiFetch(`${API_BASE}/courses/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export interface CourseFromPromptResponse {
  task_id: string;
  status: string;
}

/** Generate a full course from a single-sentence prompt (no source material).
 *  Returns the dispatch task id; use it as the AG-UI `run_id` with
 *  {@link streamCourseRunEvents} to follow live progress, and read the new
 *  course id off the terminal RUN_FINISHED event's `result.course_id`. */
export async function createCourseFromPrompt(
  prompt: string,
  targetLanguage?: string,
): Promise<CourseFromPromptResponse> {
  const res = await apiFetch(`${API_BASE}/courses/from-prompt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      ...(targetLanguage ? { target_language: targetLanguage } : {}),
    }),
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

export interface SectionMergeResponse {
  surviving_section_id: string;
  removed_section_id: string;
  chunks_reassigned: number;
}

export interface SectionSplitResponse {
  original_section_id: string;
  new_section_id: string;
  chunks_in_original: number;
  chunks_in_new: number;
}

export async function mergeSectionWithNext(
  sectionId: string,
): Promise<SectionMergeResponse> {
  const res = await apiFetch(
    `${API_BASE}/courses/sections/${sectionId}/merge-next`,
    { method: "POST" },
  );
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function splitSection(
  sectionId: string,
  splitAtChunkIndex: number,
): Promise<SectionSplitResponse> {
  const res = await apiFetch(
    `${API_BASE}/courses/sections/${sectionId}/split`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ split_at_chunk_index: splitAtChunkIndex }),
    },
  );
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

/**
 * One AG-UI protocol event. The chat stream is a sequence of these, each
 * discriminated by `type` (RUN_STARTED, TEXT_MESSAGE_CONTENT, TOOL_CALL_START,
 * TOOL_CALL_RESULT, CUSTOM, RUN_FINISHED, RUN_ERROR, …). Fields are camelCase
 * per the AG-UI wire format; only the ones the UI reads are typed here.
 */
export interface AGUIEvent {
  type: string;
  // text message
  messageId?: string;
  delta?: string;
  // tool call
  toolCallId?: string;
  toolCallName?: string;
  content?: string;
  // run lifecycle
  threadId?: string;
  runId?: string;
  message?: string; // RUN_ERROR
  code?: string;
  // custom (e.g. {name:"citations", value:[...]})
  name?: string;
  value?: unknown;
  // task progress: STATE_SNAPSHOT carries `snapshot` (full state); STATE_DELTA
  // reuses the `delta` key above but as an RFC 6902 op array (see useRunProgress).
  snapshot?: unknown;
  // RUN_FINISHED payload. The top-level key is `result` (camelCase == snake_case
  // for a single word); the course-gen runs put the new course id at
  // `result.course_id` (still snake_case — it rides inside an Any-typed dict the
  // backend serializes verbatim).
  result?: { course_id?: string; status?: string } & Record<string, unknown>;
}

interface StreamChatOptions {
  message: string;
  conversationId?: string;
  courseId?: string;
  sectionId?: string;
  signal?: AbortSignal;
}

export async function* streamChat(opts: StreamChatOptions): AsyncGenerator<AGUIEvent> {
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
    // AG-UI frames are unnamed SSE `data:` events; the event kind is the
    // `type` field inside the JSON payload.
    try {
      yield JSON.parse(evt.data) as AGUIEvent;
    } catch {
      // skip malformed events
    }
  }
}

/**
 * Live AG-UI event stream for a long-running task (course generation).
 *
 * `runId` is the course task id returned by the dispatch endpoints. The ARQ
 * worker publishes the run's events to a Redis stream; this re-streams them as
 * SSE. Reconnecting replays from the start, so a late subscriber still gets the
 * latest STATE_SNAPSHOT. Replaces polling `getSourceProgress` for live progress.
 */
export async function* streamRunEvents(
  sourceId: string,
  runId: string,
  signal?: AbortSignal
): AsyncGenerator<AGUIEvent> {
  const { streamSSEGet } = await import("./sse");

  for await (const evt of streamSSEGet(
    `${API_BASE}/sources/${sourceId}/runs/${runId}/events`,
    signal
  )) {
    try {
      yield JSON.parse(evt.data) as AGUIEvent;
    } catch {
      // skip malformed events
    }
  }
}

/**
 * Live AG-UI event stream for a source-less course run (one-sentence → course).
 *
 * Mirrors {@link streamRunEvents} but hits the source-scoped-free endpoint;
 * `runId` is the task id from {@link createCourseFromPrompt}. The terminal
 * RUN_FINISHED event carries the new course id at `result.course_id`.
 */
export async function* streamCourseRunEvents(
  runId: string,
  signal?: AbortSignal
): AsyncGenerator<AGUIEvent> {
  const { streamSSEGet } = await import("./sse");

  for await (const evt of streamSSEGet(
    `${API_BASE}/courses/runs/${runId}/events`,
    signal
  )) {
    try {
      yield JSON.parse(evt.data) as AGUIEvent;
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

export interface SourceTaskProgress {
  task_type: string;
  status: string;
  stage?: string | null;
  error_summary?: string | null;
  celery_task_id?: string | null;
  metadata_?: Record<string, unknown>;
  cancel_requested: boolean;
  course_id?: string | null;
  updated_at: string;
  created_at: string;
}

export interface SourceProgressResponse {
  source_id: string;
  source_status: string;
  error?: string | null;
  course_id?: string | null;
  tasks: SourceTaskProgress[];
}

export interface CourseProgressResponse {
  course_id: string;
  parent_course_id?: string | null;
  active_regeneration_task_id?: string | null;
  tasks: SourceTaskProgress[];
}

// ─── Unified Tasks queue (PRD §5.5) ──────────────────

export type TaskTypeUi = "embed" | "generate";
export type TaskStatusUi = "running" | "queued" | "done" | "failed";

export interface TaskListItem {
  id: string;
  type: TaskTypeUi;
  raw_task_type: string;
  status: TaskStatusUi;
  stage?: string | null;
  error?: string | null;
  eta_seconds?: number | null;
  started_at: string;
  updated_at: string;
  finished_at?: string | null;
  source_id?: string | null;
  source_title?: string | null;
  source_type?: string | null;
  course_id?: string | null;
  course_title?: string | null;
  celery_task_id?: string | null;
  cancel_requested: boolean;
}

export interface TaskListResponse {
  items: TaskListItem[];
  total: number;
  skip: number;
  limit: number;
  counts_by_type: Record<string, number>;
  counts_by_status: Record<string, number>;
}

export async function listTasks(params: {
  type?: "all" | TaskTypeUi;
  status?: "all" | TaskStatusUi;
  skip?: number;
  limit?: number;
} = {}): Promise<TaskListResponse> {
  const query = new URLSearchParams();
  if (params.type) query.set("type", params.type);
  if (params.status) query.set("status", params.status);
  if (params.skip !== undefined) query.set("skip", String(params.skip));
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  const qs = query.toString();
  const res = await apiFetch(`${API_BASE}/tasks${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function cancelTask(taskId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/tasks/${taskId}/cancel`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
}

export async function retryTask(
  taskId: string,
): Promise<{ task_id: string; status: string }> {
  const res = await apiFetch(`${API_BASE}/tasks/${taskId}/retry`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export interface SourceChunkBrief {
  id: string;
  text: string;
  length: number;
  section_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export async function listSourceChunks(
  sourceId: string,
  params: { skip?: number; limit?: number } = {},
): Promise<{ items: SourceChunkBrief[]; total: number; skip: number; limit: number }> {
  const qs = new URLSearchParams();
  if (params.skip !== undefined) qs.set("skip", String(params.skip));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const res = await apiFetch(
    `${API_BASE}/sources/${sourceId}/chunks${qs.toString() ? `?${qs.toString()}` : ""}`,
  );
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export interface SourceCitationCourse {
  course_id: string;
  course_title: string;
  created_at: string;
  parent_id: string | null;
  regeneration_directive: string | null;
  version_index: number;
  is_latest: boolean;
  sections: { section_id: string; title: string; order_index: number | null }[];
}

export async function listSourceCitations(
  sourceId: string,
): Promise<{ items: SourceCitationCourse[]; total: number }> {
  const res = await apiFetch(`${API_BASE}/sources/${sourceId}/citations`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getSourceProgress(
  sourceId: string
): Promise<SourceProgressResponse> {
  const res = await apiFetch(`${API_BASE}/sources/${sourceId}/progress`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function getCourseTaskProgress(
  courseId: string
): Promise<CourseProgressResponse> {
  const res = await apiFetch(`${API_BASE}/courses/${courseId}/task-progress`);
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function cancelSource(sourceId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/sources/${sourceId}/cancel`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
}

export async function retrySource(
  sourceId: string
): Promise<{ task_id: string }> {
  const res = await apiFetch(`${API_BASE}/sources/${sourceId}/retry`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function deleteSource(sourceId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/sources/${sourceId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await responseError(res);
}

export async function generateCourseForSource(
  sourceId: string
): Promise<{ task_id: string; source_id: string; status: string }> {
  const res = await apiFetch(`${API_BASE}/sources/${sourceId}/generate-course`, {
    method: "POST",
  });
  if (!res.ok) throw await responseError(res);
  return res.json();
}

export async function cancelCourseRegeneration(courseId: string): Promise<void> {
  const res = await apiFetch(
    `${API_BASE}/courses/${courseId}/regeneration/cancel`,
    { method: "POST" }
  );
  if (!res.ok) throw await responseError(res);
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

export interface SectionExercisesPayload {
  exercises: ExerciseResponse[];
  is_generating: boolean;
  error: string | null;
  active_task_id: string | null;
}

export async function getSectionExercises(
  sectionId: string
): Promise<SectionExercisesPayload> {
  const res = await apiFetch(`${API_BASE}/exercises/section/${sectionId}`);
  if (!res.ok) throw new Error("Failed to fetch exercises");
  const data = await res.json();
  return {
    exercises: data.items ?? [],
    is_generating: Boolean(data.is_generating),
    error: data.error ?? null,
    active_task_id: data.active_task_id ?? null,
  };
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

export interface ExerciseGenerateDispatch {
  task_id: string;
  section_id: string;
  status: "dispatched" | "in_flight";
}

export async function generateSectionExercises(
  sectionId: string,
  count = 3,
  types: Array<"mcq" | "open" | "code"> = ["mcq", "open"],
): Promise<ExerciseGenerateDispatch> {
  const res = await apiFetch(`${API_BASE}/exercises/section/${sectionId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count, types }),
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
  ollama_embedding_models?: string[];
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
  dedeuserid?: string | null;
  source?: "db" | "env" | null;
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
