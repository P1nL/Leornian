"""Publish readable provider thinking without protocol, prompts or credentials."""

import logging
import re
import time

from leornian.platform.model_network import redact_credential

logger = logging.getLogger(__name__)

_BOUNDARY = re.compile(r"[。！？\n]|[.!?](?=\s)")
_PRIVATE = re.compile(
    r"private|confidential|system[\s_-]*(?:prompt|message|instruction)|"
    r"developer[\s_-]*(?:prompt|message|instruction)|"
    r"tool_calls?|function_call|reasoning_content|candidate_call_id|"
    r"required_checks|response_format|\b(?:json|schema|protocol)\b|"
    r"系统(?:提示|指令|消息)|开发者(?:提示|指令|消息)|内部(?:提示|指令)|"
    r"工具(?:调用|参数)|私有推理",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"(?:bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)


class VisibleThinking:
    def __init__(self, publish, *, secret="", messages=()):
        self.publish = publish
        self.secret = secret
        self.private = [
            line.strip()
            for message in messages
            if message.get("role") in {"system", "developer"}
            and isinstance(message.get("content"), str)
            for line in message["content"].splitlines()
            if len(line.strip()) >= 12
        ]
        self.pending = ""
        self.ready = ""
        self.fenced = False
        self.published_at = time.monotonic()

    def feed(self, text):
        # Hold incomplete sentences so a split key or prompt cannot leak token by token.
        self.pending += text
        boundaries = list(_BOUNDARY.finditer(self.pending))
        start = 0
        for boundary in boundaries:
            self._accept(self.pending[start:boundary.end()])
            start = boundary.end()
        self.pending = self.pending[start:]
        self._publish()

    def finish(self):
        self._accept(self.pending)
        self.pending = ""
        self._publish(force=True)

    def _accept(self, text):
        if "```" in text:
            if text.count("```") % 2:
                self.fenced = not self.fenced
            return
        if self.fenced:
            return
        text = re.sub(r"</?think>", "", text).strip()
        if not text or _PRIVATE.search(text):
            return
        if any(fragment in text or text in fragment for fragment in self.private):
            return
        text = redact_credential(text, self.secret)
        text = _CREDENTIAL.sub("[leornian-redacted-credential]", text)
        self.ready += text + ("\n" if text.endswith((".", "!", "?", "。", "！", "？")) else " ")

    def _publish(self, *, force=False):
        if not self.ready or not (
            force or len(self.ready) >= 240 or time.monotonic() - self.published_at >= 0.4
        ):
            return
        text, self.ready = self.ready, ""
        self.published_at = time.monotonic()
        try:
            self.publish(text)
        except Exception:
            # A display failure must not turn a complete upstream response into UNKNOWN.
            logger.warning("Visible model thinking notification failed.")
