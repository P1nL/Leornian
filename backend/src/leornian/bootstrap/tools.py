"""Authorized tool dispatch. No model, Runner or HTTP IO inside these DB commands."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError

from leornian.agent_runtime.tools import REGISTRY, ToolProblem
from leornian.bootstrap.artifacts import ArtifactWorkflow
from leornian.modules.assessment.gates import Gates
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.artifacts import Artifacts
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError


class ToolRouter:
    def __init__(self, database, row, focus, context):
        self.database = database
        self.row = row
        self.focus = focus
        self.context = context

    def execute(self, connection, call):
        start = time.monotonic()
        try:
            args = REGISTRY[call.name].validate(call.arguments)
        except ValidationError as error:
            result = {
                "status": "rejected",
                "code": "invalid_arguments",
                "fields": [
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                    for e in error.errors(include_input=False, include_url=False)
                ],
                "next_action": "Correct the arguments using this tool's declared schema.",
            }
        else:
            try:
                with connection.transaction():
                    result = self._dispatch(connection, call.name, args)
            except BusinessError as error:
                status = (
                    "conflict"
                    if error.code in {"stale_version", "idempotency_conflict"}
                    else "waiting_dependency"
                    if error.code == "precondition_failed"
                    else "rejected"
                )
                result = {
                    "status": status,
                    "code": error.code,
                    "message": error.message,
                    "next_action": "Reread the current permitted state; do not repeat unchanged "
                    "arguments, expand scope or silently rebase.",
                }
        result_contract = (
            ToolProblem
            if result.get("status") in {"rejected", "conflict", "waiting_dependency", "unknown"}
            else REGISTRY[call.name].result
        )
        if result_contract:
            result = result_contract.model_validate_json(
                json.dumps(result), strict=True
            ).model_dump(mode="json", exclude_none=True)
            # Continuation cursors are explicit null at the end, never silently absent.
            for key in ("next_offset", "next_before"):
                if key in result_contract.model_fields and key not in result:
                    result[key] = None
        return result, int((time.monotonic() - start) * 1000)

    def _dispatch(self, connection, name, args):
        identity = Identity(PgIdentityStore(connection))
        actor = identity.authenticate_digest(self.row["session_digest"])
        if actor.id != self.row["actor_id"]:
            raise BusinessError("unauthorized", "Tool owner changed.")
        Gates(connection).require_no_exam(actor)
        conversation = Tutor(PgTutorStore(connection)).get(actor, self.row["scope_id"])
        store = Artifacts(connection)
        if name == "learning_get_context":
            return self.context()
        if name == "list_artifacts":
            items = store.list(actor, conversation.goal_id, self.focus, args.before, args.limit)
            return {
                "status": "completed",
                "items": [i.model_dump(mode="json") for i in items],
                "next_before": str(items[-1].id) if len(items) == args.limit else None,
            }
        if name == "read_artifact":
            head = store.head(actor, args.artifact_id)
            if head["goal_id"] != conversation.goal_id or head["focus"] != self.focus:
                raise BusinessError("not_found", "Artifact is outside this teaching binding.")
            artifact = store.get(actor, args.artifact_id, args.revision)
            sections = artifact.document.sections
            if args.offset >= len(sections):
                raise BusinessError("precondition_failed", "Read offset is outside the artifact.")
            end = min(args.offset + args.limit, len(sections))
            return {
                "status": "completed",
                "artifact_id": str(artifact.id),
                "revision": artifact.revision,
                "title": artifact.title,
                "sections": [s.model_dump(mode="json") for s in sections[args.offset : end]],
                "section_count": len(sections),
                "offset": args.offset,
                "next_offset": end if end < len(sections) else None,
                "code_is_inert": True,
            }
        if name not in {"request_teaching_artifact", "request_artifact_revision"}:
            raise RuntimeError("Registered tool has no business handler: " + name)
        revision = name == "request_artifact_revision"
        job = store.request(
            actor,
            conversation,
            self.focus,
            "turn:" + str(self.row["input_ref"]),
            args.command_key,
            args.instruction,
            args.artifact_id if revision else None,
            args.expected_revision if revision else 0,
            parent_run_id=self.row["id"],
            session_digest=self.row["session_digest"],
        )
        ArtifactWorkflow.event(connection, actor.id, job.artifact_id, job.id)
        return {
            "status": "accepted",
            "job_id": str(job.id),
            "artifact_id": str(job.artifact_id),
            "expected_revision": job.expected_revision,
            "message": "Queued for independent checked delivery after this turn; not delivered.",
        }

    def batch(self, connection, calls):
        # Only independent immutable/page reads run on separate read-only connections.
        # Mixed writes, current-context refresh and snapshot-sensitive operations stay serial.
        if len(calls) > 1 and all(REGISTRY[c.name].parallel_safe for c in calls):

            def read(call):
                with self.database.transaction(snapshot=True) as read_connection:
                    return self.execute(read_connection, call)

            unique = {}
            keys = [json.dumps([c.name, c.arguments], sort_keys=True) for c in calls]
            with ThreadPoolExecutor(max_workers=min(4, len(calls))) as executor:
                for key, call in zip(keys, calls, strict=True):
                    if key not in unique:
                        unique[key] = executor.submit(read, call)
                return [unique[key].result() for key in keys]
        return [self.execute(connection, call) for call in calls]
