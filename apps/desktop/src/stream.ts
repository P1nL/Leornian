import { apiBase, ApiError } from "./api";
import type { PublicEvent } from "./api";

export type Frame = { id: string; event: string; data: string };

export class SseDecoder {
  private buffer = "";

  feed(chunk: string): Frame[] {
    this.buffer += chunk;
    const frames: Frame[] = [];
    while (true) {
      const delimiter = /\r?\n\r?\n/.exec(this.buffer);
      if (!delimiter) break;
      const block = this.buffer.slice(0, delimiter.index);
      this.buffer = this.buffer.slice(delimiter.index + delimiter[0].length);
      const frame: Frame = { id: "", event: "message", data: "" };
      const data: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const name = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (name === "data") data.push(value);
        if (name === "id") frame.id = value;
        if (name === "event") frame.event = value;
      }
      frame.data = data.join("\n");
      if (data.length) frames.push(frame);
    }
    return frames;
  }
}

export async function listen(
  token: string, cursor: number, signal: AbortSignal,
  connected: () => void, consume: (event: PublicEvent) => Promise<void>,
): Promise<void> {
  // fetch allows an Authorization header; tokens never travel in an SSE URL.
  const response = await fetch(`${apiBase}/v1/events?after=${cursor}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" }, signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.code ?? "stream_failed", "Stream unavailable");
  }
  if (!response.body) throw new Error("Streaming body unavailable");
  connected();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseDecoder();
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const frame of parser.feed(decoder.decode(value, { stream: true }))) {
        if (frame.event === "stream.reset") {
          const code = JSON.parse(frame.data).code;
          throw new ApiError(code === "unauthorized" ? 401 : 409, code, "Reset stream");
        }
        const event = JSON.parse(frame.data) as PublicEvent;
        if (event.sequence > cursor) {
          await consume(event);
          cursor = event.sequence;
        }
      }
    }
    if (!signal.aborted) throw new Error("Stream closed");
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
