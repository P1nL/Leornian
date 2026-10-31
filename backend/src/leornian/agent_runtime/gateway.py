import json
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from leornian.agent_runtime.contracts import (
    Decision,
    EmptyToolArguments,
    ModelAvailability,
    Receipt,
    ToolCall,
)
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError

TOOL = {
    "type": "function",
    "function": {
        "name": "learning_get_context",
        "description": (
            "Read the selected goal, confirmed lesson, feedback and admitted source versions. "
            "No writes or execution."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


class ModelProtocolError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class DeliveryUnknown(Exception):
    """Transport ended without a complete response, not proof of a failed upstream call."""


class ChatCompletionsGateway:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def availability(self) -> ModelAvailability:
        url = urlsplit(self.settings.model_base_url)
        safe_url = (
            (
                url.scheme == "https"
                or (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})
            )
            and bool(url.hostname)
            and not (url.username or url.password or url.query or url.fragment)
        )
        ready = bool(
            self.settings.model_enabled
            and safe_url
            and self.settings.model_name.strip()
            and self.settings.model_api_key.strip()
        )
        return ModelAvailability(ready=ready, reason="ready" if ready else "not_configured")

    def require_ready(self) -> None:
        if not self.availability().ready:
            raise BusinessError(
                "model_unavailable", "Configure and explicitly enable a Leornian model."
            )

    @property
    def endpoint(self) -> str:
        return self.settings.model_base_url + "/chat/completions"

    def request(
        self,
        messages: list[dict[str, Any]],
        *,
        require_tool: bool,
        allowed_tools: tuple[str, ...] = ("learning_get_context",),
        json_output: bool = False,
    ) -> dict[str, Any]:
        self.require_ready()
        request = {
            "model": self.settings.model_name,
            "messages": messages,
            "max_tokens": 2400 if json_output else 1200,
            "stream": False,
        }
        if allowed_tools:
            if allowed_tools != ("learning_get_context",):
                raise ModelProtocolError("tool_not_allowed")
            request["tools"] = [TOOL]
            request["tool_choice"] = (
                {"type": "function", "function": {"name": "learning_get_context"}}
                if require_tool
                else "auto"
            )
        if json_output:
            request["response_format"] = {"type": "json_object"}
        if len(json.dumps(request, ensure_ascii=False).encode()) > 64000:
            raise ModelProtocolError("context_too_large")
        return request

    def send(self, endpoint: str, request: dict[str, Any]) -> Receipt:
        self.check_destination(endpoint, request)
        started = time.monotonic()
        try:
            with (
                httpx.Client(
                    transport=self.transport or httpx.HTTPTransport(retries=0),
                    timeout=httpx.Timeout(self.settings.model_timeout, connect=10),
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    json=request,
                    headers={"Authorization": f"Bearer {self.settings.model_api_key}"},
                ) as response,
            ):
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if (
                        len(chunks) > 256000
                        or time.monotonic() - started > self.settings.model_timeout
                    ):
                        raise DeliveryUnknown("incomplete_or_oversized_response")
                return Receipt(
                    body=chunks.decode("utf-8", errors="replace"),
                    http_status=response.status_code,
                    provider_request_id=response.headers.get("x-request-id", "")[:200] or None,
                )
        except httpx.TransportError as error:
            # No SDK/HTTP retry: even a timeout may hide a completed provider request.
            raise DeliveryUnknown(type(error).__name__) from None

    def check_destination(self, endpoint: str, request: dict[str, Any]) -> None:
        self.require_ready()
        # Fail before dispatch if a prepared request belongs to a previous configuration.
        if endpoint != self.endpoint or request.get("model") != self.settings.model_name:
            raise ModelProtocolError("provider_configuration_changed")


def parse_decision(body: str) -> Decision:
    try:
        response = json.loads(body)
        choices = response["choices"]
        if len(choices) != 1:
            raise ValueError("one choice required")
        choice = choices[0]
        message = choice["message"]
        if message.get("role") != "assistant" or message.get("refusal"):
            raise ValueError("not a teaching response")
        calls = message.get("tool_calls") or []
        if len(calls) > 2 or choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise ValueError("incomplete response")
        tools = []
        for call in calls:
            function = call["function"]
            if call.get("type") != "function" or not isinstance(call["id"], str) or not call["id"]:
                raise ValueError("invalid tool id")
            tools.append(
                ToolCall(
                    id=call["id"],
                    name=function["name"],
                    arguments=json.loads(function["arguments"]),
                )
            )
        if len({call.id for call in tools}) != len(tools):
            raise ValueError("duplicate tool ids")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("invalid content")
        if not tools and (not content or not content.strip() or len(content) > 16000):
            raise ValueError("empty or oversized answer")
        return Decision(content=content, tools=tools)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ModelProtocolError("invalid_model_response") from None


def validate_tools(decision: Decision, allowed: tuple[str, ...]) -> None:
    for call in decision.tools:
        if call.name not in allowed or call.name != "learning_get_context":
            raise ModelProtocolError("tool_not_allowed")
        try:
            EmptyToolArguments.model_validate(call.arguments)
        except ValueError:
            raise ModelProtocolError("invalid_tool_arguments") from None
