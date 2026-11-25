import json
from dataclasses import replace

import httpx
import pytest

from leornian.agent_runtime.contracts import RoleSpec
from leornian.agent_runtime.gateway import (
    ChatCompletionsGateway,
    DeliveryUnknown,
    ModelProtocolError,
    parse_decision,
    validate_tools,
)
from leornian.agent_runtime.policies import estimate_tokens, resolve_policy
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


@pytest.mark.parametrize("body", ["null", "[]", "{}", '{"choices":[null]}', "invalid"])
def test_malformed_model_bodies_are_known_validation_failures(body):
    with pytest.raises(ModelProtocolError):
        parse_decision(body)


def test_completed_thinking_with_whitespace_final_has_a_specific_known_error():
    body = json.dumps({"choices": [{
        "message": {
            "role": "assistant", "content": " " * 545,
            "reasoning_content": "owned-private-reasoning",
        },
        "finish_reason": "stop",
    }]})
    with pytest.raises(ModelProtocolError) as error:
        parse_decision(body)
    assert error.value.code == "empty_model_response"
    assert "owned-private-reasoning" not in str(error.value)


def test_json_output_guidance_preserves_thinking_and_does_not_mutate_source_messages():
    settings = Settings(
        model_enabled=True, model_base_url="https://provider.invalid/v1",
        model_name="owned-test", model_api_key="owned-secret", model_thinking="enabled",
    )
    messages = [
        {"role": "system", "content": "Return the required object."},
        {"role": "user", "content": "Collect my learning requirements."},
    ]
    role = RoleSpec(policy_version="planner.v1", allowed_tools=(), messages=messages)
    policy = resolve_policy(settings, role, {"context_window": 128000, "max_output_tokens": 32768})
    gateway = ChatCompletionsGateway(settings)
    for _ in range(2):
        wire = gateway.request(
            messages, require_tool=False, allowed_tools=(), json_output=True, policy=policy,
        )
        assert wire["thinking"] == {"type": "enabled"}
        assert wire["response_format"] == {"type": "json_object"}
        assert wire["messages"][0]["content"].count("Final output contract:") == 1
        assert "never just whitespace" in wire["messages"][0]["content"]
    assert messages[0]["content"] == "Return the required object."


def test_gateway_does_not_follow_redirects_or_retry_transport_errors():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://provider.invalid/v1",
        model_name="owned-test",
        model_api_key="owned-secret",
    )
    seen = []

    def redirect(request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "https://elsewhere.invalid"})

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(redirect))
    request = gateway.request([{"role": "user", "content": "Hello"}], require_tool=True)
    assert gateway.send(gateway.endpoint, request).http_status == 307
    assert len(seen) == 1

    def timeout(request):
        seen.append(request)
        raise httpx.ConnectTimeout("owned test")

    seen.clear()
    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(timeout))
    with pytest.raises(DeliveryUnknown):
        gateway.send(gateway.endpoint, request)
    assert len(seen) == 1
    assert "owned-secret" not in json.dumps(request)


def test_configuration_needs_explicit_enablement_and_secure_endpoint():
    assert not ChatCompletionsGateway(Settings()).availability().ready
    assert (
        not ChatCompletionsGateway(
            Settings(
                model_enabled=True,
                model_base_url="http://remote.invalid/v1",
                model_name="test",
                model_api_key="owned-secret",
            )
        )
        .availability()
        .ready
    )


def test_deepseek_forced_tools_require_explicit_non_thinking_configuration():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        model_api_key="owned-secret",
        model_thinking="disabled",
    )
    request = ChatCompletionsGateway(settings).request(
        [{"role": "user", "content": "Explain loops"}],
        require_tool=True,
    )
    assert request["thinking"] == {"type": "disabled"}
    assert request["tool_choice"]["function"]["name"] == "learning_get_context"
    generic = ChatCompletionsGateway(replace(settings, model_thinking="")).request(
        [{"role": "user", "content": "Explain loops"}],
        require_tool=True,
    )
    assert "thinking" not in generic


