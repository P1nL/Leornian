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
from leornian.shared_kernel.errors import BusinessError


class RuntimePort(Protocol):
    def claim(self, run_id: UUID) -> Lease | None: ...
    def context(self, lease: Lease) -> RoleSpec | None: ...
    def latest(self, lease: Lease) -> StoredCall | None: ...
    def prepare(self, lease: Lease, endpoint: str, request: dict) -> StoredCall | None: ...
    def dispatch(self, lease: Lease, call_id: UUID) -> bool: ...
    def record(self, call_id: UUID, receipt=None, *, unknown: bool = False) -> None: ...
    def apply(self, lease: Lease, call: StoredCall, decision: Decision) -> bool: ...
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
            # Bound by three persisted model steps, not by queue delivery count.
            for _ in range(4):
                role = self.port.context(lease)
                if role is None:
                    return
                call = self.port.latest(lease)
                if call is None or call.applied:
                    if call and call.step >= 3:
                        self.port.fail(lease, "step_limit")
                        return
                    request = self.gateway.request(
                        role.messages,
                        require_tool=call is None and bool(role.allowed_tools),
                        allowed_tools=role.allowed_tools,
                        json_output=role.policy_version in {"planner.v1", "lesson.v1"},
                    )
                    call = self.port.prepare(lease, self.gateway.endpoint, request)
                if call is None:
                    return
                if call.status == "prepared":
                    self.gateway.check_destination(call.endpoint, call.request)
                    if not self.port.dispatch(lease, call.id):
                        return
                    try:
                        receipt = self.gateway.send(call.endpoint, call.request)
                    except DeliveryUnknown:
                        self.port.record(call.id, unknown=True)
                    else:
                        # Record independently of the lease, including late/cancelled responses.
                        self.port.record(call.id, receipt)
                    call = self.port.latest(lease)
                    if call is None:
                        return
                if call.status in {"dispatching", "unknown"}:
                    self.port.block_unknown(lease)
                    return
                if call.status == "failed_known":
                    self.port.fail(lease, "provider_rejected")
                    return
                if call.status != "result_recorded" or call.response_body is None:
                    return
                decision = parse_decision(call.response_body)
                validate_tools(decision, role.allowed_tools)
                if not self.port.apply(lease, call, decision):
                    return
        except ModelProtocolError as error:
            self.port.fail(lease, error.code)
        except BusinessError as error:
            self.port.fail(lease, error.code)
