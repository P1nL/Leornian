from dataclasses import asdict

from leornian.agent_runtime.gateway import DeliveryUnknown
from leornian.agent_runtime.repository import Runs
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.platform.material_models import MaterialModelGateway
from leornian.platform.models import MaterialProbeConfiguration, UserModels
from leornian.shared_kernel.errors import BusinessError


def prepare_material_call(connection, actor, operation_id, models, role, **inputs):
    binding = models.binding(actor, role)
    configuration = models.resolve_material(actor, binding)
    gateway = MaterialModelGateway(configuration)
    request, policy = gateway.request(**inputs)
    public_configuration = asdict(configuration)
    del public_configuration["api_key"]
    Runs(connection).prepare_operation(
        actor.id,
        operation_id,
        gateway.endpoint,
        request,
        policy,
        {
            "operation": "material-" + role + ".v1",
            "model_binding": binding,
            "configuration": public_configuration,
        },
    )
    return binding


def consume_material_call(database, settings, operation_id, session_digest, guard, transport=None):
    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
            session_digest
        )
        guard(connection, actor)
        call = Runs(connection).operation(operation_id)
        binding = call.context_manifest["model_binding"]
        models = UserModels(connection, settings)
        if call.status == "result_recorded":
            # A complete receipt needs current permission, not the old plaintext credential.
            current = models.binding(actor, binding["role"])
            ignored = {"credential_version", "connection_revision"}
            if {k: v for k, v in binding.items() if k not in ignored} != {
                k: v for k, v in current.items() if k not in ignored
            }:
                raise BusinessError("model_unavailable", "Material profile changed.")
            gateway = MaterialModelGateway(
                MaterialProbeConfiguration(**call.context_manifest["configuration"], api_key="")
            )
            return gateway.result(call.response_body, call.request), call
        if call.status in {"unknown", "dispatching"}:
            Runs(connection).record(call.id, unknown=True)
            gateway = None
        elif call.status != "prepared":
            raise BusinessError("provider_rejected", "The recorded request cannot be resent.")
        else:
            configuration = models.resolve_material(actor, binding)
            gateway = MaterialModelGateway(configuration, transport=transport)
    if gateway is None:
        raise BusinessError("external_result_unknown", "The material request is not resent.")
    gateway.check_destination(call.endpoint, call.request)
    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
            session_digest
        )
        guard(connection, actor)
        UserModels(connection, settings).validate_binding(actor, binding)
        if not Runs(connection).dispatch(call.id):
            raise BusinessError("external_result_unknown", "Another worker owns this request.")
    try:
        receipt = gateway.send(call.endpoint, call.request, policy=call.policy_snapshot)
    except DeliveryUnknown:
        receipt = None
    with database.transaction() as connection:
        Runs(connection).record(call.id, receipt, unknown=receipt is None)
    # Save network facts even if the lease, permission or cancellation changed in flight.
    return consume_material_call(
        database, settings, operation_id, session_digest, guard, transport=transport
    )