def test_stage_thinking_override_is_frozen_in_policy_and_does_not_change_legacy_tools():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        model_api_key="owned-secret",
        model_thinking="disabled",
        model_stage_thinking='{"item_author.v1":"enabled"}',
    )
    capability = {"context_window": 128000, "max_output_tokens": 32768}
    role = RoleSpec(policy_version="item_author.v1", allowed_tools=(), messages=[])
    policy = resolve_policy(settings, role, capability)
    assert policy["thinking"] == "enabled"
    # Dispatch of prepared work uses the persisted policy, not a new operator setting.
    gateway = ChatCompletionsGateway(replace(settings, model_stage_thinking="{}"))
    wire = gateway.request(
        [{"role": "user", "content": "Author JSON."}],
        require_tool=False,
        allowed_tools=(),
        json_output=True,
        policy=policy,
    )
    assert wire["thinking"] == {"type": "enabled"}
    assert "tools" not in wire and "tool_choice" not in wire
    legacy = resolve_policy(settings, RoleSpec(messages=[]), capability)
    assert legacy["thinking"] == "disabled"
    assert (
        resolve_policy(replace(settings, model_stage_thinking=""), role, capability)["thinking"]
        == "disabled"
    )


@pytest.mark.parametrize("stage,manifest", [
    ("material_check.v1", {}), ("delivery_review.v1", {"review_scope": "operation_impact"}),
])
def test_scoped_deepseek_checks_use_low_effort_without_lowering_capacity(stage, manifest):
    settings = Settings(
        model_enabled=True, model_base_url="https://api.deepseek.com",
        model_name="deepseek-flash", model_api_key="owned-secret", model_thinking="enabled",
    )
    capability = {"context_window": 1048576, "max_output_tokens": 393216}
    role = RoleSpec(policy_version=stage, context_manifest=manifest, allowed_tools=(), messages=[])
    policy = resolve_policy(settings, role, capability)
    gateway = ChatCompletionsGateway(replace(settings, model_thinking="disabled"))
    wire = gateway.request(
        [{"role": "user", "content": "Check the supplied evidence."}],
        require_tool=False, allowed_tools=(), json_output=True, policy=policy,
    )
    assert wire["thinking"] == {"type": "enabled"}
    assert wire["reasoning_effort"] == policy["reasoning_effort"] == "low"
    assert wire["max_tokens"] == policy["model_max_output_tokens"] == 393216
    assert "reasoning_effort" not in resolve_policy(
        settings, RoleSpec(policy_version="planner.v1", messages=[]), capability,
    )
    assert "reasoning_effort" not in resolve_policy(
        settings, RoleSpec(policy_version="delivery_review.v1", messages=[]), capability,
    )
    assert "reasoning_effort" not in resolve_policy(
        replace(settings, model_base_url="https://provider.invalid/v1"), role, capability,
    )
    assert "reasoning_effort" not in resolve_policy(
        replace(settings, model_thinking="disabled"), role, capability,
    )
    legacy = {key: value for key, value in policy.items() if key != "reasoning_effort"}
    assert "reasoning_effort" not in gateway.request(
        role.messages, require_tool=False, allowed_tools=(), policy=legacy,
    )


@pytest.mark.parametrize(
    "stage",
    ["tutor.v1", "planner.v1", "lesson.v1", "delivery_review.v1", "evaluation.v1"],
)
def test_teaching_stage_thinking_uses_the_frozen_no_tool_policy(stage):
    settings = Settings(
        model_enabled=True,
        model_base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        model_api_key="owned-secret",
        model_thinking="disabled",
        model_stage_thinking=json.dumps({stage: "enabled"}),
    )
    policy = resolve_policy(
        settings,
        RoleSpec(policy_version=stage, allowed_tools=(), messages=[]),
        {"context_window": 128000, "max_output_tokens": 32768},
    )
    gateway = ChatCompletionsGateway(replace(settings, model_stage_thinking="{}"))
    wire = gateway.request(
        [{"role": "user", "content": "Teach the selected objective."}],
        require_tool=False,
        allowed_tools=(),
        json_output=stage != "tutor.v1",
        policy=policy,
    )
    assert policy["stage"] == stage and policy["thinking"] == "enabled"
    assert wire["thinking"] == {"type": "enabled"}
    assert "tools" not in wire and "tool_choice" not in wire
    assert wire["max_tokens"] == policy["max_output_tokens"]


