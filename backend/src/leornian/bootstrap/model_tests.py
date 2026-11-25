import json
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.agent_runtime.contracts import RoleSpec
from leornian.agent_runtime.gateway import (
    ChatCompletionsGateway,
    DeliveryUnknown,
    ModelProtocolError,
    parse_decision,
)
from leornian.agent_runtime.repository import Runs
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.platform.model_contracts import ModelConnectionTest
from leornian.platform.model_probes import MaterialProbeGateway
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError

TEST_COLUMNS = "id,connection_id,profile_id,status,result,error_code,created_at,completed_at"


def public_usage(usage):
    if not isinstance(usage, dict):
        return None
    counters = {
        key: value
        for key, value in usage.items()
        if key
        in {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"}
        and type(value) is int
        and value >= 0
    }
    return counters or None


class ModelTestWorkflow:
    """One explicit, billable protocol probe using the existing external-call ledger."""

    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    @staticmethod
    def gateway(models, actor, binding, transport=None):
        if binding.get("purpose") == "connection-probe.v1":
            resolved = models.resolve_probe(actor, binding)
            if binding["operation"] == "chat":
                return ChatCompletionsGateway(resolved, transport=transport)
            return MaterialProbeGateway(resolved, transport=transport)
        if binding["operation"] == "chat":
            return ChatCompletionsGateway(
                models.resolve_chat(actor, binding, require_private=False),
                transport=transport,
            )
        return MaterialProbeGateway(
            models.resolve_material_probe(actor, binding),
            transport=transport,
        )

    @staticmethod
    def validate_binding(models, actor, binding):
        if binding.get("purpose") == "connection-probe.v1":
            models.validate_probe_binding(actor, binding)
        else:
            models.validate_binding(actor, binding, require_private=False)

    def get(self, token, test_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = connection.execute(
                "SELECT " + TEST_COLUMNS + " FROM platform.model_connection_tests "
                "WHERE id=%s AND actor_id=%s",
                (test_id, actor.id),
            ).fetchone()
            if not row:
                raise BusinessError("not_found", "Model connection test not found.")
            return ModelConnectionTest(**row)

    def list(self, token):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return [
                ModelConnectionTest(**row)
                for row in connection.execute(
                    "SELECT " + TEST_COLUMNS + " FROM platform.model_connection_tests "
                    "WHERE actor_id=%s ORDER BY created_at DESC,id DESC LIMIT 100",
                    (actor.id,),
                ).fetchall()
            ]

    def submit(self, token, connection_id, key, data):
        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate(token)
            models = UserModels(connection, self.settings)
            models.connection_view(actor, connection_id)
            previous = connection.execute(
                "SELECT * FROM platform.model_connection_tests "
                "WHERE actor_id=%s AND command_key=%s",
                (actor.id, key),
            ).fetchone()
            request = data.model_dump(mode="json")
            if previous:
                if previous["connection_id"] != connection_id or previous["request"] != request:
                    raise BusinessError("idempotency_conflict", "Connection test key changed.")
                return ModelConnectionTest(**{k: previous[k] for k in TEST_COLUMNS.split(",")})
            profile = models.profile(actor, data.profile_id)
            view = models.connection_view(actor, connection_id)
            if view.revision != data.expected_connection_revision:
                raise BusinessError("stale_version", "Connection revision changed.")
            if profile.connection_id != connection_id:
                raise BusinessError("precondition_failed", "Profile belongs to another connection.")
            binding = models.probe_binding(actor, profile.id)
            gateway = self.gateway(models, actor, binding)
            if profile.operation == "chat":
                role = RoleSpec(
                    messages=[
                        {
                            "role": "user",
                            "content": 'Return exactly the JSON object {"ok": true}.',
                        }
                    ],
                    require_initial_tool=False,
                )
                policy = gateway.policy(role)
                wire = gateway.request(
                    role.messages,
                    require_tool=False,
                    allowed_tools=(),
                    json_output=True,
                    policy=policy,
                )
            else:
                wire, policy = gateway.probe()
            test_id = uuid4()
            connection.execute(
                "INSERT INTO platform.model_connection_tests"
                "(id,actor_id,connection_id,profile_id,session_digest,command_key,request) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    test_id,
                    actor.id,
                    connection_id,
                    profile.id,
                    identity.digest(token),
                    key,
                    Jsonb(request),
                ),
            )
            Runs(connection).prepare_operation(
                actor.id,
                test_id,
                gateway.endpoint,
                wire,
                policy,
                {
                    "model_binding": binding,
                    "operation": "connection-" + profile.operation + "-test.v1",
                },
            )
            row = connection.execute(
                "SELECT " + TEST_COLUMNS + " FROM platform.model_connection_tests WHERE id=%s",
                (test_id,),
            ).fetchone()
            return ModelConnectionTest(**row)

    def execute(self, test_id, transport=None):
        # Resolution and the actual network operation use no long business transaction.
        try:
            with self.database.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM platform.model_connection_tests WHERE id=%s FOR UPDATE",
                    (test_id,),
                ).fetchone()
                if not row or row["status"] != "queued":
                    return
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True)
                ).authenticate_digest(row["session_digest"])
                call = Runs(connection).operation(test_id)
                models = UserModels(connection, self.settings)
                gateway = self.gateway(
                    models,
                    actor,
                    call.context_manifest["model_binding"],
                    transport=transport,
                )
            gateway.check_destination(call.endpoint, call.request)
            with self.database.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM platform.model_connection_tests WHERE id=%s FOR UPDATE",
                    (test_id,),
                ).fetchone()
                if row["status"] != "queued":
                    return
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True)
                ).authenticate_digest(row["session_digest"])
                self.validate_binding(
                    UserModels(connection, self.settings),
                    actor,
                    call.context_manifest["model_binding"],
                )
                if not Runs(connection).dispatch(call.id):
                    return
                connection.execute(
                    "UPDATE platform.model_connection_tests SET status='dispatching',"
                    "deadline_at=now()+make_interval(secs=>%s) WHERE id=%s",
                    (call.policy_snapshot["timeout_seconds"], test_id),
                )
        except (BusinessError, ModelProtocolError) as error:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE platform.model_connection_tests SET status='failed',error_code=%s,"
                    "completed_at=now() WHERE id=%s AND status='queued'",
                    (error.code, test_id),
                )
                call = Runs(connection).operation(test_id)
                if call:
                    connection.execute(
                        "UPDATE runtime.external_calls SET status='not_sent' "
                        "WHERE id=%s AND status='prepared'",
                        (call.id,),
                    )
            return
        try:
            receipt = gateway.send(call.endpoint, call.request, policy=call.policy_snapshot)
        except DeliveryUnknown:
            receipt = None
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM platform.model_connection_tests WHERE id=%s FOR UPDATE",
                (test_id,),
            ).fetchone()
            calls = Runs(connection)
            calls.record(call.id, receipt, unknown=receipt is None)
            recorded = calls.operation(test_id)
            status, code, result = "unknown", "external_result_unknown", None
            late = row["status"] == "unknown" or row["deadline_at"] < datetime.now(UTC)
            if recorded.status == "failed_known":
                status, code = "failed", "provider_rejected"
            elif recorded.status == "result_recorded" and not late:
                try:
                    actor = Identity(
                        PgIdentityStore(connection, lock_session=True)
                    ).authenticate_digest(
                        row["session_digest"]
                    )
                    self.validate_binding(
                        UserModels(connection, self.settings),
                        actor,
                        call.context_manifest["model_binding"],
                    )
                    operation = call.context_manifest["model_binding"]["operation"]
                    if operation == "chat":
                        response = parse_decision(recorded.response_body)
                        payload = json.loads(response.content or "null")
                        if (
                            response.tools
                            or not isinstance(payload, dict)
                            or set(payload) != {"ok"}
                            or payload["ok"] is not True
                        ):
                            raise ValueError("invalid_probe_output")
                        details = {
                            "protocol": "chat-json-roundtrip.v1",
                            "json_response": "verified",
                            "tools": "not_tested",
                            "material_operations": "not_tested",
                        }
                    else:
                        details = {
                            **gateway.validate(recorded.response_body),
                            "protocol": "material-" + operation + "-roundtrip.v1",
                            "tools": "not_applicable",
                            "material_quality": "not_tested",
                        }
                    status, code = "succeeded", None
                    result = {
                        **details,
                        "model_requested": call.request["model"],
                        "region": call.context_manifest["model_binding"]["region"],
                    }
                    calls.applied(call.id)
                except BusinessError:
                    status, code = "cancelled", "configuration_or_session_changed"
                except (ValueError, TypeError, ModelProtocolError):
                    status, code = "failed", "invalid_probe_response"
            if result is not None:
                usage = connection.execute(
                    "SELECT usage,dispatched_at,recorded_at FROM runtime.external_calls "
                    "WHERE id=%s",
                    (call.id,),
                ).fetchone()
                result["usage"] = public_usage(usage["usage"])
                result["elapsed_seconds"] = (
                    usage["recorded_at"] - usage["dispatched_at"]
                ).total_seconds()
            connection.execute(
                "UPDATE platform.model_connection_tests SET status=%s,error_code=%s,result=%s,"
                "completed_at=now() WHERE id=%s",
                (status, code, Jsonb(result), test_id),
            )

    def expire_unknowns(self):
        with self.database.transaction() as connection:
            rows = connection.execute(
                "UPDATE platform.model_connection_tests SET status='unknown',"
                "error_code='external_result_unknown',completed_at=now() "
                "WHERE status='dispatching' AND deadline_at<now() RETURNING id",
            ).fetchall()
            for row in rows:
                call = Runs(connection).operation(row["id"])
                Runs(connection).record(call.id, unknown=True)
            return len(rows)
