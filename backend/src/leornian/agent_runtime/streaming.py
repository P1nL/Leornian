"""Collect provider SSE into the same durable receipt used by non-streaming calls."""

import codecs
import json
import logging

logger = logging.getLogger(__name__)


class CompletionStream:
    def __init__(self, progress=None, thinking=None):
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.buffer = ""
        self.message = {"role": "assistant", "content": None}
        self.tools = {}
        self.finish_reason = None
        self.usage = None
        self.done = False
        self.progress = progress
        self.thinking = thinking
        self.phase = None
        self.metadata = {}

    def feed(self, chunk):
        self.buffer += self.decoder.decode(chunk)
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                self.done = True
                if self.thinking:
                    self.thinking.finish()
                continue
            if not data:
                continue
            event = json.loads(data)
            for key in ("id", "model", "created"):
                if key in event:
                    self.metadata[key] = event[key]
            if event.get("usage"):
                self.usage = event["usage"]
            for choice in event.get("choices", []):
                if choice.get("index", 0) != 0:
                    continue
                delta = choice.get("delta", {})
                for key in ("content", "reasoning_content"):
                    value = delta.get(key)
                    if isinstance(value, str):
                        self.message[key] = (self.message.get(key) or "") + value
                        if self.thinking:
                            if key == "reasoning_content":
                                self.thinking.feed(value)
                            elif value:
                                self.thinking.finish()
                        phase = "thinking" if key == "reasoning_content" else "composing"
                        if value and self.phase != phase:
                            self.phase = phase
                            if self.progress:
                                # Phase labels and filtered model text have separate channels.
                                try:
                                    self.progress(phase)
                                except Exception:
                                    logger.warning(
                                        "Model progress notification failed.", exc_info=True
                                    )
                for tool in delta.get("tool_calls") or []:
                    target = self.tools.setdefault(tool["index"], {
                        "id": "", "type": "function", "function": {"name": "", "arguments": ""},
                    })
                    if tool.get("id"):
                        target["id"] += tool["id"]
                    for key in ("name", "arguments"):
                        target["function"][key] += tool.get("function", {}).get(key) or ""
                if choice.get("finish_reason"):
                    self.finish_reason = choice["finish_reason"]
                    for key in ("annotations", "server_tool_calls"):
                        if key in delta:
                            self.message[key] = delta[key]

    def body(self):
        if not self.done or not self.finish_reason:
            raise ValueError("incomplete_completion_stream")
        if self.tools:
            self.message["tool_calls"] = [self.tools[key] for key in sorted(self.tools)]
        return json.dumps({
            **self.metadata,
            "choices": [{"index": 0, "message": self.message, "finish_reason": self.finish_reason}],
            **({"usage": self.usage} if self.usage else {}),
        }, ensure_ascii=False)
