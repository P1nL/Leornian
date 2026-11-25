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
from leornian.agent_runtime.streaming import CompletionStream
from leornian.agent_runtime.tools import REGISTRY
from leornian.agent_runtime.visible_thinking import VisibleThinking
from leornian.platform.config import Settings
from leornian.platform.model_network import (
    AsyncPinnedModelTransport,
    PinnedModelTransport,
    redact_credential,
    resolve_destination,
)
from leornian.shared_kernel.errors import BusinessError

TOOL = REGISTRY["learning_get_context"].wire()

_JSON_OUTPUT_INSTRUCTION = (
    "Final output contract: return exactly one complete JSON object matching the task's schema. "
    "Begin the final content with { and end with }. Put the actual answer in the appropriate "
    "JSON fields, with no Markdown fences or prose outside the object. Keep any reasoning in "
    "the separate reasoning channel; reasoning alone is not a final answer. "
    "The final content must contain the JSON object, never just whitespace."
)


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
        self._destination = None
        self.model_binding = None
        self.progress_callback = None
        self.thinking_callback = None

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
                        trust_env=not self.settings.model_network_guard,
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
        policy = resolve_policy(self.settings, role, self._capability)
        if self.settings.model_profile_timeout is not None:
            policy["timeout_seconds"] = self.settings.model_profile_timeout
        return policy

    def _transport(self, *, asynchronous=False):
        if not self.settings.model_network_guard:
            return self.transport or (
                httpx.AsyncHTTPTransport(retries=0)
                if asynchronous
                else httpx.HTTPTransport(retries=0)
            )
        if self._destination is None:
            self._destination = resolve_destination(
                self.settings.model_base_url, self.settings.model_local_endpoint
            )
        factory = AsyncPinnedModelTransport if asynchronous else PinnedModelTransport
        return factory(self.settings.model_base_url, self._destination, self.transport)

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
            "stream": True,
        }
        thinking = policy.get("thinking") if policy else self.settings.model_thinking
        if thinking:
            if thinking not in {"enabled", "disabled"}:
                raise ModelProtocolError("unsupported_thinking_mode")
            if thinking == "enabled" and policy is None:
                raise ModelProtocolError("thinking_policy_required")
            if "/compatible-mode/" in self.settings.model_base_url:
                request["enable_thinking"] = thinking == "enabled"
            else:
                request["thinking"] = {"type": thinking}
        if policy and policy.get("reasoning_effort"):
            request["reasoning_effort"] = policy["reasoning_effort"]
        if allowed_tools:
            if any(name not in REGISTRY for name in allowed_tools):
                raise ModelProtocolError("tool_not_allowed")
            shared_definition = {
                "prepare_learning_composition", "get_learning_component_contracts",
            } <= set(allowed_tools)
            request["tools"] = [
                REGISTRY[name].wire(
                    shared_composition=shared_definition and name != "prepare_learning_composition",
                )
                for name in allowed_tools
            ]
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
            # JSON-mode providers can mask non-JSON output with spaces.
            request["messages"] = [dict(message) for message in messages]
            if messages and messages[0]["role"] == "system" and isinstance(
                messages[0].get("content"), str
            ):
                request["messages"][0]["content"] += "\n\n" + _JSON_OUTPUT_INSTRUCTION
            else:
                request["messages"].insert(
                    0, {"role": "system", "content": _JSON_OUTPUT_INSTRUCTION},
                )
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

    def _receipt(self, body, status, request_id):
        # Some compatible providers echo the rejected API key in their error body.
        # Redact only this credential before any durable receipt or public content sees it.
        return Receipt(
            body=redact_credential(body, self.settings.model_api_key),
            http_status=status,
            provider_request_id=redact_credential(request_id or "", self.settings.model_api_key)[
                :200
            ]
            or None,
        )

    def _completion_stream(self, request):
        thinking = VisibleThinking(
            self.thinking_callback, secret=self.settings.model_api_key,
            messages=request.get("messages", ()),
        ) if self.thinking_callback else None
        return CompletionStream(self.progress_callback, thinking)

    def send(self, endpoint: str, request: dict[str, Any], *, policy=None) -> Receipt:
        self.check_destination(endpoint, request)
        if policy:
            return asyncio.run(self._send_with_deadline(endpoint, request, policy))
        started = time.monotonic()
        try:
            with (
                httpx.Client(
                    transport=self._transport(),
                    timeout=httpx.Timeout(self.settings.model_timeout, connect=10),
                    follow_redirects=False,
                    trust_env=not self.settings.model_network_guard,
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    json=request,
                    headers={"Authorization": f"Bearer {self.settings.model_api_key}"},
                ) as response,
            ):
                chunks = bytearray()
                stream = self._completion_stream(request) if (
                    200 <= response.status_code < 300 and
                    "text/event-stream" in response.headers.get("content-type", "")
                ) else None
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if stream:
                        try:
                            stream.feed(chunk)
                        except (ValueError, KeyError, TypeError):
                            raise DeliveryUnknown("invalid_completion_stream") from None
                    if (
                        len(chunks) > 256000
                        or time.monotonic() - started > self.settings.model_timeout
                    ):
                        raise DeliveryUnknown("incomplete_or_oversized_response")
                return self._receipt(
                    self._stream_body(stream, chunks),
                    response.status_code,
                    response.headers.get("x-request-id", "") or None,
                )
        except httpx.TransportError as error:
            # No SDK/HTTP retry: even a timeout may hide a completed provider request.
            raise DeliveryUnknown(type(error).__name__) from None

    async def _send_with_deadline(self, endpoint, request, policy):
        try:
            async with (
                asyncio.timeout(policy["timeout_seconds"]),
                httpx.AsyncClient(
                    transport=self._transport(asynchronous=True),
                    timeout=httpx.Timeout(
                        policy["timeout_seconds"], connect=policy["connect_timeout_seconds"]
                    ),
                    follow_redirects=False,
                    trust_env=not self.settings.model_network_guard,
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    json=request,
                    headers={"Authorization": f"Bearer {self.settings.model_api_key}"},
                ) as response,
            ):
                chunks = bytearray()
                stream = self._completion_stream(request) if (
                    200 <= response.status_code < 300 and
                    "text/event-stream" in response.headers.get("content-type", "")
                ) else None
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if stream:
                        try:
                            stream.feed(chunk)
                        except (ValueError, KeyError, TypeError):
                            raise DeliveryUnknown("invalid_completion_stream") from None
                    if len(chunks) > policy["response_bytes"]:
                        raise DeliveryUnknown("incomplete_or_oversized_response")
                return self._receipt(
                    self._stream_body(stream, chunks),
                    response.status_code,
                    response.headers.get("x-request-id", "") or None,
                )
        except (TimeoutError, httpx.TransportError) as error:
            raise DeliveryUnknown(type(error).__name__) from None

    @staticmethod
    def _stream_body(stream, chunks):
        if stream is None:
            return chunks.decode("utf-8", errors="replace")
        try:
            return stream.body()
        except ValueError:
            raise DeliveryUnknown("incomplete_completion_stream") from None

    def check_destination(self, endpoint: str, request: dict[str, Any]) -> None:
        self.require_ready()
        # Fail before dispatch if a prepared request belongs to a previous configuration.
        if endpoint != self.endpoint or request.get("model") != self.settings.model_name:
            raise ModelProtocolError("provider_configuration_changed")
        if self.settings.model_network_guard and self._destination is None:
            self._destination = resolve_destination(
                self.settings.model_base_url, self.settings.model_local_endpoint
            )


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
        if not tools and (not content or not content.strip()):
            raise ModelProtocolError("empty_model_response")
        if not tools and len(content) > max_chars:
            raise ValueError("oversized answer")
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
