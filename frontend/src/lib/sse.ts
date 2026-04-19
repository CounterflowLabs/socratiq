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
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`无法连接后端 SSE 接口：${url}\n原始错误：${reason}`);
  }

  if (!res.ok) {
    const bodyText = await res.text();
    throw new Error(
      `SSE 请求失败：${res.status} ${res.statusText}\nURL：${res.url}\n详情：${bodyText || "响应体为空"}`
    );
  }
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
