import asyncio
import json
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from leornian.agent_runtime.contracts import (
    Decision,
    ModelAvailability,
    Receipt,
    ToolCall,
)
from leornian.agent_runtime.policies import allocate_output, fit_optional_history, resolve_policy
from leornian.agent_runtime.tools import REGISTRY
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError

TOOL = REGISTRY["learning_get_context"].wire()


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
        self._capability = None

    def policy(self, role):
        if self._capability is None:
            if self.settings.model_context_tokens and self.settings.model_max_output_tokens:
                self._capability = {
                    "context_window": self.settings.model_context_tokens,
                    "max_output_tokens": self.settings.model_max_output_tokens,
                    "source": "operator-channel-declaration",
                }
            else:
                self.require_ready()
                try:
                    with httpx.Client(
                        transport=self.transport or httpx.HTTPTransport(retries=0),
                        timeout=10,
                        follow_redirects=False,
                    ) as client:
                        response = client.get(
                            self.settings.model_base_url + "/models",
                            headers={"Authorization": f"Bearer {self.settings.model_api_key}"},
                        )
                        response.raise_for_status()
                        model = next(
                            item
                            for item in response.json()["data"]
                            if item["id"] == self.settings.model_name
                        )
                        self._capability = {
                            "context_window": int(model["context_window"]),
                            "max_output_tokens": int(model["max_output_tokens"]),
                            "source": "provider-model-metadata",
                        }
                except (httpx.HTTPError, KeyError, ValueError, StopIteration):
                    raise BusinessError(
                        "model_unavailable",
                        "Channel capacity is unavailable; configure it explicitly.",
                    ) from None
        return resolve_policy(self.settings, role, self._capability)

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
        output_tokens: int | None = None,
        policy: dict | None = None,
        optional_history: list | None = None,
    ) -> dict[str, Any]:
        self.require_ready()
        request = {
            "model": self.settings.model_name,
            "messages": messages,
            "max_tokens": policy["max_output_tokens"]
            if policy
            else (output_tokens or (2400 if json_output else 1200)),
            "stream": False,
        }
        thinking = policy.get("thinking") if policy else self.settings.model_thinking
        if thinking:
            if thinking not in {"enabled", "disabled"}:
                raise ModelProtocolError("unsupported_thinking_mode")
            if thinking == "enabled" and policy is None:
                raise ModelProtocolError("thinking_policy_required")
            request["thinking"] = {"type": thinking}
        if allowed_tools:
            if any(name not in REGISTRY for name in allowed_tools):
                raise ModelProtocolError("tool_not_allowed")
            request["tools"] = [REGISTRY[name].wire() for name in allowed_tools]
            # DeepSeek thinking supports auto, not required/named forced tool choice.
            # Omission uses auto when tools are present; do not silently disable thinking.
            if thinking != "enabled":
                request["tool_choice"] = (
                    {"type": "function", "function": {"name": allowed_tools[0]}}
                    if require_tool
                    else "auto"
                )
        if json_output:
            request["response_format"] = {"type": "json_object"}
        if policy:
            try:
                request["messages"] = protocol_messages(
                    request["messages"], thinking=thinking, tools=bool(allowed_tools)
                )
                history = [
                    protocol_messages(pair, thinking=thinking, tools=bool(allowed_tools))
                    for pair in optional_history or []
                ]
                request = fit_optional_history(request, history, policy)
                request = allocate_output(request, policy)
            except BusinessError:
                raise ModelProtocolError("context_too_large") from None
        elif len(json.dumps(request, ensure_ascii=False).encode()) > 64000:
            raise ModelProtocolError("context_too_large")
        return request

    def send(self, endpoint: str, request: dict[str, Any], *, policy=None) -> Receipt:
        self.check_destination(endpoint, request)
        if policy:
            return asyncio.run(self._send_with_deadline(endpoint, request, policy))
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

    async def _send_with_deadline(self, endpoint, request, policy):
        try:
            async with (
                asyncio.timeout(policy["timeout_seconds"]),
                httpx.AsyncClient(
                    transport=self.transport or httpx.AsyncHTTPTransport(retries=0),
                    timeout=httpx.Timeout(
                        policy["timeout_seconds"], connect=policy["connect_timeout_seconds"]
                    ),
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
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > policy["response_bytes"]:
                        raise DeliveryUnknown("incomplete_or_oversized_response")
                return Receipt(
                    body=chunks.decode("utf-8", errors="replace"),
                    http_status=response.status_code,
                    provider_request_id=response.headers.get("x-request-id", "")[:200] or None,
                )
        except (TimeoutError, httpx.TransportError) as error:
            raise DeliveryUnknown(type(error).__name__) from None

    def check_destination(self, endpoint: str, request: dict[str, Any]) -> None:
        self.require_ready()
        # Fail before dispatch if a prepared request belongs to a previous configuration.
        if endpoint != self.endpoint or request.get("model") != self.settings.model_name:
            raise ModelProtocolError("provider_configuration_changed")


def protocol_messages(messages: list[dict], *, thinking: str | None, tools: bool) -> list[dict]:
    result = []
    for message in messages:
        message = dict(message)
        if thinking == "enabled" and tools and message["role"] == "assistant":
            # A genuinely old non-thinking reply may have no reasoning. Null is supported;
            # recorded thinking replies are hydrated from their exact accepted receipt.
            message.setdefault("reasoning_content", None)
        elif thinking != "enabled" or not tools:
            message.pop("reasoning_content", None)
        result.append(message)
    return result


def parse_decision(
    body: str,
    *,
    max_chars: int = 16000,
    thinking_tools: bool = False,
    recover_arguments: bool = False,
) -> Decision:
    try:
        response = json.loads(body)
        choices = response["choices"]
        if len(choices) != 1:
            raise ValueError("one choice required")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ModelProtocolError("output_truncated")
        message = choice["message"]
        if message.get("role") != "assistant" or message.get("refusal"):
            raise ValueError("not a teaching response")
        calls = message.get("tool_calls") or []
        if (len(calls) > 2 and not recover_arguments) or choice.get("finish_reason") not in {
            "stop",
            "tool_calls",
        }:
            raise ValueError("incomplete response")
        tools = []
        for call in calls:
            function = call["function"]
            if call.get("type") != "function" or not isinstance(call["id"], str) or not call["id"]:
                raise ValueError("invalid tool id")
            try:
                arguments = json.loads(function["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
            except ValueError:
                if not recover_arguments:
                    raise
                arguments = function["arguments"]
            tools.append(
                ToolCall(
                    id=call["id"],
                    name=function["name"],
                    arguments=arguments,
                )
            )
        if len({call.id for call in tools}) != len(tools):
            raise ValueError("duplicate tool ids")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("invalid content")
        if not tools and (not content or not content.strip() or len(content) > max_chars):
            raise ValueError("empty or oversized answer")
        if "reasoning_content" in message and not isinstance(
            message["reasoning_content"], (str, type(None))
        ):
            raise ValueError("invalid reasoning")
        if thinking_tools and tools and "reasoning_content" not in message:
            raise ValueError("missing tool reasoning")
        assistant = {"role": "assistant", "content": content if content is not None else ""}
        for key in ("reasoning_content", "tool_calls"):
            if key in message:
                assistant[key] = message[key]
        return Decision(content=content, tools=tools, assistant_message=assistant)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ModelProtocolError("invalid_model_response") from None


def validate_tools(
    decision: Decision,
    allowed: tuple[str, ...],
    *,
    request: dict | None = None,
    recover_arguments: bool = False,
) -> None:
    if request is not None:
        advertised = {tool["function"]["name"] for tool in request.get("tools", [])}
        allowed = tuple(name for name in allowed if name in advertised)
    for call in decision.tools:
        if call.name not in allowed or call.name not in REGISTRY:
            raise ModelProtocolError("tool_not_allowed")
        if recover_arguments:
            continue
        try:
            REGISTRY[call.name].validate(call.arguments)
        except ValueError:
            raise ModelProtocolError("invalid_tool_arguments") from None
