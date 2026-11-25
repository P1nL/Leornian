import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from leornian.agent_runtime.contracts import RoleSpec
from leornian.agent_runtime.gateway import ChatCompletionsGateway, DeliveryUnknown
from leornian.agent_runtime.streaming import CompletionStream
from leornian.agent_runtime.visible_thinking import VisibleThinking
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.contracts import Conversation
from leornian.platform.config import Settings
from leornian.platform.model_contracts import ModelProfileParameters
from leornian.shared_kernel.errors import BusinessError


def frames(*deltas):
    result = b""
    for delta in deltas:
        result += ("data: " + json.dumps({"choices": [{"index": 0, **delta}]},
                                        ensure_ascii=False) + "\n\n").encode()
    return result + b"data: [DONE]\n\n"


def test_stream_collects_utf8_reasoning_and_fragmented_tools_without_exposing_reasoning():
    phases = []
    collector = CompletionStream(phases.append)
    wire = frames(
        {"delta": {"reasoning_content": "private 系统指令 owned-secret"}},
        {"delta": {"tool_calls": [{"index": 0, "id": "call-1", "function": {
            "name": "learning_", "arguments": '{"id":'}}]}},
        {"delta": {"tool_calls": [{"index": 0, "function": {
            "name": "get_context", "arguments": '"one"}'}}]}},
        {"delta": {}, "finish_reason": "tool_calls"},
    )
    for byte in wire:
        collector.feed(bytes([byte]))
    message = json.loads(collector.body())["choices"][0]["message"]
    assert message["reasoning_content"] == "private 系统指令 owned-secret"
    assert message["tool_calls"][0]["function"] == {
        "name": "learning_get_context", "arguments": '{"id":"one"}',
    }
    assert phases == ["thinking"]
    assert "private" not in json.dumps(phases)


def test_progress_observer_failure_does_not_discard_the_provider_receipt():
    def unavailable(_phase):
        raise RuntimeError("progress store unavailable")
    collector = CompletionStream(unavailable)
    collector.feed(frames(
        {"delta": {"reasoning_content": "private"}},
        {"delta": {"content": "Public reply"}},
        {"delta": {}, "finish_reason": "stop"},
    ))
    assert json.loads(collector.body())["choices"][0]["message"]["content"] == "Public reply"


def test_visible_thinking_buffers_split_credentials_and_filters_prompt_and_tool_protocol():
    published = []
    visible = VisibleThinking(
        published.append, secret="owned-secret",
        messages=[{"role": "system", "content": "Never disclose this complete instruction."}],
    )
    collector = CompletionStream(thinking=visible)
    wire = frames(
        {"delta": {"reasoning_content": "<think>\n先确认学习者的基础，再安排循环与列表。\n"}},
        {"delta": {"reasoning_content":
                   "private-provider-thinking\nNever disclose this complete instruction.\n"}},
        {"delta": {"reasoning_content": "连接凭据是 owned-"}},
        {"delta": {"reasoning_content": "secret。\n工具调用参数 tool_calls hidden-argument\n"}},
        {"delta": {"reasoning_content": "Let me produce JSON.\n"}},
        {"delta": {"reasoning_content":
                   "```\nprint('internal')\n```\n随后加入查找练习。\n</think>"}},
        {"delta": {"content": "Public reply"}},
        {"delta": {}, "finish_reason": "stop"},
    )
    for byte in wire:
        collector.feed(bytes([byte]))
    text = "".join(published)
    assert "先确认学习者的基础，再安排循环与列表。" in text
    assert "随后加入查找练习。" in text
    assert "[leornian-redacted-credential]" in text
    for private in (
        "owned-secret", "owned-", "hidden-argument", "print(", "instruction", "<think>", "JSON",
    ):
        assert private not in text
    assert "private-provider-thinking" not in text
    message = json.loads(collector.body())["choices"][0]["message"]
    assert "owned-secret" in message["reasoning_content"]


