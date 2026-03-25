/** SSE streaming helper using eventsource-parser. */

import {
  EventSourceParserStream,
  type EventSourceMessage,
} from "eventsource-parser/stream";

export interface SSEEvent {
  event: string;
  data: string;
}

/**
 * Stream SSE events from a POST endpoint.
 * Uses eventsource-parser for proper SSE parsing.
 */
export async function* streamSSE(
  url: string,
  body: Record<string, unknown>,
  signal?: AbortSignal
): AsyncGenerator<SSEEvent> {
  const authHeaders: Record<string, string> = {};
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) authHeaders["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) throw new Error(await res.text());
  if (!res.body) throw new Error("No response body");

  const stream = res.body
    .pipeThrough(new TextDecoderStream())
    .pipeThrough(new EventSourceParserStream());

  const reader = stream.getReader();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const msg = value as EventSourceMessage;
    if (msg.data) {
      yield { event: msg.event || "message", data: msg.data };
    }
  }
}
