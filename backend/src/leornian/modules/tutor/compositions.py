"""Tutor owns prepared public presentations, not question grades or execution."""

import hashlib
import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionCandidate,
    CompositionContentRef,
    CompositionOwnerBinding,
    CompositionPresentation,
    SubmittedCodeReviewBinding,
)
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.modules.tutor.demo_contracts import DemoBinding
from leornian.modules.tutor.demos import DemoReports
from leornian.shared_kernel.errors import BusinessError


class Compositions:
    def __init__(self, connection):
        self.connection = connection

    def get(self, actor, presentation_id):
        row = self.connection.execute(
            "SELECT * FROM tutor.learning_presentations WHERE actor_id=%s AND id=%s",
            (actor.id, presentation_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Composition presentation not found.")
        return row

    @staticmethod
    def validate_preview_controls(definition):
        editable = {
            node.props.state for node in definition.components
            if node.component in {"CodeEditor", "CodeDiff"}
            and (state := definition.states[node.props.state]).type == "code"
            and not state.read_only
        }
        refreshable = {
            node.props.for_component for node in definition.components
            if node.component == "ArtifactAction" and node.props.event == "preview"
        }
        for node in definition.components:
            if (
                node.component == "IsolatedPreview"
                and {node.props.html_state, node.props.css_state} & editable
                and node.id not in refreshable
            ):
                raise BusinessError(
                    "precondition_failed",
                    f"{node.id}: editable HTML/CSS needs an ArtifactAction with "
                    f"event='preview' and for_component='{node.id}'; editing and demo "
                    "report commands do not update the preview.",
                )

    @staticmethod
    def validate_owner_controls(definition, owner_bindings):
        nodes = {node.id: node for node in definition.components}
        actions = {
            (node.props.for_component, node.props.event) for node in definition.components
            if node.component == "ArtifactAction"
        }
        for binding in owner_bindings:
            node = nodes[binding.component_id]
            event = (
                "check_code" if node.component in {"CodeEditor", "CodeDiff"}
                else "submit_review" if node.component == "LineRangeAnswer" else "submit_answer"
            )
            if (node.id, event) not in actions:
                raise BusinessError(
                    "precondition_failed",
                    f"{node.id}: bound practice needs an ArtifactAction with "
                    f"event='{event}' and for_component='{node.id}'; editing, feedback "
                    "and assistance/demo controls do not submit the practice.",
                )
            if (node.id, "cancel") in actions:
                raise BusinessError(
                    "precondition_failed",
                    f"{node.id}: ArtifactAction event='cancel' cancels the whole artifact, "
                    "not this practice or its active Attempt. Remove this owner-targeted "
                    "cancel action; the host provides the exact active-attempt cancellation "
                    "control while this practice is queued or running.",
                )

    def prepare(
        self, actor, conversation_id, run_id, focus, key, definition, manifest, owner_bindings=(),
        review_bindings=(), hint_bindings=(), demo_bindings=(), *, example_workspace=None,
    ):
        body = definition.model_dump(mode="json")
        owners = [binding.model_dump(mode="json") for binding in owner_bindings]
        reviews = [binding.model_dump(mode="json") for binding in review_bindings]
        hints = [binding.model_dump(mode="json") for binding in hint_bindings]
        demos = [binding.model_dump(mode="json") for binding in demo_bindings]
        content = {"definition": body, "owner_bindings": owners} if owners else body
        if example_workspace is not None:
            workspace = example_workspace.model_dump(mode="json")
            manifest = {**manifest, "example_workspace": workspace}
            content = {"definition": body, "example_workspace": workspace}
        if reviews:
            content = {
                "definition": body, "owner_bindings": owners, "review_bindings": reviews,
            }
        if hints:
            content = {**content, "hint_bindings": hints}
        if demos:
            content = {**content, "demo_bindings": demos}
        identity = hashlib.sha256(
            json.dumps(
                content,
                sort_keys=True, separators=(",", ":"),
            ).encode()
        ).hexdigest()
        existing = self.connection.execute(
            "SELECT * FROM tutor.learning_presentations "
            "WHERE actor_id=%s AND prepared_run_id=%s AND command_key=%s",
            (actor.id, run_id, key),
        ).fetchone()
        if existing:
            if (
                existing["conversation_id"] != conversation_id
                or existing["public_identity"] != identity
                or existing["context_manifest"] != manifest
                or existing["owner_bindings"] != owners
                or existing["review_bindings"] != reviews
                or existing["hint_bindings"] != hints
                or existing["demo_bindings"] != demos
            ):
                raise BusinessError("idempotency_conflict", "Composition preparation changed.")
            presentation_id = existing["id"]
        else:
            # Historical definitions and original command receipts keep their interpretation.
            self.validate_preview_controls(definition)
            self.validate_owner_controls(definition, owner_bindings)
            presentation_id = uuid4()
            self.connection.execute(
                "INSERT INTO tutor.learning_presentations"
                "(id,actor_id,conversation_id,prepared_run_id,command_key,"
                "definition,context_manifest,public_identity,owner_bindings,review_bindings,"
                "hint_bindings,demo_bindings) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    presentation_id, actor.id, conversation_id, run_id, key,
                    Jsonb(body), Jsonb(manifest), identity, Jsonb(owners), Jsonb(reviews),
                    Jsonb(hints), Jsonb(demos),
                ),
            )
            self.connection.execute(
                "INSERT INTO tutor.learning_candidates"
                "(id,actor_id,conversation_id,kind,focus,public_identity,presentation_id)"
                " VALUES (%s,%s,%s,'learning_composition',%s,%s,%s)",
                (
                    uuid4(), actor.id, conversation_id,
                    Jsonb(focus.model_dump(mode="json")), identity, presentation_id,
                ),
            )
        candidate = self.connection.execute(
            "SELECT * FROM tutor.learning_candidates WHERE presentation_id=%s",
            (presentation_id,),
        ).fetchone()
        return self.option(actor, candidate)

    def option(self, actor, candidate):
        row = self.get(actor, candidate["presentation_id"])
        definition = LearningCompositionV2.model_validate(row["definition"])
        return CompositionCandidate(
            id=candidate["id"], conversation_id=candidate["conversation_id"],
            focus=TeachingFocus(**candidate["focus"]), title=definition.title,
            content_ref=CompositionContentRef(
                id=row["id"], revision=row["revision"], public_identity=row["public_identity"]
            ),
            presentation=CompositionPresentation(
                definition=definition,
                example_workspace=row["context_manifest"].get("example_workspace"),
            ),
            owner_bindings=[
                CompositionOwnerBinding.model_validate(b) for b in row["owner_bindings"]
            ],
            review_bindings=[
                SubmittedCodeReviewBinding.model_validate(b) for b in row["review_bindings"]
            ],
            demo_bindings=[DemoBinding.model_validate(b) for b in row["demo_bindings"]],
        )

    def delivered_artifact(self, actor, presentation_id):
        return self.connection.execute(
            "SELECT a.* FROM tutor.learning_artifacts a JOIN tutor.learning_candidates c "
            "ON c.id=a.candidate_id WHERE a.actor_id=%s AND c.presentation_id=%s",
            (actor.id, presentation_id),
        ).fetchone()

    def assign_owners(self, actor, artifact):
        row = self.get(actor, artifact["presentation_id"])
        DemoReports(self.connection).assign(artifact["id"], row["demo_bindings"])
        for binding in row["owner_bindings"]:
            self.connection.execute(
                "INSERT INTO tutor.learning_component_bindings"
                "(artifact_id,component_id,source_candidate_id) VALUES(%s,%s,%s)",
                (artifact["id"], binding["component_id"], binding["source"]["id"]),
            )

    def components(self, actor, artifact_id):
        return self.connection.execute(
            "SELECT b.*,c.kind,c.pack_id,c.slot FROM tutor.learning_component_bindings b "
            "JOIN tutor.learning_artifacts a ON a.id=b.artifact_id "
            "JOIN tutor.learning_candidates c ON c.id=b.source_candidate_id "
            "WHERE a.actor_id=%s AND a.id=%s ORDER BY b.component_id",
            (actor.id, artifact_id),
        ).fetchall()

    def assistance_delivered(self, artifact_id):
        self.connection.execute(
            "UPDATE tutor.learning_artifacts SET revision=revision+1 WHERE id=%s",
            (artifact_id,),
        )

    def action_identity(self, artifact_id, component_id, action_id):
        self.connection.execute(
            "UPDATE tutor.learning_component_bindings SET last_action_id=%s "
            "WHERE artifact_id=%s AND component_id=%s",
            (action_id, artifact_id, component_id),
        )

    def owner_result(self, actor, pack_id, slot, kind, result_id, state, *, new_attempt=False):
        field = {
            "choice": "choice_result_id", "python": "python_attempt_id",
            "response": "response_result_id", "program": "program_attempt_id",
        }[kind]
        rows = self.connection.execute(
            "UPDATE tutor.learning_component_bindings b SET state=%s,"
            "last_action_id=CASE WHEN b." + field + "=%s THEN b.last_action_id ELSE NULL END,"
            + field + "=%s FROM tutor.learning_artifacts a,tutor.learning_candidates c "
            "WHERE b.artifact_id=a.id AND b.source_candidate_id=c.id AND a.actor_id=%s "
            "AND c.pack_id=%s AND c.slot=%s AND a.state NOT IN ('cancelled','superseded') "
            "AND (b." + field + " IS NULL OR b." + field + "=%s OR %s) "
            "AND (b.state<>%s OR b." + field + " IS DISTINCT FROM %s) RETURNING b.artifact_id",
            (state, result_id, result_id, actor.id, pack_id, slot, result_id, new_attempt,
             state, result_id),
        ).fetchall()
        result = []
        for row in rows:
            result.append(self.connection.execute(
                "UPDATE tutor.learning_artifacts a SET revision=revision+1,state=CASE "
                "WHEN EXISTS(SELECT 1 FROM tutor.learning_component_bindings b "
                "WHERE b.artifact_id=a.id AND b.state='running') THEN 'running' "
                "WHEN EXISTS(SELECT 1 FROM tutor.learning_component_bindings b "
                "WHERE b.artifact_id=a.id AND b.state='ready') OR "
                "EXISTS(SELECT 1 FROM tutor.demo_observations d "
                "WHERE d.artifact_id=a.id AND d.state<>'completed') "
                "THEN 'ready' ELSE 'completed' END "
                "WHERE a.id=%s RETURNING a.id,a.conversation_id", (row["artifact_id"],),
            ).fetchone())
        return result

    def cancel_components(self, artifact_id):
        self.connection.execute(
            "UPDATE tutor.learning_component_bindings SET state='cancelled' WHERE artifact_id=%s",
            (artifact_id,),
        )

    def accept(self, actor, candidate, run_id):
        row = self.get(actor, candidate["presentation_id"])
        if row["prepared_run_id"] != run_id:
            raise BusinessError("precondition_failed", "Composition belongs to another Run.")
        check = self.connection.execute(
            "SELECT c.review_call_id FROM tutor.delivery_checks c "
            "JOIN tutor.delivery_tasks t ON t.id=c.task_id "
            "WHERE t.run_id=%s AND t.status='accepted' AND c.candidate_call_id=t.candidate_call_id "
            "AND c.verdict='accepted' "
            "ORDER BY c.created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if not check:
            raise BusinessError("precondition_failed", "Composition requires checked delivery.")
        self.connection.execute(
            "UPDATE tutor.learning_presentations SET quality_call_id=%s,accepted_at=now() "
            "WHERE id=%s AND quality_call_id IS NULL",
            (check["review_call_id"], row["id"]),
        )
