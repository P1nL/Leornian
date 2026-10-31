import { describe, expect, it } from "vitest";
import { SseDecoder } from "./stream";

describe("SSE framing", () => {
  it("decodes fragmented frames and ignores heartbeat comments", () => {
    const decoder = new SseDecoder();
    expect(decoder.feed(": heartbeat\r\n\r\nid: 1\r\nevent: goal.")).toEqual([]);
    expect(decoder.feed('created\r\ndata: {"sequence":1}\r\n\r\n')).toEqual([
      { id: "1", event: "goal.created", data: '{"sequence":1}' },
    ]);
  });
  it("keeps incomplete trailing data and joins multiple data lines", () => {
    const decoder = new SseDecoder();
    expect(decoder.feed("data: first\ndata: second\n\ndata: tail")).toEqual([
      { id: "", event: "message", data: "first\nsecond" },
    ]);
    expect(decoder.feed("\n\n")).toEqual([{ id: "", event: "message", data: "tail" }]);
  });
});
