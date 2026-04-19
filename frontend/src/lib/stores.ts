/** Zustand stores for global state management. */

import { create } from "zustand";
import type { SourceResponse, CourseResponse, ConversationResponse, Citation } from "./api";

// ─── Chat Store ───────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

interface ChatStore {
  messages: ChatMessage[];
  conversationId: string | null;
  isStreaming: boolean;
  addMessage: (msg: ChatMessage) => void;
  appendToLast: (text: string) => void;
  setCitationsOnLast: (citations: Citation[]) => void;
  setConversationId: (id: string) => void;
  setStreaming: (s: boolean) => void;
  clearChat: () => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  conversationId: null,
  isStreaming: false,
  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),
  appendToLast: (text) =>
    set((state) => {
      const msgs = [...state.messages];
      if (msgs.length > 0) {
        msgs[msgs.length - 1] = {
          ...msgs[msgs.length - 1],
          content: msgs[msgs.length - 1].content + text,
        };
      }
      return { messages: msgs };
    }),
  setCitationsOnLast: (citations) =>
    set((state) => {
      const msgs = [...state.messages];
      if (msgs.length > 0) {
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], citations };
      }
      return { messages: msgs };
    }),
  setConversationId: (id) => set({ conversationId: id }),
  setStreaming: (s) => set({ isStreaming: s }),
  clearChat: () => set({ messages: [], conversationId: null }),
}));

// ─── Sources Store ────────────────────────────────────

interface SourcesStore {
  sources: SourceResponse[];
  loading: boolean;
  setSources: (s: SourceResponse[]) => void;
  setLoading: (l: boolean) => void;
  addSource: (s: SourceResponse) => void;
  updateSource: (id: string, patch: Partial<SourceResponse>) => void;
}

export const useSourcesStore = create<SourcesStore>((set) => ({
  sources: [],
  loading: false,
  setSources: (sources) => set({ sources }),
  setLoading: (loading) => set({ loading }),
  addSource: (s) =>
    set((state) => ({ sources: [s, ...state.sources] })),
  updateSource: (id, patch) =>
    set((state) => ({
      sources: state.sources.map((s) =>
        s.id === id ? { ...s, ...patch } : s
      ),
    })),
}));

// ─── Tasks Store (background ingestion tasks) ────────

export interface PendingTask {
  taskId: string;
  sourceId: string;
  title: string;
  sourceType: string;
  state: string; // PENDING, extracting, analyzing, generating_lessons, generating_labs, storing, embedding, SUCCESS, FAILURE
  error?: string;
  courseId?: string; // set when course generated
}

interface TasksStore {
  tasks: PendingTask[];
  addTask: (t: PendingTask) => void;
  updateTask: (taskId: string, patch: Partial<PendingTask>) => void;
  removeTask: (taskId: string) => void;
}

export const useTasksStore = create<TasksStore>((set) => ({
  tasks: [],
  addTask: (t) => set((state) => ({ tasks: [t, ...state.tasks] })),
  updateTask: (taskId, patch) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.taskId === taskId ? { ...t, ...patch } : t
      ),
    })),
  removeTask: (taskId) =>
    set((state) => ({ tasks: state.tasks.filter((t) => t.taskId !== taskId) })),
}));

// ─── Courses Store ────────────────────────────────────

interface CoursesStore {
  courses: CourseResponse[];
  loading: boolean;
  setCourses: (c: CourseResponse[]) => void;
  setLoading: (l: boolean) => void;
  addCourse: (c: CourseResponse) => void;
}

export const useCoursesStore = create<CoursesStore>((set) => ({
  courses: [],
  loading: false,
  setCourses: (courses) => set({ courses }),
  setLoading: (loading) => set({ loading }),
  addCourse: (c) =>
    set((state) => ({ courses: [c, ...state.courses] })),
}));