@pytest.mark.parametrize(
    "value", ["invalid", "[]", '{"unknown.v1":"enabled"}', '{"item_author.v1":"guess"}']
)
def test_invalid_stage_thinking_is_rejected_before_dispatch(value):
    with pytest.raises(BusinessError) as error:
        resolve_policy(
            Settings(model_stage_thinking=value),
            RoleSpec(policy_version="item_author.v1", allowed_tools=(), messages=[]),
            {"context_window": 128000, "max_output_tokens": 32768},
        )
    assert error.value.code == "model_unavailable"


def test_thinking_tools_use_auto_without_forcing_or_disabling_reasoning():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        model_api_key="owned-secret",
        model_stage_thinking='{"tutor.v1":"enabled"}',
    )
    policy = resolve_policy(
        settings,
        RoleSpec(messages=[]),
        {"context_window": 128000, "max_output_tokens": 32768},
    )
    wire = ChatCompletionsGateway(settings).request(
        [{"role": "user", "content": "Read my current goal first."}],
        require_tool=True,
        policy=policy,
    )
    assert wire["thinking"] == {"type": "enabled"}
    assert [t["function"]["name"] for t in wire["tools"]] == ["learning_get_context"]
    assert "tool_choice" not in wire
    assert policy["reasoning_token_limit"] is None
    assert wire["max_tokens"] == 32768 > policy["final_output_target_tokens"]


def test_thinking_output_uses_remaining_window_not_the_stage_body_reservation():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        model_api_key="owned-secret",
        model_thinking="enabled",
    )
    policy = resolve_policy(
        settings,
        RoleSpec(policy_version="item_review.v1", allowed_tools=(), messages=[]),
        {"context_window": 40000, "max_output_tokens": 32768},
    )
    policy["estimator_factor"] = 1.1
    wire = ChatCompletionsGateway(settings).request(
        [{"role": "user", "content": "x" * 70000}],
        require_tool=False,
        allowed_tools=(),
        policy=policy,
    )
    assert policy["final_output_target_tokens"] == 8192
    assert 8192 < wire["max_tokens"] < 32768
    assert (
        policy["calibrated_input_tokens"] + wire["max_tokens"] + policy["estimate_margin"] == 40000
    )
    assert estimate_tokens(wire) * 1.1 <= policy["input_limit"]


@pytest.mark.parametrize(
    ("stage", "target", "timeout"),
    [
        ("tutor.v1", 65536, 300),
        ("planner.v1", 65536, 300),
        ("lesson.v1", 48000, 600),
        ("item_author.v1", 65536, 600),
        ("item_blind.v1", 65536, 600),
        ("item_review.v1", 32768, 300),
        ("gate_relation.v1", 32768, 300),
        ("transfer_relation.v1", 32768, 300),
        ("evaluation.v1", 24000, 180),
        ("delivery_review.v1", 32768, 300),
        ("artifact.v1", 48000, 600),
    ],
)
def test_explicit_512k_budget_scales_stage_output_and_derived_limits(stage, target, timeout):
    policy = resolve_policy(
        Settings(
            model_output_budget_multiplier=4, model_thinking="", model_stage_thinking="{}"
        ),
        RoleSpec(policy_version=stage, messages=[]),
        {"context_window": 512000, "max_output_tokens": 131072},
    )
    assert policy["final_output_target_tokens"] == policy["max_output_tokens"] == target
    assert policy["model_max_output_tokens"] == 131072
    assert policy["estimate_margin"] == 2560
    assert policy["input_limit"] == 512000 - target - 2560
    assert policy["response_bytes"] == target * 32
    assert policy["timeout_seconds"] == timeout


def test_scaled_output_still_respects_channel_input_and_output_caps():
    policy = resolve_policy(
        Settings(
            model_output_budget_multiplier=4, model_thinking="", model_stage_thinking="{}"
        ),
        RoleSpec(messages=[], output_multiplier=2),
        {"context_window": 512000, "max_output_tokens": 32768, "max_input_tokens": 400000},
    )
    assert policy["final_output_target_tokens"] == policy["max_output_tokens"] == 32768
    assert policy["input_limit"] == 400000
    with pytest.raises(BusinessError) as error:
        resolve_policy(
            Settings(model_output_budget_multiplier=0),
            RoleSpec(messages=[]),
            {"context_window": 512000, "max_output_tokens": 131072},
        )
    assert error.value.code == "model_unavailable"