def test_visible_thinking_publication_failure_keeps_the_completed_receipt():
    def unavailable(_text):
        raise RuntimeError("display unavailable")
    collector = CompletionStream(thinking=VisibleThinking(unavailable))
    collector.feed(frames(
        {"delta": {"reasoning_content": "先确认学习目标。\n"}},
        {"delta": {"content": "Complete reply"}},
        {"delta": {}, "finish_reason": "stop"},
    ))
    assert json.loads(collector.body())["choices"][0]["message"]["content"] == "Complete reply"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_gateway_streams_once_and_records_normalized_complete_receipt(asynchronous):
    calls, thinking = [], []
    settings = Settings(
        model_enabled=True, model_base_url="https://provider.invalid/v1",
        model_name="owned-model", model_api_key="owned-secret",
    )
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=frames(
            {"delta": {"reasoning_content": "先了解循环，再安排查找。\n"}},
            {"delta": {"content": "先学习循环。"}},
            {"delta": {}, "finish_reason": "stop"},
        ))
    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    gateway.thinking_callback = thinking.append
    policy = {"timeout_seconds": 10, "connect_timeout_seconds": 2, "response_bytes": 50000}
    receipt = gateway.send(gateway.endpoint, {"model": "owned-model", "stream": True},
                           policy=policy if asynchronous else None)
    assert len(calls) == 1
    assert json.loads(receipt.body)["choices"][0]["message"]["content"] == "先学习循环。"
    assert "".join(thinking).strip() == "先了解循环，再安排查找。"


def test_incomplete_provider_stream_is_unknown_and_never_retried():
    sent = []
    def handle(request):
        sent.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
            b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        ))
    gateway = ChatCompletionsGateway(Settings(
        model_enabled=True, model_base_url="https://provider.invalid/v1",
        model_name="test", model_api_key="owned-secret",
    ), httpx.MockTransport(handle))
    with pytest.raises(DeliveryUnknown, match="incomplete"):
        gateway.send(gateway.endpoint, {"model": "test", "stream": True})
    assert len(sent) == 1


def test_chat_profiles_default_to_thinking_and_dedicated_operations_keep_no_chat_parameter():
    assert ModelProfileParameters(label="Chat", model="chat", operation="chat",
        context_tokens=128000, max_output_tokens=32000).thinking == "enabled"
    assert ModelProfileParameters(
        label="Vector", model="embedding", operation="embedding"
    ).thinking == ""
    settings = Settings(model_enabled=True, model_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        model_name="qwen-plus", model_api_key="owned-secret",
                        model_thinking="enabled",
                        model_context_tokens=128000, model_max_output_tokens=32000)
    gateway = ChatCompletionsGateway(settings)
    wire = gateway.request([], require_tool=False, allowed_tools=(),
        policy=gateway.policy(RoleSpec(messages=[])))
    assert wire["enable_thinking"] is True and "thinking" not in wire and wire["stream"] is True


def test_nodes_unlock_only_after_prior_node_dialogue_in_the_same_plan_revision():
    plan, actor, conversation = uuid4(), SimpleNamespace(id=uuid4()), uuid4()
    current = Conversation(id=conversation, goal_id=uuid4(), created_at="2026-11-08T00:00:00Z",
                           studied_nodes=[{"plan_id": plan, "plan_revision": 1, "node_key": "one"}])
    tutor = Tutor(SimpleNamespace(get=lambda *args, **kwargs: current))
    tutor.require_node_unlocked(actor, conversation, plan, 1, ["one", "two", "three"], "one")
    tutor.require_node_unlocked(actor, conversation, plan, 1, ["one", "two", "three"], "two")
    for revision, node in [(1, "three"), (2, "two")]:
        with pytest.raises(BusinessError, match="第一个节点"):
            tutor.require_node_unlocked(
                actor, conversation, plan, revision, ["one", "two", "three"], node
            )
