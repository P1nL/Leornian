"""One resolved budget for context construction, transport and durable replay."""

import json
import math
from typing import Any
from urllib.parse import urlsplit

from leornian.shared_kernel.errors import BusinessError

STAGES = {
    "tutor.v1": (16384, 300),
    "planner.v1": (16384, 300),
    "lesson.v1": (12000, 600),
    "item_author.v1": (16384, 600),
    "item_blind.v1": (16384, 600),
    "item_review.v1": (8192, 300),
    "gate_relation.v1": (8192, 300),
    "transfer_relation.v1": (8192, 300),
    "evaluation.v1": (6000, 180),
    "delivery_review.v1": (8192, 300),
    "artifact.v1": (12000, 600),
    "material_check.v1": (8192, 300),
    "material_review.v1": (8192, 300),
}


def estimate_tokens(value: Any) -> int:
    # Deliberately labelled estimate, not a provider tokenizer or a byte/token identity.
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(sum(1.5 if ord(char) > 127 else 0.35 for char in text))


def resolve_policy(settings, role, capability: dict) -> dict:
    window, maximum = capability["context_window"], capability["max_output_tokens"]
    if window <= 0 or maximum <= 0:
        raise BusinessError("model_unavailable", "Register the current channel's token capacity.")
    try:
        overrides = json.loads(settings.model_stage_thinking or "{}")
        if not isinstance(overrides, dict) or any(
            stage not in STAGES or value not in {"enabled", "disabled"}
            for stage, value in overrides.items()
        ):
            raise ValueError("Invalid stage thinking configuration.")
    except (TypeError, ValueError):
        raise BusinessError(
            "model_unavailable", "Stage thinking overrides need known stages and enabled/disabled."
        ) from None
    fallback = (
        overrides.get("tutor.v1", settings.model_thinking or None)
        if role.policy_version == "artifact.v1"
        else settings.model_thinking or None
    )
    thinking = overrides.get(role.policy_version, fallback)
    if thinking not in {None, "enabled", "disabled"}:
        raise BusinessError("model_unavailable", "Unsupported thinking configuration.")
    if settings.model_output_budget_multiplier < 1:
        raise BusinessError("model_unavailable", "Output budget multiplier must be positive.")
    base, timeout = STAGES[role.policy_version]
    final_target = min(
        base * settings.model_output_budget_multiplier * role.output_multiplier, maximum
    )
    output = maximum if thinking == "enabled" else final_target
    margin = max(256, math.ceil(window * 0.005))
    if final_target + margin >= window:
        raise BusinessError("model_unavailable", "Output reservation cannot fit this channel.")
    policy = {
        "version": "stage-policy.v2",
        "stage": role.policy_version,
        "model": settings.model_name,
        "context_window": window,
        "max_output_tokens": output,
        "model_max_output_tokens": maximum,
        "final_output_target_tokens": final_target,
        "reasoning_token_limit": None,
        "output_budget_kind": "shared_reasoning_and_content"
        if thinking == "enabled"
        else "content",
        "input_limit": min(
            capability.get("max_input_tokens", window), window - final_target - margin
        ),
        "estimate_margin": margin,
        "timeout_seconds": timeout,
        "connect_timeout_seconds": 10,
        "thinking": thinking,
        "response_bytes": max(256000, output * 32),
        "capability_source": capability.get("source", "operator"),
    }
    if role.policy_version == "delivery_review.v1" and (
        scope := role.context_manifest.get("review_scope")
    ) in {"full", "operation_impact"}:
        policy["review_scope"] = scope
    if (
        thinking == "enabled"
        and (role.policy_version == "material_check.v1" or
             policy.get("review_scope") == "operation_impact")
        and urlsplit(settings.model_base_url).hostname == "api.deepseek.com"
        and settings.model_name in {"deepseek-flash", "deepseek-v4-pro"}
    ):
        policy["reasoning_effort"] = "low"
    return policy


def allocate_output(request: dict, policy: dict) -> dict:
    """Resolve NEW requests only; existing prepared request/policy pairs remain immutable."""
    if policy.get("version") != "stage-policy.v2" or policy.get("thinking") != "enabled":
        return request
    input_estimate = math.ceil(estimate_tokens(request) * policy.get("estimator_factor", 1.0))
    available = min(
        policy["model_max_output_tokens"],
        policy["context_window"] - input_estimate - policy["estimate_margin"],
    )
    if available < policy["final_output_target_tokens"]:
        raise BusinessError("precondition_failed", "Required input exceeds the channel budget.")
    policy["max_output_tokens"] = available
    policy["response_bytes"] = max(256000, available * 32)
    policy["calibrated_input_tokens"] = input_estimate
    return {**request, "max_tokens": available}


def fit_optional_history(request: dict, history: list[list[dict]], policy: dict) -> dict:
    """Keep required input atomic; add complete, recent dialogue pairs if they fit."""
    factor = policy.get("estimator_factor", 1.0)
    if estimate_tokens(request) * factor > policy["input_limit"]:
        raise BusinessError("precondition_failed", "Required input exceeds the channel budget.")
    base = request["messages"]
    anchor = next((i for i, message in enumerate(base) if message["role"] == "user"), len(base))
    selected = []
    for pair in reversed(history):
        proposed = {**request, "messages": base[:anchor] + pair + selected + base[anchor:]}
        if estimate_tokens(proposed) * factor <= policy["input_limit"]:
            selected = pair + selected
    return {**request, "messages": base[:anchor] + selected + base[anchor:]}
