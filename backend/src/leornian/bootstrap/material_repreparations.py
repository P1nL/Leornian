import hashlib

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.assessment.gates import Gates
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.material_contracts import MaterialSpan
from leornian.modules.knowledge.materials import Materials
from leornian.modules.learning.contracts import LessonRequestInput
from leornian.modules.learning.lessons import Lessons
from leornian.modules.learning.material_contracts import MaterialBindingInput, material_content_key
from leornian.modules.learning.material_repreparations import (
    TERMINAL,
    LearningMaterialRepreparations,
)
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.contracts import PlanningInput
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.teaching_sessions import TeachingSessions
from leornian.shared_kernel.errors import BusinessError


def replace_accepted_ranges(blocks, old_refs, successor_refs):
    """Retain unaffected exact ranges when an accepted update covers only part of a block."""
    result = []
    for block in blocks:
        ref = block.ref
        spans = [(ref.span.start, ref.span.end)]
        for old in old_refs:
            if (
                old.document_id != ref.document_id
                or old.document_revision != ref.document_revision
                or old.block_id != ref.block_id
            ):
                continue
            spans = [
                piece for start, end in spans
                for piece in (
                    (start, min(end, old.span.start)), (max(start, old.span.end), end),
                ) if piece[0] < piece[1]
            ]
        for start, end in spans:
            text = block.text[start - ref.span.start:end - ref.span.start]
            result.append(ref.model_copy(update={
                "span": MaterialSpan(start=start, end=end),
                "content_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "selection_id": None,
            }))
    result.extend(ref.model_copy(update={"selection_id": None}) for ref in successor_refs)
    return list({material_content_key(ref): ref for ref in result}.values())


class MaterialRepreparationWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def list(self, token, decision_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return LearningMaterialRepreparations(connection).list(actor, decision_id)

    def _derive_planning_binding(self, connection, actor, row, decision):
        jobs = LearningMaterialRepreparations(connection)
        bindings = MaterialBindings(connection)
        old = bindings.get(actor, decision["binding_id"], decision["binding_revision"])
        successor = bindings.get(
            actor, decision["successor_binding_id"], decision["successor_binding_revision"],
        )
        if bindings.get(actor, successor.id).revision != successor.revision:
            raise BusinessError("stale_version", "The accepted material successor changed.")
        materials = Materials(connection)
        current = bindings.for_scope(actor, row["goal_id"], "planning")
        current_refs = [ref for binding in current for ref in binding.refs]
        old_keys = {material_content_key(ref) for ref in old.refs}
        new_keys = {material_content_key(ref) for ref in successor.refs}
        changed_docs = {
            ref.document_id for ref in old.refs + successor.refs
            if material_content_key(ref) not in old_keys & new_keys
        }
        old_refs = [ref for ref in old.refs if ref.document_id in changed_docs]
        new_refs = [ref for ref in successor.refs if ref.document_id in changed_docs]
        blocks = materials.read_refs(actor, row["goal_id"], "planning", current_refs)
        refs = replace_accepted_ranges(blocks, old_refs, new_refs)
        materials.read_refs(actor, row["goal_id"], "planning", refs)
        if {material_content_key(ref) for ref in refs} == {
            material_content_key(ref) for ref in current_refs
        }:
            return
        previous_revision = current[0].revision if current else 0
        binding = bindings.bind(
            actor, row["command_key"] + ":planning-materials",
            MaterialBindingInput(
                goal_id=row["goal_id"], purpose="planning", refs=refs,
                expected_binding_revision=previous_revision,
                expected_completion_at=successor.expected_completion_at,
            ),
        )
        jobs.derived_binding(row["id"], binding, previous_revision)

    @staticmethod
    def _observe_in(connection, actor, row):
        jobs = LearningMaterialRepreparations(connection)
        task = (
            Deliveries(connection).row(actor, row["delivery_task_id"])
            if row["delivery_task_id"] else None
        )
        run_id = task["run_id"] if task else row["run_id"]
        run = Runs(connection).get(actor.id, run_id)
        if run.status == "blocked_unknown" or task and task["status"] == "blocked_unknown":
            jobs.state(row["id"], "waiting_receipt", "original_receipt_unknown")
            return
        if run.status == "cancelled" or task and task["status"] in {"cancelled", "superseded"}:
            jobs.state(row["id"], "cancelled", "original_task_cancelled")
            return
        if run.status == "succeeded" and (not task or task["status"] == "accepted"):
            if row["kind"] == "plan":
                revision = Plans(connection).produced_revision(actor, row["plan_id"], run_id)
                if revision:
                    jobs.state(row["id"], "ready", plan_revision=revision)
                    return
            else:
                lesson = Lessons(connection).for_run(actor, run_id)
                if lesson:
                    jobs.state(
                        row["id"], "ready", plan_revision=lesson.plan_revision,
                        lesson_id=lesson.id,
                    )
                    return
        jobs.state(
            row["id"],
            "waiting_dependency" if run.status == "failed" or task and task["status"].startswith(
                "waiting_"
            ) else "running",
            run.error_code or (task["status"] if task else None),
        )

    def _advance_in(self, connection, actor, row):
        jobs = LearningMaterialRepreparations(connection)
        if row["state"] in TERMINAL:
            return
        if row["run_id"]:
            self._observe_in(connection, actor, row)
            return
        decision = jobs.decision(actor, row["decision_id"])
        plan = Plans(connection).get(actor, row["plan_id"], lock=True)
        target_revision = None
        if row["kind"] == "plan":
            if plan.latest.revision != row["source_revision"]:
                jobs.state(row["id"], "superseded", "a_newer_plan_already_exists")
                return
        else:
            parent = jobs.parent(actor, row)
            if not parent or parent["state"] in {"superseded", "cancelled"}:
                jobs.state(row["id"], "superseded", "route_preparation_no_longer_current")
                return
            target_revision = parent["output_plan_revision"]
            if parent["state"] != "ready" or target_revision is None:
                jobs.state(row["id"], "waiting_dependency", "route_preparation_pending")
                return
            if not plan.active or plan.active.revision != target_revision:
                if plan.latest.revision > target_revision:
                    jobs.state(row["id"], "superseded", "a_newer_route_requires_its_own_lessons")
                else:
                    jobs.state(
                        row["id"], "waiting_confirmation", "confirm_the_exact_successor_route",
                    )
                return
            if row["node_key"] not in {node.key for node in plan.active.document.nodes}:
                jobs.state(row["id"], "superseded", "node_removed_from_confirmed_route")
                return
        tutor = Tutor(PgTutorStore(connection))
        conversation = tutor.conversation(actor, row["goal_id"])
        session = TeachingSessions(connection).get(conversation.id)
        if (
            Runs(connection).active(conversation.id) or Gates(connection).active(actor)
            or session and session.active_branch_id
        ):
            jobs.state(row["id"], "waiting_priority", "foreground_or_exam_has_priority")
            return
        workflow = TutorWorkflow(self.database, self.settings)
        if row["kind"] == "plan":
            self._derive_planning_binding(connection, actor, row, decision)
            data = PlanningInput(
                expected_revision=row["source_revision"],
                text=(
                    "Reprepare the current learning route using the explicitly accepted material "
                    "update. Keep stable node keys for unchanged objectives. Explain material "
                    "changes and retain unaffected goals. Save an unconfirmed successor; do not "
                    "claim completion or alter historical attempts or evidence."
                ),
            )
            accepted = workflow._submit_in(
                connection, actor, row["session_digest"], conversation.id, row["command_key"],
                data, "planning", data.expected_revision,
            )
        else:
            data = LessonRequestInput(
                expected_plan_revision=target_revision, node_key=row["node_key"],
                instruction=(
                    "Reprepare this lesson from the explicitly confirmed successor route and "
                    "its exact accepted material references. Preserve the old lesson as history. "
                    "Do not execute examples, answer assessments or change learning evidence."
                ),
            )
            accepted = workflow._submit_lesson_in(
                connection, actor, row["session_digest"], row["plan_id"],
                row["command_key"], data,
            )
        jobs.attach(row["id"], data, accepted)

    def reconcile_once(self, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            candidates = LearningMaterialRepreparations(connection).due(limit)
        changed = 0
        for candidate in candidates:
            with self.database.transaction() as connection:
                jobs = LearningMaterialRepreparations(connection)
                try:
                    actor = Identity(
                        PgIdentityStore(connection, serialize_actor=True),
                    ).authenticate_digest(candidate["session_digest"])
                    if actor.id != candidate["actor_id"]:
                        raise BusinessError("unauthorized", "Material preparation owner changed.")
                    row = jobs.row(actor, candidate["id"], lock=True)
                    with connection.transaction():
                        self._advance_in(connection, actor, row)
                except BusinessError as error:
                    jobs.state(
                        candidate["id"],
                        "cancelled" if error.code == "unauthorized" else "waiting_dependency",
                        error.code,
                    )
                changed += 1
        return changed
