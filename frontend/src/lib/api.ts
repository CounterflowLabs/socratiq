/** API client for LearnMentor backend. */

const API_BASE = "/api";

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

  const res = await fetch(`${API_BASE}/sources`, { method: "POST", body: form });
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

  const res = await fetch(`${API_BASE}/sources`, { method: "POST", body: form });
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
  type: "text_delta" | "message_end" | "error";
  text?: string;
  conversation_id?: string;
  message?: string;
}

export async function* streamChat(
  message: string,
  conversationId?: string,
  courseId?: string
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      course_id: courseId,
    }),
  });

  if (!res.ok) throw new Error(await res.text());
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        try {
          yield JSON.parse(data) as ChatStreamEvent;
        } catch {
          // skip malformed lines
        }
      }
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
