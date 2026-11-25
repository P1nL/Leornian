from functools import partial
from typing import Protocol
from uuid import UUID

from leornian.agent_runtime.contracts import Decision, Lease, RoleSpec, StoredCall
from leornian.agent_runtime.gateway import (
    ChatCompletionsGateway,
    DeliveryUnknown,
    ModelProtocolError,
    parse_decision,
    validate_tools,
)
from leornian.agent_runtime.lease import maintain_lease
from leornian.agent_runtime.policies import estimate_tokens
from leornian.agent_runtime.tools import contracts
from leornian.shared_kernel.errors import BusinessError


class RuntimePort(Protocol):
    def claim(self, run_id: UUID) -> Lease | None: ...
    def context(self, lease: Lease) -> RoleSpec | None: ...
    def latest(self, lease: Lease) -> StoredCall | None: ...
    def prepare(
        self, lease: Lease, endpoint: str, request: dict, policy=None, manifest=None
    ) -> StoredCall | None: ...
    def heartbeat(self, lease: Lease) -> bool: ...
    def yield_run(self, lease: Lease) -> None: ...
    def token_calibration(self, endpoint: str, model: str, stage: str) -> float: ...
    def dispatch(self, lease: Lease, call_id: UUID) -> bool: ...
    def record(self, call_id: UUID, receipt=None, *, unknown: bool = False) -> None: ...
    def apply(self, lease: Lease, call: StoredCall, decision: Decision) -> bool: ...
    def apply_web_lookup(self, lease: Lease, call: StoredCall) -> bool: ...
    def fail(self, lease: Lease, code: str) -> None: ...
    def block_unknown(self, lease: Lease) -> None: ...


class AgentLoop:
    def __init__(self, port: RuntimePort, gateway: ChatCompletionsGateway):
        self.port = port
        self.gateway = gateway

    def run(self, run_id: UUID) -> None:
        lease = self.port.claim(run_id)
        if lease is None:
            return
        try:
            # A scheduling quantum is not a generation-task attempt limit. Item repairs are
            # separate durable wakeups; the interactive Tutor retains its tool-loop contract.
            for _ in range(4):
                role = self.port.context(lease)
                if role is None:
                    return
                call = self.port.latest(lease)
                gateway = (
                    self.port.gateway_for(lease, role, call, self.gateway)
                    if hasattr(self.port, "gateway_for")
                    else self.gateway
                )
                if gateway is None:
                    return
                if call is None or call.applied:
                    supply = role.policy_version.startswith("item_") or (
                        role.policy_version == "transfer_relation.v1"
                    )
                    if call and call.step >= 3 and not supply and not role.completion_driven:
                        self.port.fail(lease, "step_limit")
                        return
                    if (
                        call
                        and call.applied
                        and call.policy_snapshot
                        and not call.context_manifest.get("node_web_lookup")
                        and role.messages
                        and role.messages[-1]["role"] == "tool"
                    ):
                        # Finish the tool turn under its original protocol/channel policy.
                        policy = dict(call.policy_snapshot)
                    elif (
                        gateway.settings.delivery_enabled
                        or gateway.settings.model_thinking == "enabled"
                        or gateway.settings.model_stage_thinking.strip() not in {"", "{}"}
                    ):
                        policy = gateway.policy(role)
                    else:
                        policy = None
                    if policy:
                        policy["estimator_factor"] = self.port.token_calibration(
                            gateway.endpoint,
                            gateway.settings.model_name,
                            role.policy_version,
                        )
                    request = gateway.request(
                        role.messages,
                        require_tool=call is None
                        and bool(role.allowed_tools)
                        and role.require_initial_tool,
                        allowed_tools=role.allowed_tools,
                        json_output=(role.json_output or role.policy_version != "tutor.v1")
                        and not bool(role.allowed_tools),
                        policy=policy,
                        optional_history=role.optional_history,
                        output_tokens=4800
                        if role.policy_version
                        in {
                            "item_author.v1",
                            "item_blind.v1",
                            "item_review.v1",
                            "gate_relation.v1",
                            "transfer_relation.v1",
                        }
                        else None,
                    )
                    manifest = {
                        **role.context_manifest,
                        "tool_contracts": contracts(role.allowed_tools),
                        "selected_history": [
                            pair[0]["content"].split("\n", 1)[0]
                            for pair in role.optional_history
                            if pair[0] in request["messages"]
                        ],
                    }
                    if gateway.model_binding:
                        manifest["model_binding"] = gateway.model_binding
                    if call and call.status == "not_sent":
                        manifest["replaces_unsent_call_id"] = str(call.id)
                    if policy:
                        policy["estimated_input_tokens"] = estimate_tokens(request)
                    call = self.port.prepare(lease, gateway.endpoint, request, policy, manifest)
                if call is None:
                    return
                lookup = bool(call.context_manifest.get("node_web_lookup"))
                if call.status == "prepared":
                    gateway.check_destination(call.endpoint, call.request)
                    if not self.port.dispatch(lease, call.id):
                        return
                    if hasattr(self.port, "model_progress"):
                        gateway.progress_callback = partial(
                            self.port.model_progress, lease, role.policy_version,
                        )
                    gateway.thinking_callback = (
                        partial(self.port.model_thinking, lease, role.policy_version)
                        if hasattr(self.port, "model_thinking")
                        and not lookup
                        and role.policy_version in {"planner.v1", "tutor.v1"}
                        else None
                    )
                    with maintain_lease(
                        self.port, lease, gateway.settings.heartbeat_seconds
                    ) as lost:
                        try:
                            receipt = gateway.send(
                                call.endpoint, call.request, policy=call.policy_snapshot or None
                            )
                        except DeliveryUnknown:
                            self.port.record(call.id, unknown=True)
                        else:
                            self.port.record(call.id, receipt)
                        if lost.is_set():
                            return
                    call = self.port.latest(lease)
                    if call is None:
                        return
                if call.status in {"dispatching", "unknown"}:
                    self.port.block_unknown(lease)
                    return
                if lookup and call.status in {"result_recorded", "failed_known"}:
                    if self.port.apply_web_lookup(lease, call):
                        self.port.yield_run(lease)
                    return
                if call.status == "failed_known":
                    self.port.fail(lease, "provider_rejected")
                    return
                if call.status != "result_recorded" or call.response_body is None:
                    return
                decision = parse_decision(
                    call.response_body,
                    max_chars=call.policy_snapshot.get("response_bytes", 16000),
                    thinking_tools=(call.request.get("thinking") == {"type": "enabled"}
                        or call.request.get("enable_thinking") is True)
                    and bool(call.request.get("tools")),
                    recover_arguments=role.recover_tool_errors,
                )
                validate_tools(
                    decision,
                    role.allowed_tools,
                    request=call.request,
                    recover_arguments=role.recover_tool_errors,
                )
                if not self.port.apply(lease, call, decision):
                    return
                if role.completion_driven:
                    self.port.yield_run(lease)
                    return
        except ModelProtocolError as error:
            self.port.fail(lease, error.code)
        except BusinessError as error:
            self.port.fail(lease, error.code)