def test_new_512k_configuration_does_not_recalculate_prepared_policy_or_default_targets():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://provider.invalid/v1",
        model_name="owned-test",
        model_api_key="owned-secret",
        model_thinking="",
        model_stage_thinking="{}",
        model_context_tokens=512000,
        model_max_output_tokens=131072,
        model_output_budget_multiplier=4,
    )
    role = RoleSpec(messages=[])
    gateway = ChatCompletionsGateway(settings)
    policy = gateway.policy(role)
    wire = gateway.request(
        [{"role": "user", "content": "x" * 400000}],
        require_tool=False,
        allowed_tools=(),
        policy=policy,
    )
    assert wire["max_tokens"] == 65536
    assert policy["input_limit"] == 443904
    default_settings = replace(settings, model_output_budget_multiplier=1)
    assert (
        ChatCompletionsGateway(default_settings).policy(role)["final_output_target_tokens"] == 16384
    )
    old_policy = resolve_policy(
        default_settings, role, {"context_window": 128000, "max_output_tokens": 32768}
    )
    frozen = old_policy.copy()
    old_wire = gateway.request(
        [{"role": "user", "content": "Use the original prepared budget."}],
        require_tool=False,
        allowed_tools=(),
        policy=old_policy,
    )
    assert old_policy == frozen
    assert old_wire["max_tokens"] == 16384
    assert old_policy["input_limit"] == 110976


def test_512k_thinking_output_still_fits_the_remaining_window():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://provider.invalid/v1",
        model_name="owned-test",
        model_api_key="owned-secret",
        model_thinking="enabled",
        model_stage_thinking="{}",
        model_context_tokens=512000,
        model_max_output_tokens=131072,
        model_output_budget_multiplier=4,
    )
    gateway = ChatCompletionsGateway(settings)
    policy = gateway.policy(RoleSpec(messages=[]))
    wire = gateway.request(
        [{"role": "user", "content": "x" * 1200000}],
        require_tool=False,
        allowed_tools=(),
        policy=policy,
    )
    assert policy["final_output_target_tokens"] == 65536
    assert 65536 < wire["max_tokens"] < 131072
    assert (
        policy["calibrated_input_tokens"] + wire["max_tokens"] + policy["estimate_margin"] == 512000
    )
    assert policy["response_bytes"] == wire["max_tokens"] * 32


def test_tool_reasoning_is_preserved_but_not_serialized_as_a_public_decision():
    message = {
        "role": "assistant",
        "content": "Reading the selected context.",
        "reasoning_content": "private reasoning " * 3000,
        "tool_calls": [
            {
                "id": "exact-id",
                "type": "function",
                "function": {"name": "learning_get_context", "arguments": "{ \n }"},
            }
        ],
    }
    decision = parse_decision(
        json.dumps(
            {
                "choices": [{"message": message, "finish_reason": "tool_calls"}],
            }
        ),
        max_chars=100,
        thinking_tools=True,
    )
    assert decision.assistant_message == message
    assert decision.tools[0].arguments == {}
    assert "private reasoning" not in decision.model_dump_json()
    assert "private reasoning" not in repr(decision)
    # Deploying a newly tool-capable role does not authorize tools on old no-tool calls.
    with pytest.raises(ModelProtocolError) as error:
        validate_tools(decision, ("learning_get_context",), request={"messages": []})
    assert error.value.code == "tool_not_allowed"
    message.pop("reasoning_content")
    with pytest.raises(ModelProtocolError):
        parse_decision(
            json.dumps(
                {
                    "choices": [{"message": message, "finish_reason": "tool_calls"}],
                }
            ),
            thinking_tools=True,
        )


def test_final_content_validation_does_not_count_reasoning_as_body():
    decision = parse_decision(
        json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "A concise final answer.",
                            "reasoning_content": "private" * 10000,
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
        max_chars=40,
    )
    assert decision.content == "A concise final answer."


def test_old_frozen_policy_is_not_reallocated_using_new_budget_rules():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        model_api_key="owned-secret",
    )
    frozen = {
        "version": "stage-policy.v1",
        "max_output_tokens": 8192,
        "thinking": "enabled",
        "input_limit": 100000,
    }
    before = dict(frozen)
    wire = ChatCompletionsGateway(settings).request(
        [{"role": "user", "content": "Review JSON."}],
        require_tool=False,
        allowed_tools=(),
        policy=frozen,
    )
    assert frozen == before and wire["max_tokens"] == 8192
