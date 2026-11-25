import json
from uuid import UUID

from leornian.agent_runtime.contracts import (
    Decision,
    Lease,
    Receipt,
    RoleSpec,
    Run,
    StoredCall,
    TurnAccepted,
)
from leornian.agent_runtime.gateway import (
    ChatCompletionsGateway,
    ModelProtocolError,
    validate_tools,
)
from leornian.agent_runtime.repository import Runs
from leornian.agent_runtime.tools import (
    ASSISTED_COMPOSITION_TOOLS,
    CODE_REVIEW_COMPLETION_TOOLS,
    CODE_REVIEW_COMPOSITION_TOOLS,
    COMPOSITION_TOOLS,
    DEMO_COMPOSITION_TOOLS,
    HINT_COMPOSITION_TOOLS,
    NODE_WEB_TOOL,
    PRACTICE_COMPOSITION_TOOLS,
    PRACTICE_SUPPLY_TOOLS,
    PROGRAM_COMPOSITION_TOOLS,
    REGISTRY,
    RESPONSE_COMPOSITION_TOOLS,
    TEACHING_TOOLS,
    TEMPLATE_TOOLS,
    allowed,
)
from leornian.bootstrap.artifacts import ArtifactWorkflow
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.evaluation import EvaluationWorkflow
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.material_consumers import (
    manifest_citations,
    prepare_consumer_in,
    read_citations_in,
)
from leornian.bootstrap.model_configuration import configuration_scope, require_model_admission
from leornian.bootstrap.node_web_lookup import (
    available_tools,
    begin_lookup,
    finish_lookup,
    public_scope,
)
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.bootstrap.teaching_context import TeachingContext
from leornian.bootstrap.teaching_delivery import TeachingDelivery
from leornian.bootstrap.tools import ToolRouter
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.bootstrap.tutor_activity import TutorActivity
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.application import Assessment
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.transfers import Transfers
from leornian.modules.execution.example_contracts import example_capability
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.catalog import published_item
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.learning.application import Learning
from leornian.modules.learning.contracts import (
    GeneratedLesson,
    LearningPlan,
    LessonDocument,
    LessonRequestInput,
    PlanDocument,
    PlanRevision,
)
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.journey import Journey
from leornian.modules.learning.journey_contracts import Lesson
from leornian.modules.learning.lessons import Lessons
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.artifacts import Artifacts
from leornian.modules.tutor.contracts import Conversation, PlanningInput, TeachingFocus, TurnInput
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.evaluations import Evaluations
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.platform.config import Settings
from leornian.platform.database import Database
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


class TutorWorkflow:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    @staticmethod
    def _event(connection, row: dict, status: str, code: str | None = None) -> None:
        if row["policy_version"] == "material_check.v1":
            return
        turn = PgTutorStore(connection).get_turn(row["scope_id"], row["input_ref"]) if (
            status == "succeeded" and row["policy_version"] in {"tutor.v1", "planner.v1"}
        ) else None
        Events(connection).append(
            row["actor_id"],
            "tutor." + status,
            row["id"],
            EventPayload(
                run_id=row["id"],
                conversation_id=row["scope_id"],
                turn_id=row["input_ref"],
                error_code=code,
                reply_text=turn.assistant_text if turn else None,
            ),
        )

    @classmethod
    def _finish(cls, connection, row: dict, status: str, code: str | None = None) -> None:
        delivery = Deliveries(connection).for_run(row["id"])
        if delivery:
            if status == "cancelled":
                Deliveries(connection).state(delivery["id"], "cancelled")
            elif status == "blocked_unknown":
                Deliveries(connection).state(delivery["id"], "blocked_unknown")
            elif status == "failed" and TeachingDelivery.failure(connection, row, code):
                TutorActivity.finish(connection, row, "failed")
                cls._event(connection, row, "queued", code)
                return
        if status == "failed" and delivery:
            if Deliveries(connection).for_run(row["id"])["status"] == "blocked_protocol":
                code = "delivery_protocol_stalled"
        if status == "cancelled":
            Runs(connection).mark_unknown(row["id"])
        Runs(connection).finish(row["id"], status, code)
        TutorActivity.finish(connection, row, status, code)
        artifact_job = Artifacts(connection).for_run(row["id"])
        if artifact_job and status in {"cancelled", "failed"}:
            task_status = Deliveries(connection).for_run(row["id"])["status"]
            if status == "cancelled" or task_status == "superseded":
                connection.execute(
                    "UPDATE tutor.artifact_requests SET status=%s WHERE id=%s",
                    ("cancelled" if status == "cancelled" else "superseded", artifact_job["id"]),
                )
            ArtifactWorkflow.event(
                connection, row["actor_id"], artifact_job["artifact_id"], artifact_job["id"]
            )
        if status in {"failed", "cancelled"} and row["policy_version"].startswith("item_"):
            packs = Packs(connection)
            stage = packs.stage(row["id"])
            if stage:
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                pack = packs.row(actor, stage["pack_id"])
                if pack["status"] not in {"published", "cancelled"}:
                    packs.status(stage["pack_id"], status)
                ItemSupply.event(connection, row["actor_id"], stage["pack_id"])
        if status in {"failed", "cancelled"} and row["policy_version"] == "gate_relation.v1":
            gates = Gates(connection)
            gates.block_run(row["id"], code, cancelled=status == "cancelled")
            ConceptGate.event(connection, row["actor_id"], gates.for_run(row["id"]))
        if status in {"failed", "cancelled"} and row["policy_version"] == "transfer_relation.v1":
            transfers = Transfers(connection)
            transfers.block_run(row["id"], code, cancelled=status == "cancelled")
            TransferWorkflow.event(connection, row["actor_id"], transfers.for_run(row["id"]))
        if row["policy_version"] == "material_check.v1" and status in {
            "failed", "cancelled", "blocked_unknown",
        }:
            from leornian.bootstrap.material_goal_coverage import MaterialGoalCoverageWorkflow

            MaterialGoalCoverageWorkflow.block_run(
                connection, row["id"], code, cancelled=status == "cancelled",
            )
        cls._event(connection, row, status, code)

    def _current(self, connection, lease: Lease) -> dict | None:
        row = Runs(connection).lock(lease.run_id)
        if (
            not row
            or row["status"] != "running"
            or row["lease_token"] != lease.token
            or not row["lease_valid"]
        ):
            return None
        if row["cancel_requested"]:
            self._finish(connection, row, "cancelled")
            return None
        delivery = Deliveries(connection).for_run(row["id"])
        if delivery and delivery["cancel_requested"]:
            self._finish(connection, row, "cancelled")
            return None
        try:
            identity = Identity(PgIdentityStore(connection, lock_session=True))
            actor = identity.authenticate_digest(row["session_digest"])
            if actor.id != row["actor_id"]:
                raise BusinessError("unauthorized", "Run owner changed.")
        except BusinessError:
            self._finish(connection, row, "failed", "unauthorized")
            return None
        if row["context_refs"]:
            conversation = Tutor(PgTutorStore(connection)).get(actor, row["scope_id"])
            try:
                Knowledge(connection).current(
                    actor,
                    conversation.goal_id,
                    [SourceRef(**ref) for ref in row["context_refs"]],
                )
            except BusinessError:
                changed = delivery and any(
                    Knowledge(connection).get(actor, UUID(ref["source_id"])).revision
                    != ref["revision"]
                    for ref in row["context_refs"]
                )
                self._finish(
                    connection, row, "failed", "stale_version" if changed else "source_not_current"
                )
                return None
        if row["policy_version"] == "material_check.v1":
            from leornian.bootstrap.material_goal_coverage import MaterialGoalCoverageWorkflow

            try:
                MaterialGoalCoverageWorkflow.current(connection, actor, row["input_ref"])
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        if row["policy_version"] == "planner.v1":
            tutor = Tutor(PgTutorStore(connection))
            conversation = tutor.get(actor, row["scope_id"])
            turn = tutor.get_turn(conversation.id, row["input_ref"])
            try:
                Plans(connection).require_base(actor, conversation.goal_id, turn.plan_base_revision)
            except BusinessError:
                self._finish(connection, row, "failed", "stale_version")
                return None
        if row["policy_version"] == "lesson.v1":
            tutor = Tutor(PgTutorStore(connection))
            turn = tutor.get_turn(row["scope_id"], row["input_ref"])
            try:
                request = Lessons(connection).get_request(actor, turn.lesson_request_id)
                Lessons(connection).current(actor, request, lock=True)
                if not delivery:
                    from leornian.bootstrap.teaching_memory import TeachingMemory

                    previous_call = Runs(connection).latest(row["id"])
                    if previous_call:
                        conversation = tutor.get(actor, row["scope_id"])
                        TeachingMemory.require_current_in(
                            connection, actor, conversation.goal_id,
                            previous_call.context_manifest.get("learning_memory", {}),
                        )
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        if row["policy_version"].startswith("item_"):
            try:
                stage = Packs(connection).stage(row["id"])
                pack = Packs(connection).row(actor, stage["pack_id"])
                SupplyTasks(connection).require_current(actor, pack["id"])
                ItemSupply.require_stage_current(pack, stage)
                ItemSupply.current(connection, actor, pack)
            except BusinessError as error:
                self._finish(
                    connection,
                    row,
                    "cancelled" if error.code == "supply_cancelled" else "failed",
                    error.code,
                )
                return None
        if row["policy_version"] == "gate_relation.v1":
            try:
                ConceptGate.current(connection, actor, Gates(connection).for_run(row["id"]))
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        if row["policy_version"] == "transfer_relation.v1":
            try:
                TransferWorkflow.current(
                    connection, actor, Transfers(connection).for_run(row["id"])
                )
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        if row["policy_version"] == "evaluation.v1":
            try:
                EvaluationWorkflow.current(
                    connection, actor, Evaluations(connection).for_run(actor, row["id"])
                )
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        if row["policy_version"] == "artifact.v1":
            try:
                Artifacts(connection).current(actor, Artifacts(connection).for_run(row["id"]))
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        if delivery:
            try:
                from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
                from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
                from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow

                TeachingSessionWorkflow.context_in(
                    connection, actor, row["input_ref"],
                    delivery["context_manifest"].get("teaching_session"),
                    node_turn=delivery["context_manifest"].get("node_turn_contract") == 1,
                )
                TeachingContinuationWorkflow.context_in(
                    connection, actor, row["input_ref"],
                    delivery["context_manifest"].get("teaching_intent"),
                )

                LearningArtifactWorkflow.context_in(
                    connection, actor, row["scope_id"], row["input_ref"]
                )
                Gates(connection).require_no_exam(actor)
                if delivery["context_manifest"].get("route_discussion") == 1:
                    planning_turns = [
                        turn for turn in PgTutorStore(connection).turns(row["scope_id"])
                        if turn.purpose == "planning"
                    ]
                    if planning_turns and planning_turns[-1].id != row["input_ref"]:
                        raise BusinessError(
                            "stale_version", "A newer route request superseded this one.",
                        )
                frozen_focus = TeachingFocus(**delivery["focus"])
                if delivery["context_manifest"].get("lesson_ids"):
                    frozen_focus = frozen_focus.model_copy(
                        update={"lesson_id": UUID(delivery["context_manifest"]["lesson_ids"][0])}
                    )
                memory_turn = Tutor(PgTutorStore(connection)).get_turn(
                    row["scope_id"], row["input_ref"],
                )
                memory_conversation = Tutor(PgTutorStore(connection)).get(actor, row["scope_id"])
                _, current_manifest = TeachingContext.build(
                    connection,
                    actor,
                    memory_conversation,
                    frozen_focus,
                    material_purpose={"planning": "planning", "lesson": "lesson"}.get(
                        delivery["kind"], "teaching"
                    ),
                    material_demand=self._material_demand(
                        connection, actor, row["input_ref"], delivery["kind"], freeze=True,
                    ),
                    session_digest=row["session_digest"],
                    allow_pending_materials=(
                        delivery["context_manifest"].get("route_discussion") == 1
                        and (delivery["phase"] == "review" or not
                             delivery["context_manifest"].get("awaiting_route_materials"))
                    ),
                    teaching_branch_id=memory_turn.teaching_branch_id,
                    memory_before_turn_id=memory_turn.id,
                )
                if delivery["author_messages"] and (
                    current_manifest["plan_binding"]
                    != delivery["context_manifest"].get("plan_binding")
                ):
                    raise BusinessError("stale_version", "Delivery plan binding changed.")
                if delivery["author_messages"] and not (
                    delivery["context_manifest"].get("route_discussion") == 1
                    and delivery["context_manifest"].get("material_preparation")
                ) and (
                    [{k: v for k, v in b.items() if k != "purpose"}
                     for b in current_manifest.get("material_bindings", [])]
                    != [{k: v for k, v in b.items() if k != "purpose"}
                        for b in delivery["context_manifest"].get("material_bindings", [])]
                ):
                    raise BusinessError("stale_version", "Delivery material binding changed.")
                frozen_memory = delivery["context_manifest"].get("learning_memory")
                if delivery["author_messages"] and frozen_memory:
                    from leornian.bootstrap.teaching_memory import TeachingMemory

                    TeachingMemory.require_current_in(
                        connection, actor, memory_conversation.goal_id, frozen_memory,
                    )
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        return row

    @staticmethod
    def _material_demand(connection, actor, turn_id, purpose, *, freeze=False):
        from leornian.bootstrap.material_consumers import attempt_material_scope_in
        from leornian.modules.knowledge.intake import MaterialIntake

        intake = MaterialIntake(connection)
        linked = connection.execute(
            "SELECT material_demand_id,context_focus FROM tutor.turns WHERE id=%s", (turn_id,),
        ).fetchone()
        demand = intake.demand(actor, linked["material_demand_id"]) if (
            linked and linked["material_demand_id"]
        ) else (
            intake.consumer_demand(actor, f"tutor-turn:{turn_id}:{purpose}:semantic-goal.v1")
            or intake.consumer_demand(actor, f"tutor-turn:{turn_id}:{purpose}")
        )
        if purpose == "teaching" and linked and linked["context_focus"].get("kind") == "attempt":
            _, legacy_only = attempt_material_scope_in(
                connection, actor, TeachingFocus(**linked["context_focus"]),
            )
            inferred = demand and demand.consumer_ref in {
                f"tutor-turn:{turn_id}:teaching",
                f"tutor-turn:{turn_id}:teaching:semantic-goal.v1",
                f"tutor-turn:{turn_id}:teaching:attempt-source.v1:semantic-goal.v1",
            }
            if legacy_only:
                if demand is None:
                    return None
                if inferred:
                    task = connection.execute(
                        "SELECT d.id,d.author_messages,d.context_manifest "
                        "FROM tutor.delivery_tasks d JOIN runtime.runs r ON r.id=d.run_id "
                        "WHERE r.actor_id=%s AND r.input_ref=%s", (actor.id, turn_id),
                    ).fetchone()
                    scope = {
                        "receipt_id": linked["context_focus"]["assessment_receipt_id"],
                        "superseded_demand_id": str(demand.id),
                    }
                    if task and task["context_manifest"].get("legacy_attempt_sources") == scope:
                        return None
                    has_call = connection.execute(
                        "SELECT 1 FROM runtime.external_calls c JOIN runtime.runs r "
                        "ON r.id=c.run_id WHERE r.actor_id=%s AND r.input_ref=%s LIMIT 1",
                        (actor.id, turn_id),
                    ).fetchone()
                    if not has_call:
                        if freeze and task:
                            Deliveries(connection).context(task["id"], task["author_messages"], {
                                **task["context_manifest"], "legacy_attempt_sources": scope,
                            })
                        return None
        if linked and linked["material_demand_id"]:
            return demand
        return demand if demand and demand.status != "cancelled" else None

    def heartbeat(self, lease):
        with self.database.transaction() as connection:
            return Runs(connection).heartbeat(lease, self.settings.run_lease_seconds)

    def token_calibration(self, endpoint, model, stage):
        with self.database.transaction(snapshot=True) as connection:
            return Runs(connection).calibration(endpoint, model, stage)

    def yield_run(self, lease):
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row:
                Runs(connection).resume(row["id"])

    @staticmethod
    def _learning_context(connection, actor, goal_id, materials) -> dict:
        goal = Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
        context = {
            "goal": goal.model_dump(mode="json"),
            "materials": [material.model_dump(mode="json") for material in materials],
        }
        dynamic_plan = Plans(connection).for_goal(actor, goal_id)
        if dynamic_plan:
            # Previous content is reference data, not authority to reuse old source excerpts.
            context["dynamic_plan"] = {
                "id": str(dynamic_plan.id),
                "latest_revision": dynamic_plan.latest.revision,
                "latest_document": dynamic_plan.latest.document.model_dump(mode="json"),
                "active_revision": dynamic_plan.active.revision if dynamic_plan.active else None,
                "active_document": dynamic_plan.active.document.model_dump(mode="json")
                if dynamic_plan.active
                else None,
            }
            if dynamic_plan.active:
                generated = Lessons(connection).latest_for_plan(
                    actor,
                    dynamic_plan.id,
                    dynamic_plan.active.revision,
                )
                current_sources = {(item.source_id, item.revision) for item in materials}
                if generated and all(
                    (item.source_id, item.revision) in current_sources for item in generated.sources
                ):
                    context["latest_generated_lesson"] = {
                        "id": str(generated.id),
                        "plan_revision": generated.plan_revision,
                        "node_key": generated.node_key,
                        "document": generated.document.model_dump(mode="json"),
                    }
        track = Journey(connection).for_goal(actor, goal_id)
        if track:
            context["plan"] = track.model_dump(mode="json")
            if track.status != "draft":
                context["lesson"] = Lesson().model_dump(mode="json")
                context["exercise"] = published_item(track.course_version).exercise.model_dump(
                    mode="json"
                )
                context["recent_feedback"] = [
                    attempt.model_dump(mode="json")
                    for attempt in Assessment(connection).recent_for_track(actor, track.id)
                ]
        return context

    def conversation(self, token: str, goal_id: UUID) -> Conversation:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
            return Tutor(PgTutorStore(connection)).conversation(actor, goal_id)

    def hide_conversation(self, token: str, conversation_id: UUID) -> Conversation:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            tutor = Tutor(PgTutorStore(connection))
            conversation = tutor.get(actor, conversation_id, lock=True)
            if conversation.hidden_from_recents:
                return conversation
            conversation = tutor.hide_from_recents(actor, conversation_id)
            Events(connection).append(
                actor.id, "tutor.conversation_hidden", conversation.id,
                EventPayload(conversation_id=conversation.id, goal_id=conversation.goal_id),
            )
            return conversation

    def submit(self, token: str, conversation_id: UUID, key: str, data: TurnInput) -> TurnAccepted:
        return self._submit(token, conversation_id, key, data, "teaching", None)

    def requested_turn(self, token, conversation_id, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            store = PgTutorStore(connection)
            Tutor(store).get(actor, conversation_id)
            turn = store.requested_turn(conversation_id, key)
            if turn is None:
                raise BusinessError("not_found", "No committed teaching request.")
            run = Runs(connection).for_turn(actor.id, turn.id)
            task = Deliveries(connection).for_run(run.id)
            return TurnAccepted(
                run_id=run.id, turn_id=turn.id,
                delivery_task_id=task["id"] if task else None,
            )

    def submit_plan(
        self,
        token: str,
        conversation_id: UUID,
        key: str,
        data: PlanningInput,
    ) -> TurnAccepted:
        return self._submit(token, conversation_id, key, data, "planning", data.expected_revision)

    def submit_lesson(
        self,
        token: str,
        plan_id: UUID,
        key: str,
        data: LessonRequestInput,
    ) -> TurnAccepted:
        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate(token)
            return self._submit_lesson_in(
                connection, actor, identity.digest(token), plan_id, key, data,
            )

    def _submit_lesson_in(self, connection, actor, digest, plan_id, key, data):
        from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
        from leornian.modules.tutor.teaching_sessions import TeachingSessions

        plan = Plans(connection).get(actor, plan_id)
        tutor = Tutor(PgTutorStore(connection))
        conversation = tutor.conversation(actor, plan.goal_id)
        teaching_session = TeachingSessions(connection).get(conversation.id)
        lessons = Lessons(connection)
        request, _created = lessons.request(actor, plan_id, key, data)
        turn, created = tutor.request_turn(
            conversation.id, key, data.instruction, "lesson", None, request.id,
        )
        runs = Runs(connection)
        if not created:
            run = runs.for_turn(actor.id, turn.id)
            task = Deliveries(connection).for_run(run.id)
            return TurnAccepted(
                run_id=run.id, turn_id=turn.id, delivery_task_id=task["id"] if task else None
            )
        TeachingContinuationWorkflow.preempt_in(connection, actor, conversation.id)
        tutor.get(actor, conversation.id, lock=True)
        if teaching_session and teaching_session.active_branch_id:
            raise BusinessError("precondition_failed", "Return to the teaching mainline first.")
        Gates(connection).require_no_exam(actor)
        if runs.active(conversation.id):
            raise BusinessError("run_active", "Finish the active conversation run first.")
        require_model_admission(self.settings)
        node = lessons.current(actor, request)
        Knowledge(connection).current(actor, plan.goal_id, node.source_refs)
        lessons.current(actor, request, lock=True)
        focus = TeachingFocus(
            kind="node", plan_id=plan_id,
            expected_plan_revision=request.plan_revision, node_key=request.node_key,
        )
        if self.settings.delivery_enabled:
            prepare_consumer_in(
                connection, actor, conversation, turn, "lesson", focus, session_digest=digest,
            )
        elif node.material_citations:
            raise BusinessError(
                "precondition_failed", "Material-cited lessons require qualified delivery."
            )
        run = runs.create(
            actor.id, conversation.id, turn.id, digest, "lesson.v1",
            configuration_scope=configuration_scope(self.settings),
        )
        runs.bind_sources(run.id, [ref.model_dump(mode="json") for ref in node.source_refs])
        task = None
        if self.settings.delivery_enabled:
            PgTutorStore(connection).bind_focus(turn.id, focus)
            task = Deliveries(connection).create(
                actor, run.id, "lesson", focus.model_dump(mode="json")
            )
        self._event(connection, runs.lock(run.id), "queued")
        return TurnAccepted(
            run_id=run.id, turn_id=turn.id, delivery_task_id=task.id if task else None
        )

    def lesson_document(self, token: str, lesson_id: UUID) -> GeneratedLesson:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Lessons(connection).get(actor, lesson_id)

    def _submit(
        self,
        token: str,
        conversation_id: UUID,
        key: str,
        data: TurnInput,
        purpose: str,
        base_revision: int | None,
    ) -> TurnAccepted:
        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate(token)
            return self._submit_in(
                connection, actor, identity.digest(token), conversation_id, key, data,
                purpose, base_revision,
            )

    def _submit_in(
        self, connection, actor, digest, conversation_id, key, data, purpose,
        base_revision, *, intent=None, source_run=None,
    ):
        tutor = Tutor(PgTutorStore(connection))
        conversation = tutor.get(actor, conversation_id)
        turn, created = tutor.request_turn(
            conversation_id,
            key,
            data.text,
            purpose,
            base_revision,
            teaching_intent_id=intent["id"] if intent else None,
        )
        runs = Runs(connection)
        from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
        from leornian.modules.tutor.teaching_sessions import TeachingSessions

        sessions = TeachingSessions(connection)
        session_binding = None
        if data.node_pacing and (
            purpose != "teaching" or data.focus.kind != "node" or not data.teaching_session_revision
        ):
            raise BusinessError("precondition_failed", "Node pacing needs a bound node session.")
        if created and intent is None:
            from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow

            TeachingContinuationWorkflow.preempt_in(connection, actor, conversation_id)
        conversation = tutor.get(actor, conversation_id, lock=True)
        if not created:
            session_binding = sessions.replay(turn.id, data)
            if session_binding:
                run = runs.for_turn(actor.id, turn.id)
                task = Deliveries(connection).for_run(run.id)
                return TurnAccepted(
                    run_id=run.id, turn_id=turn.id,
                    delivery_task_id=task["id"] if task else None,
                )
        elif purpose == "teaching":
            if sessions.get(conversation_id) and not self.settings.delivery_enabled:
                raise BusinessError("precondition_failed", "Sessions require checked delivery.")
            session_binding = sessions.admit(
                actor, conversation_id, turn.id, data, mainline=intent is not None,
            )
        else:
            teaching_session = sessions.get(conversation_id)
            if data.teaching_session_revision is not None or (
                teaching_session and teaching_session.active_branch_id
            ):
                raise BusinessError(
                    "precondition_failed", "Return to the teaching mainline first."
                )
        branch = bool(session_binding and session_binding["teaching_branch_id"])

        if purpose != "teaching" and data.learning_candidate_id is not None:
            raise BusinessError(
                "precondition_failed", "Only teaching can introduce a candidate."
            )
        if data.presentation_capabilities.versions and (
            purpose != "teaching" or not self.settings.delivery_enabled
        ):
            raise BusinessError(
                "precondition_failed", "Compositions need checked teaching delivery."
            )
        LearningArtifactWorkflow.bind_in(
            connection, actor, conversation_id, turn, data.learning_candidate_id, data.focus,
            created=created,
        )
        if not created:
            if turn.context_focus != data.focus:
                raise BusinessError("idempotency_conflict", "Turn focus changed.")
            run = runs.for_turn(actor.id, turn.id)
            frozen = runs.lock(run.id)
            if (
                ("prepare_learning_composition" in frozen["tool_contracts"])
                != bool(data.presentation_capabilities.versions)
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client presentation support changed."
                )
            if (
                ("prepare_learning_template" in frozen["tool_contracts"])
                != ("learning_templates.v1" in data.presentation_capabilities.actions
                    and not branch)
            ):
                raise BusinessError("idempotency_conflict", "Client template support changed.")
            if (
                ("prepare_learning_practice_composition" in frozen["tool_contracts"])
                != ("learning_practice.v2" in data.presentation_capabilities.actions)
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client practice action support changed."
                )
            if (
                ("prepare_learning_response_composition" in frozen["tool_contracts"])
                != ("learning_responses.v1" in data.presentation_capabilities.actions)
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client response action support changed."
                )
            if (
                ("prepare_learning_code_review_composition" in frozen["tool_contracts"])
                != ("learning_code_review.v1" in data.presentation_capabilities.actions)
                or ("prepare_learning_code_review_composition_v2" in frozen["tool_contracts"])
                != ("learning_code_review.v2" in data.presentation_capabilities.actions)
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client submitted-review support changed."
                )
            if (
                ("prepare_learning_program_composition" in frozen["tool_contracts"])
                != bool({"learning_programs.v1", "learning_programs.v2"}
                        & set(data.presentation_capabilities.actions))
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client program action support changed.",
                )
            if (
                ("prepare_learning_assisted_composition" in frozen["tool_contracts"])
                != ("learning_direct_answers.v1" in data.presentation_capabilities.actions)
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client direct-answer support changed."
                )
            if (
                ("prepare_learning_hint_composition" in frozen["tool_contracts"])
                != ("learning_hints.v1" in data.presentation_capabilities.actions)
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client graduated-hint support changed."
                )
            if (
                ("prepare_learning_demo_composition" in frozen["tool_contracts"])
                != ("learning_demo_events.v1" in data.presentation_capabilities.actions)
            ):
                raise BusinessError(
                    "idempotency_conflict", "Client demonstration event support changed."
                )
            task = Deliveries(connection).for_run(run.id)
            frozen_examples = task and task["context_manifest"].get("example_runs")
            if ("learning_example_runs.v1" if frozen_examples is True else frozen_examples) != (
                example_capability(data.presentation_capabilities.actions)
            ):
                raise BusinessError("idempotency_conflict", "Client example run support changed.")
            if purpose == "planning" and bool(
                task and task["context_manifest"].get("route_discussion") == 1
            ) != getattr(data, "discussion", False):
                raise BusinessError("idempotency_conflict", "Planning request mode changed.")
            if purpose == "planning" and getattr(data, "start_plan", False) != bool(
                turn.planning_state and turn.planning_state.start_action
            ):
                raise BusinessError("idempotency_conflict", "Planning start action changed.")
            return TurnAccepted(
                run_id=run.id, turn_id=turn.id, delivery_task_id=task["id"] if task else None
            )
        Gates(connection).require_no_exam(actor)
        if runs.active(conversation_id):
            raise BusinessError(
                "run_active", "Finish or cancel the current teaching turn first."
            )
        require_model_admission(self.settings)
        if purpose == "planning":
            Plans(connection).require_base(actor, conversation.goal_id, base_revision)
            if getattr(data, "discussion", False) and (
                not self.settings.delivery_enabled or data.focus.kind != "goal"
            ):
                raise BusinessError(
                    "precondition_failed", "Route discussion requires checked goal-scoped planning."
                )
            if getattr(data, "start_plan", False):
                if not getattr(data, "discussion", False):
                    raise BusinessError(
                        "precondition_failed", "Start the plan from its discussion.",
                    )
                state = PgTutorStore(connection).ready_to_plan(
                    conversation.id, getattr(data, "expected_requirements_revision", None),
                    exclude_turn=turn.id,
                ).model_copy(update={
                    "plan_requested": True, "material_blocked": False, "start_action": True,
                })
                PgTutorStore(connection).planning_state(turn.id, state)
                turn = tutor.get_turn(conversation.id, turn.id)
                from leornian.bootstrap.planning_materials import PlanningMaterials

                PlanningMaterials.begin_in(connection, actor, conversation, turn, digest)
        task = None
        if self.settings.delivery_enabled:
            demand = prepare_consumer_in(
                connection, actor, conversation, turn, purpose, data.focus, session_digest=digest,
                discussion=getattr(data, "discussion", False),
            )
            try:
                TeachingContext.build(
                    connection, actor, conversation, data.focus, material_purpose=purpose,
                    material_demand=None if getattr(data, "discussion", False) else demand,
                    session_digest=digest,
                )
            except BusinessError as error:
                if error.code != "material_pending":
                    raise
            PgTutorStore(connection).bind_focus(turn.id, data.focus)
        lookup_tools = available_tools(connection, self.settings, actor, conversation.goal_id) if (
            purpose == "teaching" and data.focus.kind == "node" and self.settings.delivery_enabled
            and configuration_scope(self.settings) == "user" and not source_run
        ) else ()
        run = runs.create(
            actor.id,
            conversation_id,
            turn.id,
            digest,
            "planner.v1" if purpose == "planning" else "tutor.v1",
            tools=(tuple(
                name for name in TEACHING_TOOLS if REGISTRY[name].effect == "read"
            ) if branch else TEACHING_TOOLS + (
                COMPOSITION_TOOLS if data.presentation_capabilities.versions else ()
            ) + (
                TEMPLATE_TOOLS
                if "learning_templates.v1" in data.presentation_capabilities.actions else ()
            ) + (
                PRACTICE_COMPOSITION_TOOLS
                if "learning_practice.v2" in data.presentation_capabilities.actions else ()
            ) + (
                RESPONSE_COMPOSITION_TOOLS
                if "learning_responses.v1" in data.presentation_capabilities.actions else ()
            ) + (
                CODE_REVIEW_COMPOSITION_TOOLS
                if "learning_code_review.v1" in data.presentation_capabilities.actions else ()
            ) + (
                CODE_REVIEW_COMPLETION_TOOLS
                if "learning_code_review.v2" in data.presentation_capabilities.actions else ()
            ) + (
                PROGRAM_COMPOSITION_TOOLS
                if {"learning_programs.v1", "learning_programs.v2"}
                & set(data.presentation_capabilities.actions) else ()
            ) + (
                ASSISTED_COMPOSITION_TOOLS
                if "learning_direct_answers.v1" in data.presentation_capabilities.actions
                else ()
            ) + (
                HINT_COMPOSITION_TOOLS
                if "learning_hints.v1" in data.presentation_capabilities.actions else ()
            ) + (
                DEMO_COMPOSITION_TOOLS
                if "learning_demo_events.v1" in data.presentation_capabilities.actions else ()
            ) + (
                PRACTICE_SUPPLY_TOOLS if any(
                    c in data.presentation_capabilities.actions
                    for c in ("learning_practice.v2", "learning_responses.v1")
                ) else ()
            )) + lookup_tools
            if purpose == "teaching" and self.settings.delivery_enabled
            else None,
            configuration_scope=source_run["model_configuration_scope"] if source_run else (
                configuration_scope(self.settings)
            ),
            frozen_tools=source_run["tool_contracts"] if source_run else None,
        )
        if self.settings.delivery_enabled:
            task = Deliveries(connection).create(
                actor, run.id, purpose, data.focus.model_dump(mode="json")
            )
            if purpose == "teaching":
                manifest = {}
                if data.focus.kind in {"node", "attempt"}:
                    manifest["node_turn_contract"] = 1
                    manifest["operation_wording_repair"] = 1
                if data.focus.kind == "node" and demand:
                    manifest["material_demand"] = {
                        "id": str(demand.id), "revision": demand.revision,
                    }
                if capability := example_capability(data.presentation_capabilities.actions):
                    manifest["example_runs"] = capability
                if branch:
                    from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow

                    anchor = TeachingSessionWorkflow.context_in(
                        connection, actor, turn.id, node_turn="node_turn_contract" in manifest,
                    )
                    if "node_turn_contract" in manifest:
                        manifest["teaching_session"] = {
                            key: value for key, value in anchor.items() if key != "public_anchor"
                        }
                if manifest:
                    Deliveries(connection).context(task.id, [], manifest)
            if purpose == "planning" and getattr(data, "discussion", False):
                Deliveries(connection).context(task.id, [], {
                    "route_discussion": 1, "planning_requested": turn.planning_requested,
                    "planning_policy": "model-first.v1",
                })
        row = runs.lock(run.id)
        if branch:
            from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow

            TeachingSessionWorkflow.event(connection, actor, conversation_id)
        self._event(connection, row, "queued")
        return TurnAccepted(
            run_id=run.id, turn_id=turn.id, delivery_task_id=task.id if task else None
        )

    def plan(self, token: str, plan_id: UUID) -> LearningPlan:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Plans(connection).get(actor, plan_id)

    def plan_history(self, token: str, plan_id: UUID, before=None, limit=20) -> list[PlanRevision]:
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Plans(connection).history(actor, plan_id, before, limit)

    def plan_confirmation(self, token, plan_id, revision):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Plans(connection).confirmation(actor, plan_id, revision)

    def confirm_plan(
        self, token: str, plan_id: UUID, revision: int, environment_requirements=None,
    ) -> LearningPlan:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Gates(connection).require_no_exam(actor)
            plans = Plans(connection)
            plan = plans.get(actor, plan_id)
            if plan.latest.revision != revision:
                raise BusinessError("stale_version", "Only the current draft may be confirmed.")
            if plan.active and plan.active.revision == revision:
                # Confirmation receipts are immutable; later installation uses its own decision.
                return plan
            Knowledge(connection).current(
                actor,
                plan.goal_id,
                [
                    SourceRef(source_id=item.source_id, revision=item.revision)
                    for item in plan.latest.sources
                ],
            )
            read_citations_in(
                connection, actor, plan.goal_id,
                [c for node in plan.latest.document.nodes for c in node.material_citations],
            )
            plan, changed = plans.confirm(actor, plan_id, revision)
            from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow

            ExecutionEnvironmentWorkflow.prepare_route_in(
                connection, actor, plan, environment_requirements,
            )
            if changed:
                Events(connection).append(
                    actor.id,
                    "learning.dynamic_plan_confirmed",
                    plan.id,
                    EventPayload(goal_id=plan.goal_id, plan_id=plan.id, plan_revision=revision),
                )
            return plan

    def get(self, token: str, run_id: UUID) -> Run:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Runs(connection).get(actor.id, run_id)

    def delivery_tasks(self, token, before=None, limit=50):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Deliveries(connection).page(actor, before, limit)

    def delivery_task(self, token, task_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            store = Deliveries(connection)
            row = store.row(actor, task_id)
            task = store.summary(row)
            if row["status"] == "blocked_unknown":
                task = task.model_copy(
                    update={"can_resume": Runs(connection).get(actor.id, row["run_id"]).can_resume}
                )
            return task

    def cancel_delivery(self, token, task_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            task = Deliveries(connection).row(actor, task_id)
        self.cancel(token, task["run_id"])
        return self.delivery_task(token, task_id)

    def resume_delivery(self, token, task_id, additional_instruction=""):
        return self._resume_delivery_digest(Identity.digest(token), task_id, additional_instruction)

    def _resume_delivery_digest(self, digest, task_id, additional_instruction=""):
        from psycopg.types.json import Jsonb

        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                digest
            )
            store = Deliveries(connection)
            task = store.row(actor, task_id)
            runs = Runs(connection)
            row = runs.lock(task["run_id"])
            task = store.row(actor, task_id)
            turn = PgTutorStore(connection).get_turn(row["scope_id"], row["input_ref"])
            material_wait = bool(
                task["context_manifest"].get("awaiting_route_materials")
                and turn.planning_state and turn.planning_state.material_blocked
            )
            if task["context_manifest"].get("route_discussion") == 1 and turn.completed_at and (
                not material_wait
            ):
                raise BusinessError(
                    "resume_not_allowed", "这条答复已经交付，请主动发起新的制定或修复请求。",
                )
            if material_wait and turn.id != next((
                item.id for item in reversed(PgTutorStore(connection).turns(row["scope_id"]))
                if item.purpose == "planning"
            ), None):
                raise BusinessError("resume_not_allowed", "已有更新的路线请求，保留原阻塞记录。")
            if task["cancel_requested"] or task["status"] not in {
                "waiting_input",
                "waiting_dependency",
                "waiting_config",
                "blocked_unknown",
                "blocked_protocol",
            }:
                raise BusinessError("resume_not_allowed", "Delivery is not awaiting recovery.")
            if task["status"] == "waiting_input" and not material_wait and (
                not additional_instruction.strip()
            ):
                raise BusinessError(
                    "precondition_failed", "Provide the requested information first."
                )
            if connection.execute(
                "SELECT id FROM runtime.runs WHERE scope_id=%s AND id!=%s "
                "AND status IN ('queued','running','blocked_unknown')",
                (row["scope_id"], row["id"]),
            ).fetchone():
                raise BusinessError("run_active", "Finish the other conversation run first.")
            call = runs.latest(row["id"])
            if task["status"] == "blocked_protocol" and (
                row["status"] == "blocked_unknown"
                and (not call or call.status != "result_recorded" or call.applied)
            ):
                raise BusinessError(
                    "unknown_unresolved", "Resolve the in-flight receipt before protocol recovery."
                )
            if call and call.status in {"failed_known", "not_sent"}:
                runs.applied(call.id)
            if task["status"] == "blocked_unknown" and (
                not call or call.status != "result_recorded" or call.applied
            ):
                raise BusinessError(
                    "unknown_unresolved", "No complete receipt authorizes recovery."
                )
            if (
                call is None and task["kind"] == "teaching"
                and row["error_code"] == "material_pending"
                and turn.context_focus.kind == "attempt"
                and turn.material_demand_id is None
            ):
                demand = self._material_demand(connection, actor, turn.id, "teaching")
                if demand and demand.consumer_ref == (
                    f"tutor-turn:{turn.id}:teaching:semantic-goal.v1"
                ):
                    prepare_consumer_in(
                        connection, actor,
                        Tutor(PgTutorStore(connection)).get(actor, row["scope_id"]),
                        turn, "teaching", turn.context_focus, session_digest=digest,
                    )
            if material_wait:
                PgTutorStore(connection).reopen_material_wait(turn.id)
            recovered_reply = TeachingDelivery.recover_waiting_reply(connection, row, task)
            if recovered_reply:
                task = store.row(actor, task_id)
            if task["context_manifest"].get("awaiting_route_materials") and not recovered_reply:
                if not task["context_manifest"].get("planning_requested"):
                    raise BusinessError(
                        "resume_not_allowed", "请在收集完必要信息后，主动发起制定计划。",
                    )
                try:
                    TeachingContext.build(
                        connection, actor, Tutor(PgTutorStore(connection)).get(
                            actor, row["scope_id"],
                        ), TeachingFocus(**task["focus"]), material_purpose="planning",
                        material_demand=self._material_demand(
                            connection, actor, row["input_ref"], "planning",
                        ), session_digest=digest,
                    )
                except BusinessError as error:
                    if error.code != "material_pending":
                        raise
                    demand = self._material_demand(connection, actor, row["input_ref"], "planning")
                    if demand and self._planning_wait(connection, actor, row, task, demand):
                        return store.summary(store.row(actor, task_id))
                    store.state(task_id, "waiting_dependency")
                    return store.summary(store.row(actor, task_id))
                demand = self._material_demand(connection, actor, row["input_ref"], "planning")
                if demand:
                    from leornian.bootstrap.tutor_activity import TutorActivity

                    TutorActivity.material_wait(connection, row, demand.id, completed=True)
            if additional_instruction:
                if task["status"] == "blocked_unknown":
                    raise BusinessError(
                        "resume_not_allowed", "Consume the receipt before changing input."
                    )
                manifest = task["context_manifest"]
                messages = task["author_messages"]
                if manifest.get("node_turn_contract") == 1 and not messages:
                    manifest = {**manifest, "learner_clarifications": [
                        *manifest.get("learner_clarifications", []), additional_instruction,
                    ]}
                else:
                    messages = [*messages, {"role": "user", "content": additional_instruction}]
                connection.execute(
                    "UPDATE tutor.delivery_tasks SET author_messages=%s,context_manifest=%s,"
                    "phase='author',issues='[]' WHERE id=%s",
                    (Jsonb(messages), Jsonb(manifest), task_id),
                )
            connection.execute(
                "UPDATE runtime.runs SET session_digest=%s WHERE id=%s",
                (digest, row["id"]),
            )
            if task["status"] == "blocked_protocol":
                connection.execute(
                    "UPDATE tutor.delivery_tasks SET protocol_repair='{}' WHERE id=%s",
                    (task_id,),
                )
            store.state(
                task_id,
                "checking"
                if task["phase"] == "review" and not additional_instruction
                else "repairing",
            )
            runs.resume(row["id"])
            if self._current(
                connection, runs.claim(runs.lock(row["id"]), self.settings.run_lease_seconds)
            ):
                runs.resume(row["id"])
                self._event(connection, row, "queued")
            result = store.summary(store.row(actor, task_id))
        return result

    def reconcile_deliveries(self):
        ArtifactWorkflow(self.database, self.settings).reconcile_once()
        with self.database.transaction() as connection:
            candidates = connection.execute(
                "SELECT t.id,r.session_digest FROM tutor.delivery_tasks t "
                "JOIN runtime.runs r ON r.id=t.run_id WHERE NOT t.cancel_requested AND "
                "((t.status='waiting_dependency' AND t.next_action_at<=now()) OR "
                "(t.status='blocked_unknown' AND EXISTS(SELECT 1 FROM runtime.external_calls c "
                "WHERE c.run_id=r.id AND c.status='result_recorded' AND NOT c.applied))) "
                "AND (t.context_manifest->>'route_discussion' IS DISTINCT FROM '1' "
                "OR t.context_manifest->>'planning_requested'='true' "
                "OR t.status='blocked_unknown') "
                "AND NOT EXISTS(SELECT 1 FROM tutor.turns finished WHERE finished.id=r.input_ref "
                "AND finished.completed_at IS NOT NULL "
                "AND t.context_manifest->>'route_discussion'='1' "
                "AND (finished.planning_state->>'material_blocked' IS DISTINCT FROM 'true' "
                "OR t.context_manifest->>'awaiting_route_materials' IS DISTINCT FROM 'true')) "
                "ORDER BY t.updated_at LIMIT 20"
            ).fetchall()
        for task in candidates:
            try:
                self._resume_delivery_digest(task["session_digest"], task["id"])
            except BusinessError:
                continue
        return len(candidates)

    def turn_history(self, token, conversation_id, before=None, limit=50):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            turns = PgTutorStore(connection).page(conversation_id, before, limit)
            thinking = Events(connection).thinking(actor.id, [turn.id for turn in turns])
            thinking = {
                **Runs(connection).visible_thinking(actor.id, [
                    turn.id for turn in turns
                    if turn.assistant_text is not None and str(turn.id) not in thinking
                ]),
                **thinking,
            }
            steps = Events(connection).thinking_steps(actor.id, [turn.id for turn in turns])
            return [
                Events(connection).attach_reply_thinking(
                    actor.id, turn, thinking.get(str(turn.id)), steps.get(str(turn.id), []),
                )
                for turn in turns
            ]

    def material_progress(self, token, conversation_id):
        from leornian.bootstrap.material_consumers import consumer_material_required_in
        from leornian.modules.knowledge.progress import MaterialPreparation
        from leornian.modules.knowledge.progress_contracts import MaterialPreparationProgress

        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            turns = [
                turn for turn in PgTutorStore(connection).turns(conversation_id)
                if turn.purpose in {"planning", "teaching"}
            ]
            if not turns:
                return MaterialPreparationProgress()
            latest = turns[-1]
            demand = self._material_demand(connection, actor, latest.id, latest.purpose)
            if not demand or not consumer_material_required_in(connection, actor, demand):
                return MaterialPreparationProgress()
            return MaterialPreparation(connection).for_demand(actor, demand.id)

    def cancel(self, token: str, run_id: UUID) -> Run:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return self.cancel_in(connection, actor, run_id)

    @classmethod
    def cancel_in(cls, connection, actor, run_id):
        runs = Runs(connection)
        runs.get(actor.id, run_id)
        row = runs.lock(run_id)
        task = Deliveries(connection).for_run(run_id)
        if task and task["status"] not in {"accepted", "cancelled", "superseded"}:
            connection.execute(
                "UPDATE tutor.delivery_tasks SET cancel_requested=true WHERE id=%s",
                (task["id"],),
            )
            Deliveries(connection).state(task["id"], "cancelled")
        if row["status"] not in {"succeeded", "failed", "cancelled"}:
            runs.cancel(run_id)
            connection.execute(
                "UPDATE tutor.artifact_requests SET status='cancelled' "
                "WHERE parent_run_id=%s AND run_id IS NULL "
                "AND status IN ('queued','waiting_config')",
                (run_id,),
            )
            runs.mark_unknown(run_id)
            cls._finish(connection, row, "cancelled")
        if task and task["kind"] in {"teaching", "lesson"}:
            from leornian.bootstrap.material_consumers import stop_consumer_material_in

            demand = cls._material_demand(connection, actor, row["input_ref"], task["kind"])
            if demand:
                stop_consumer_material_in(connection, actor, demand, row["input_ref"])
        return runs.get(actor.id, run_id)

    def resume(self, token: str, run_id: UUID) -> Run:
        return self.resume_digest(Identity.digest(token), run_id)

    def resume_digest(self, digest: str, run_id: UUID) -> Run:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                digest
            )
            runs = Runs(connection)
            runs.get(actor.id, run_id)
            row = runs.lock(run_id)
            call = runs.latest(run_id)
            recorded_batch = (
                row
                and row["status"] == "failed"
                and row["policy_version"] == "gate_relation.v1"
                and row["error_code"] == "invalid_relation_batch"
            )
            if (
                not row
                or row["status"] != "blocked_unknown"
                and not recorded_batch
                or row["cancel_requested"]
            ):
                raise BusinessError("resume_not_allowed", "This run cannot be resumed.")
            if not call or call.status != "result_recorded" or call.applied:
                raise BusinessError("unknown_unresolved", "No recorded result supports resuming.")
            if recorded_batch:
                gates = Gates(connection)
                gate = gates.for_run(run_id)
                ConceptGate.current(connection, actor, {**gate, "status": "preparing"})
                gates.resume_recorded_batch(actor, gate)
                ConceptGate.event(connection, actor.id, gate)
            if row["policy_version"].startswith("item_"):
                stage = Packs(connection).stage(run_id)
                pack = Packs(connection).row(actor, stage["pack_id"])
                SupplyTasks(connection).require_current(actor, pack["id"])
                ItemSupply.current(connection, actor, pack)
            if row["policy_version"] == "transfer_relation.v1":
                TransferWorkflow.current(connection, actor, Transfers(connection).for_run(run_id))
            # A new session may authorize consuming a late result, never resending its call.
            connection.execute(
                "UPDATE runtime.runs SET session_digest = %s WHERE id = %s",
                (digest, run_id),
            )
            self._event(connection, row, "queued")
            task = Deliveries(connection).for_run(run_id)
            if task:
                Deliveries(connection).state(
                    task["id"], "checking" if task["phase"] == "review" else "repairing"
                )
            runs.resume(run_id)
            return runs.get(actor.id, run_id)

    def claim(self, run_id: UUID) -> Lease | None:
        with self.database.transaction() as connection:
            runs = Runs(connection)
            row = runs.lock(run_id)
            if not row or row["status"] not in {"queued", "running"}:
                return None
            if row["status"] == "running" and row["lease_valid"]:
                return None
            call = runs.latest(run_id)
            if call and call.status in {"dispatching", "unknown"}:
                runs.mark_unknown(run_id)
                self._finish(connection, row, "blocked_unknown", "external_result_unknown")
                return None
            lease = runs.claim(row, self.settings.run_lease_seconds)
            if self._current(connection, lease) is None:
                return None
            self._event(connection, row, "running")
            return lease

    def _planning_wait(self, connection, actor, row, task, demand):
        from leornian.bootstrap.planning_materials import PlanningMaterials

        blocked = PlanningMaterials.blockage_in(connection, actor, demand)
        if blocked:
            descriptions = {
                "blocked_unknown": "资料处理的一次外部调用结果未知，需要先核对原回执。",
                "waiting_config": "资料获取或处理配置不可用，需要检查 Key、模型配置或来源权限。",
                "waiting_dependency": "资料获取或解析未通过，需针对出错步骤修复后继续。",
            }
            if blocked.reason_code == "approved_source_required":
                description = "当前主题尚未找到可用的已授权官方资料入口，正在核对来源范围。"
            elif blocked.reason_code == "material_discovery_exhausted":
                from leornian.modules.knowledge.source_acquisition import MaterialSources

                discovery = MaterialSources(connection).discovery(
                    actor, demand.id, demand.revision,
                )
                gaps = discovery.missing_facets if discovery else [demand.goal_text]
                searched = connection.execute(
                    "SELECT 1 FROM knowledge.material_web_requests w "
                    "JOIN runtime.external_calls c ON c.operation_ref=w.id "
                    "WHERE w.discovery_id=%s AND c.status='result_recorded' "
                    "AND c.endpoint LIKE '%%/search' LIMIT 1",
                    (discovery.id if discovery else None,),
                ).fetchone()
                description = (
                    (
                        "已检查候选资料并取得定向搜索回执，当前仍缺少足够的可用正文。"
                        if searched else
                        "已检查本轮候选资料，当前仍缺少足够的可用正文；"
                        "本轮没有已完成的联网补搜回执。"
                    )
                    + "\n\n资料缺口：" + "；".join(gaps)
                )
            elif blocked.reason_code == "material_quality_pending":
                description = (
                    "资料检查未取得可用结果。\n\n"
                    "尚未完成的检查范围：" + demand.goal_text
                )
            else:
                description = descriptions.get(
                    blocked.status, "本次计划所需的资料尚未准备完成。",
                )
            self._planning_blocked(
                connection, row, task, blocked.reason_code or "material_blocked",
                description
                + (f"\n\n当前阻塞：{blocked.reason_code}" if blocked.reason_code else ""),
            )
            return True
        Deliveries(connection).await_route_materials(task["id"], demand)
        TutorActivity.material_wait(connection, row, demand.id)
        Runs(connection).messages(row["id"], [])
        self._finish(connection, row, "failed", "material_pending")
        return False

    def _planning_blocked(self, connection, row, task, reason, description):
        store = PgTutorStore(connection)
        turn = store.get_turn(row["scope_id"], row["input_ref"])
        if turn.planning_state:
            store.planning_state(
                turn.id, turn.planning_state.model_copy(update={"material_blocked": True}),
            )
        demand = self._material_demand(
            connection,
            Identity(PgIdentityStore(connection)).get_actor(row["actor_id"]),
            turn.id, "planning",
        )
        if demand:
            Deliveries(connection).await_route_materials(
                task["id"], demand, turn_id=turn.id, blockage=reason,
            )
        store.complete(
            turn.id, "制定计划暂时停在资料准备这一步。\n\n" + description
            + (
                "\n\n本轮自动处理已停止，已完成的资料和检查结果已保留。"
                if reason in {"material_discovery_exhausted", "material_quality_pending"}
                else "\n\n已完成的资料和检查结果已保留；资料就绪后系统将继续原任务。"
            ),
        )
        Deliveries(connection).state(task["id"], "waiting_input")
        Runs(connection).finish(row["id"], "failed", reason)
        TutorActivity.finish(connection, row, "failed")
        self._event(connection, row, "failed", reason)

    def context(self, lease: Lease) -> RoleSpec | None:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is None:
                return None
            task = Deliveries(connection).for_run(row["id"])
            if task:
                if task["phase"] == "review":
                    return TeachingDelivery.review_role(task)
                from leornian.modules.tutor.node_reply import pending_handoff

                if task["context_manifest"].get("node_turn_contract") and task["author_messages"]:
                    from leornian.bootstrap.node_turn_context import handoff_role

                    role = RoleSpec(
                        allowed_tools=allowed(row["tool_contracts"]), require_initial_tool=False,
                        recover_tool_errors=len(row["tool_contracts"]) > 1, completion_driven=True,
                        context_manifest=task["context_manifest"],
                        messages=task["author_messages"] + row["messages"],
                    )
                    if issue := pending_handoff(task):
                        return handoff_role(
                            role, task, Runs(connection).tool_results(row["id"]), issue,
                        )
                    return TeachingDelivery.author_role(role, task)
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                tutor = Tutor(PgTutorStore(connection))
                turn = tutor.get_turn(row["scope_id"], row["input_ref"])
                if (
                    task["context_manifest"].get("route_discussion") == 1
                    and turn.planning_requested
                ):
                    from leornian.bootstrap.material_consumers import consumer_material_required_in
                    from leornian.bootstrap.planning_materials import PlanningMaterials

                    demand = self._material_demand(connection, actor, turn.id, "planning")
                    if (
                        demand and PlanningMaterials.blocks_drafting(
                            turn, task["context_manifest"],
                        ) and consumer_material_required_in(connection, actor, demand)
                    ):
                        try:
                            PlanningMaterials.ready_in(
                                connection, actor, row["session_digest"], demand,
                            )
                        except BusinessError as error:
                            if error.code != "material_pending":
                                raise
                            self._planning_wait(connection, actor, row, task, demand)
                            return None
                role = TeachingContext.role(connection, row, tutor, turn, task)
                if not task["author_messages"]:
                    Deliveries(connection).context(task["id"], role.messages, role.context_manifest)
                    Runs(connection).bind_sources(row["id"], role.context_manifest["sources"])
                else:
                    role = role.model_copy(
                        update={
                            "messages": task["author_messages"],
                            "context_manifest": task["context_manifest"],
                            "optional_history": [] if task["context_manifest"].get(
                                "recovering_legacy_planning_reply"
                            ) else role.optional_history,
                        }
                    )
                role = role.model_copy(update={"messages": role.messages + row["messages"]})
                return TeachingDelivery.author_role(role, task)
            if row["policy_version"] == "material_check.v1":
                from leornian.bootstrap.material_goal_coverage import MaterialGoalCoverageWorkflow

                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                if not row["messages"]:
                    role = MaterialGoalCoverageWorkflow.role(connection, actor, row["input_ref"])
                    Runs(connection).messages(row["id"], role.messages)
                    return role
                return RoleSpec(
                    messages=row["messages"], policy_version="material_check.v1", allowed_tools=(),
                    require_initial_tool=False, completion_driven=True,
                )
            if row["policy_version"] == "evaluation.v1":
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                if not row["messages"]:
                    role = EvaluationWorkflow.role(
                        connection, actor, Evaluations(connection).for_run(actor, row["id"])
                    )
                    Runs(connection).messages(row["id"], role.messages)
                    return role
                return RoleSpec(
                    messages=row["messages"], policy_version="evaluation.v1", allowed_tools=()
                )
            if row["policy_version"] == "transfer_relation.v1":
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                if not row["messages"]:
                    role = TransferWorkflow.role(
                        connection, actor, Transfers(connection).for_run(row["id"])
                    )
                    Runs(connection).messages(row["id"], role.messages)
                    return role
                return RoleSpec(
                    messages=row["messages"],
                    policy_version="transfer_relation.v1",
                    allowed_tools=(),
                )
            if row["policy_version"] == "gate_relation.v1":
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                if not row["messages"]:
                    role = ConceptGate.role(connection, actor, Gates(connection).for_run(row["id"]))
                    Runs(connection).messages(row["id"], role.messages)
                    return role
                return RoleSpec(
                    messages=row["messages"], policy_version="gate_relation.v1", allowed_tools=()
                )
            if row["policy_version"].startswith("item_"):
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                stage = Packs(connection).stage(row["id"])
                pack = Packs(connection).row(actor, stage["pack_id"])
                if not row["messages"]:
                    role = ItemSupply.role(connection, actor, pack, stage)
                    Runs(connection).messages(row["id"], role.messages)
                    return role
                return RoleSpec(
                    messages=row["messages"], policy_version=row["policy_version"], allowed_tools=()
                )
            if not row["messages"]:
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                tutor = Tutor(PgTutorStore(connection))
                conversation = tutor.get(actor, row["scope_id"])
                lesson_run = row["policy_version"] == "lesson.v1"
                materials = (
                    Knowledge(connection).current(
                        actor,
                        conversation.goal_id,
                        [SourceRef(**ref) for ref in row["context_refs"]],
                    )
                    if lesson_run
                    else Knowledge(connection).materials(actor, conversation.goal_id)
                )
                refs = [
                    SourceRef(source_id=item.source_id, revision=item.revision)
                    for item in materials
                ]
                Runs(connection).bind_sources(
                    row["id"], [ref.model_dump(mode="json") for ref in refs]
                )
                context = self._learning_context(connection, actor, conversation.goal_id, materials)
                turn = tutor.get_turn(conversation.id, row["input_ref"])
                if lesson_run:
                    request = Lessons(connection).get_request(actor, turn.lesson_request_id)
                    node = Lessons(connection).current(actor, request, lock=True)
                    plan = Plans(connection).get(actor, request.plan_id)
                    context = {
                        "goal": context["goal"],
                        "confirmed_plan_revision": request.plan_revision,
                        "confirmed_plan_title": plan.active.document.title,
                        "node": node.model_dump(mode="json"),
                        "materials": [material.model_dump(mode="json") for material in materials],
                    }
                    from leornian.bootstrap.teaching_memory import TeachingMemory

                    memory, memory_manifest = TeachingMemory.build_in(
                        connection, actor, conversation,
                        TeachingFocus(
                            kind="node", plan_id=request.plan_id,
                            expected_plan_revision=request.plan_revision, node_key=request.node_key,
                        ),
                        plan=plan, branch_id=turn.teaching_branch_id, before_turn_id=turn.id,
                    )
                    context["learning_memory"] = memory
                    role = tutor.lesson_role(context, turn)
                    role = role.model_copy(update={
                        "context_manifest": {"learning_memory": memory_manifest},
                    })
                elif row["policy_version"] == "planner.v1":
                    role = tutor.planning_role(context, turn)
                else:
                    turns = tutor.turns(conversation.id)
                    role = tutor.role(context, turns, row["input_ref"])
                    history = [
                        t
                        for t in turns
                        if t.completed_at and t.id != row["input_ref"] and t.purpose == "teaching"
                    ][-6:]
                    protocol = Runs(connection).protocol_history(actor.id, [t.id for t in history])
                    previous_turns = iter(history)
                    messages = []
                    for message in role.messages:
                        if message["role"] == "assistant":
                            previous = next(previous_turns)
                            prior = protocol.get(previous.id, [{}])
                            messages.extend(prior[:-1])
                            message["reasoning_content"] = prior[-1].get("reasoning_content")
                        messages.append(message)
                    role = role.model_copy(update={"messages": messages})
                Runs(connection).messages(row["id"], role.messages)
                return role
            structured = row["policy_version"] != "tutor.v1"
            previous_call = Runs(connection).latest(row["id"])
            return RoleSpec(
                messages=row["messages"],
                policy_version=row["policy_version"],
                allowed_tools=() if structured else ("learning_get_context",),
                context_manifest=previous_call.context_manifest if previous_call else {},
            )

    def latest(self, lease: Lease) -> StoredCall | None:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            return Runs(connection).latest(lease.run_id) if row else None

    def gateway_for(self, lease, role, call, fallback):
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is None:
                return None
            if row["model_configuration_scope"] == "legacy_development":
                return fallback
            if call and not call.applied and call.status != "prepared":
                # Receipt consumption never needs credentials and never authorizes another send.
                return fallback
            # Do not invert user commands' actor -> run lock order while holding this run row.
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate_digest(
                row["session_digest"]
            )
            models = UserModels(connection, self.settings)
            continuation = (
                call and call.applied and role.messages and role.messages[-1]["role"] == "tool"
            )
            frozen = (
                call.context_manifest.get("model_binding")
                if call and (call.status == "prepared" or continuation)
                else models.binding(actor, role.policy_version)
            )
            if not frozen:
                raise BusinessError("model_unavailable", "Prepared user call has no model binding.")
            resolved = models.resolve_chat(actor, frozen)
            gateway = ChatCompletionsGateway(resolved, transport=fallback.transport)
            gateway.model_binding = frozen
            return gateway

    def prepare(
        self, lease: Lease, endpoint: str, request: dict, policy=None, manifest=None
    ) -> StoredCall | None:
        with self.database.transaction() as connection:
            if self._current(connection, lease) is None:
                return None
            return Runs(connection).prepare(lease.run_id, endpoint, request, policy, manifest)

    def dispatch(self, lease: Lease, call_id: UUID) -> bool:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is None:
                return False
            call = Runs(connection).latest(lease.run_id)
            if not call or call.id != call_id or call.status != "prepared":
                return False
            if row["model_configuration_scope"] == "user":
                actor = Identity(
                    PgIdentityStore(connection, lock_session=True)
                ).authenticate_digest(row["session_digest"])
                frozen = call.context_manifest.get("model_binding")
                if not frozen:
                    raise BusinessError("model_unavailable", "User call has no model binding.")
                UserModels(connection, self.settings).validate_binding(actor, frozen)
                lookup = call.context_manifest.get("node_web_lookup")
                if lookup and not public_scope(connection, actor, UUID(lookup["goal_id"])):
                    runs = Runs(connection)
                    runs.skip_prepared(call.id)
                    finish_lookup(connection, row, call, not_authorized=True)
                    runs.resume(row["id"])
                    return False
            if not Runs(connection).heartbeat(lease, self.settings.run_lease_seconds):
                return False
            dispatched = Runs(connection).dispatch(call_id)
            if dispatched:
                TutorActivity.model(connection, row, call)
            return dispatched

    def model_thinking(self, lease, stage, text):
        if stage not in {"planner.v1", "tutor.v1"} or not text.strip():
            return
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is None:
                return
            call = Runs(connection).latest(row["id"])
            if call:
                TutorActivity.model(connection, row, call, text=text)

    def model_progress(self, lease, stage, phase):
        if stage not in {"tutor.v1", "planner.v1", "delivery_review.v1"}:
            return
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is not None:
                call = Runs(connection).latest(row["id"])
                if call:
                    TutorActivity.model(connection, row, call, phase=phase)

    def record(
        self, call_id: UUID, receipt: Receipt | None = None, *, unknown: bool = False
    ) -> None:
        with self.database.transaction() as connection:
            runs = Runs(connection)
            row = runs.lock(runs.call_run(call_id))
            runs.record(call_id, receipt, unknown=unknown)
            if (
                row["status"] == "blocked_unknown"
                and runs.get(row["actor_id"], row["id"]).can_resume
            ):
                self._event(connection, row, "result_available")

    def block_unknown(self, lease: Lease) -> None:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row:
                Runs(connection).mark_unknown(lease.run_id)
                self._finish(connection, row, "blocked_unknown", "external_result_unknown")

    def fail(self, lease: Lease, code: str) -> None:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row:
                self._finish(connection, row, "failed", code)

    def apply_web_lookup(self, lease, call):
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is None:
                return False
            current = Runs(connection).latest(row["id"])
            if current.id != call.id or current.applied or current.status not in {
                "result_recorded", "failed_known",
            }:
                return False
            finish_lookup(connection, row, current)
            self._event(connection, row, "tool_completed")
            return True

    def apply(self, lease: Lease, call: StoredCall, decision: Decision) -> bool:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is None:
                return False
            runs = Runs(connection)
            current = runs.latest(row["id"])
            if (
                not current
                or current.id != call.id
                or current.applied
                or current.status != "result_recorded"
            ):
                return False
            TutorActivity.model(connection, row, call, status="completed")
            planning = row["policy_version"] == "planner.v1"
            lesson_run = row["policy_version"] == "lesson.v1"
            item_run = row["policy_version"].startswith("item_")
            gate_run = row["policy_version"] == "gate_relation.v1"
            transfer_run = row["policy_version"] == "transfer_relation.v1"
            evaluation_run = row["policy_version"] == "evaluation.v1"
            material_run = row["policy_version"] == "material_check.v1"
            task = Deliveries(connection).for_run(row["id"])
            validate_tools(
                decision,
                ()
                if planning
                or lesson_run
                or item_run
                or gate_run
                or transfer_run
                or evaluation_run
                or material_run
                or task
                and task["phase"] == "review"
                else allowed(row["tool_contracts"]),
                request=call.request,
                recover_arguments=bool(task and len(row["tool_contracts"]) > 1),
            )
            if decision.tools:
                if not task and runs.tool_count(row["id"]) + len(decision.tools) > 2:
                    raise ModelProtocolError("tool_limit")
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                conversation = Tutor(PgTutorStore(connection)).get(actor, row["scope_id"])
                lookup_result = None
                if len(decision.tools) == 1 and decision.tools[0].name == NODE_WEB_TOOL:
                    lookup_result = begin_lookup(
                        connection, actor, conversation, row, call, decision,
                    )
                    if lookup_result is None:
                        return True

                def context_result():
                    if task:
                        context_turn = Tutor(PgTutorStore(connection)).get_turn(
                            conversation.id, row["input_ref"],
                        )
                        node_turn = task["context_manifest"].get("node_turn_contract") == 1
                        if node_turn or task["context_manifest"].get("anchor_context_refresh") == 1:
                            current_context, _ = TeachingContext.turn_data(
                                connection, actor, conversation, TeachingFocus(**task["focus"]),
                                row, context_turn, task,
                            )
                            if node_turn:
                                from leornian.bootstrap.node_turn_context import turn_facts

                                current_context = turn_facts(current_context, context_turn)
                            return TeachingContext.refresh_from_prompt(
                                task["author_messages"], current_context, node_turn=node_turn,
                            )
                        context = TeachingContext.build(
                            connection, actor, conversation, TeachingFocus(**task["focus"]),
                            material_demand=self._material_demand(
                                connection, actor, row["input_ref"], task["kind"],
                            ),
                            session_digest=row["session_digest"],
                            teaching_branch_id=context_turn.teaching_branch_id,
                            memory_before_turn_id=context_turn.id,
                        )[0]
                        from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow

                        session_context = TeachingSessionWorkflow.context_in(
                            connection, actor, row["input_ref"],
                            task["context_manifest"].get("teaching_session"),
                        )
                        if session_context:
                            context["teaching_session"] = session_context
                        return context
                    materials = Knowledge(connection).current(
                        actor,
                        conversation.goal_id,
                        [SourceRef(**ref) for ref in row["context_refs"]],
                    )
                    return self._learning_context(
                        connection, actor, conversation.goal_id, materials
                    )

                router = ToolRouter(
                    self.database,
                    row,
                    task["focus"] if task else TeachingFocus().model_dump(mode="json"),
                    context_result,
                )
                outcomes = ([(lookup_result, 0)] if lookup_result is not None
                            else router.batch(connection, decision.tools))
                if not connection.execute(
                    "SELECT lease_until>clock_timestamp() AS valid FROM runtime.runs WHERE id=%s",
                    (row["id"],),
                ).fetchone()["valid"]:
                    # Roll back commands as well as receipts; a new lease consumes the same
                    # recorded model response without dispatching the provider again.
                    raise BusinessError("precondition_failed", "Tool batch lease expired.")
                # Preserve exact provider tool ids, argument strings, content AND reasoning.
                # Only this private same-turn transcript is used for protocol continuation.
                messages = row["messages"] + [decision.assistant_message]
                for tool, (result, duration_ms) in zip(decision.tools, outcomes, strict=True):
                    activity_id = runs.tool(
                        row["id"],
                        call.id,
                        tool,
                        result,
                        outcome=result.get("status", "completed"),
                        duration_ms=duration_ms,
                    )
                    TutorActivity.tool(
                        connection, row, activity_id, tool, result, duration_ms,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                runs.messages(row["id"], messages)
                runs.applied(call.id)
                self._event(connection, row, "tool_completed")
                return True
            if material_run:
                from leornian.bootstrap.material_goal_coverage import MaterialGoalCoverageWorkflow

                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                MaterialGoalCoverageWorkflow.apply(
                    connection, actor, row["input_ref"], decision.content, call_id=call.id,
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                return False
            delivery = TeachingDelivery.apply(connection, row, call, decision)
            if delivery is not None:
                continuing, accepted = delivery
                if accepted is None:
                    self._event(connection, row, "running")
                    return continuing
                decision = accepted
            if row["policy_version"] == "artifact.v1":
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                job = Artifacts(connection).for_run(row["id"])
                context, _ = TeachingContext.build(
                    connection,
                    actor,
                    Tutor(PgTutorStore(connection)).get(actor, row["scope_id"]),
                    TeachingFocus(**task["focus"]),
                )
                # Use the frozen, currently revalidated material contracts, not model citations.
                materials = Knowledge(connection).current(
                    actor,
                    UUID(context["goal"]["id"]),
                    [SourceRef(**ref) for ref in row["context_refs"]],
                )
                artifact = Artifacts(connection).record(actor, job, decision.content, materials)
                # Full public content also enters the existing teaching/exposure Gate context.
                Tutor(PgTutorStore(connection)).complete(
                    row["input_ref"], artifact.document.model_dump_json()
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                ArtifactWorkflow.event(connection, actor.id, artifact.id, job["id"])
                return False
            if evaluation_run:
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                text = EvaluationWorkflow.apply(
                    connection,
                    actor,
                    Evaluations(connection).for_run(actor, row["id"]),
                    decision.content,
                )
                Tutor(PgTutorStore(connection)).complete(row["input_ref"], text)
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                return False
            if transfer_run:
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                complete = TransferWorkflow.apply(
                    connection,
                    actor,
                    Transfers(connection).for_run(row["id"]),
                    decision.content,
                    call_id=call.id,
                )
                if not complete:
                    runs.applied(call.id)
                    runs.messages(row["id"], [])
                    return True
                Tutor(PgTutorStore(connection)).complete(
                    row["input_ref"], "新情境后继检查已保存。题目由服务端明确分配，不代表掌握度。"
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                return False
            if gate_run:
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                complete = ConceptGate.apply(
                    connection,
                    actor,
                    Gates(connection).for_run(row["id"]),
                    decision.content,
                    call_id=call.id,
                )
                if not complete:
                    runs.applied(call.id)
                    runs.messages(row["id"], [])
                    return True
                Tutor(PgTutorStore(connection)).complete(
                    row["input_ref"],
                    "概念考核独立性检查已保存。开始和评分仍由服务端 Gate 决定。",
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                return False
            if item_run:
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                packs = Packs(connection)
                stage = packs.stage(row["id"])
                pack = packs.row(actor, stage["pack_id"], lock=True)
                next_role = ItemSupply.apply(connection, actor, pack, stage, decision.content)
                Tutor(PgTutorStore(connection)).complete(
                    row["input_ref"],
                    "题包阶段 " + stage["role"] + " 的回执已保存。发布、评分和学习完成是独立动作。",
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                if next_role == "qualify":
                    if pack["kind"] == "python_io":
                        PythonWorkflow.qualify(connection, actor, pack, row["session_digest"])
                    else:
                        from leornian.bootstrap.program_execution import ProgramWorkflow

                        ProgramWorkflow.qualify(connection, actor, pack, row["session_digest"])
                elif next_role:
                    ItemSupply.schedule(
                        connection, actor, row["scope_id"], row["session_digest"], pack, next_role
                    )
                ItemSupply.event(connection, actor.id, pack["id"])
                return False
            if lesson_run:
                try:
                    document = LessonDocument.model_validate_json(decision.content, strict=True)
                except (ValueError, TypeError):
                    raise ModelProtocolError("invalid_lesson_output") from None
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                tutor = Tutor(PgTutorStore(connection))
                conversation = tutor.get(actor, row["scope_id"])
                turn = tutor.get_turn(conversation.id, row["input_ref"])
                lessons = Lessons(connection)
                request = lessons.get_request(actor, turn.lesson_request_id)
                materials = Knowledge(connection).current(
                    actor,
                    conversation.goal_id,
                    [SourceRef(**ref) for ref in row["context_refs"]],
                )
                citations = manifest_citations(
                    task["context_manifest"], "lesson"
                ) if task else []
                read_citations_in(connection, actor, conversation.goal_id, citations)
                lesson = lessons.record(
                    actor, request, row["id"], document, materials, citations
                )
                Events(connection).append(
                    actor.id,
                    "learning.lesson_document_created",
                    lesson.id,
                    EventPayload(
                        goal_id=conversation.goal_id,
                        plan_id=lesson.plan_id,
                        plan_revision=lesson.plan_revision,
                        lesson_id=lesson.id,
                        run_id=row["id"],
                    ),
                )
                tutor.complete(
                    turn.id,
                    f"{document.title}\n课时正文已保存，引用对应计划版本 "
                    f"{lesson.plan_revision}；示例代码未运行，未判定学习完成。",
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                return False
            if planning:
                discussion = bool(task and task["context_manifest"].get("route_discussion") == 1)
                if discussion:
                    from leornian.bootstrap.material_consumers import consumer_material_required_in
                    from leornian.bootstrap.planning_materials import PlanningMaterials
                    from leornian.bootstrap.route_discussion import (
                        RouteDiscussion,
                        RouteDiscussionReply,
                    )
                    from leornian.modules.tutor.contracts import PlanningState
                    from leornian.modules.tutor.route_requirements import RouteRequirements

                    reply = RouteDiscussionReply.model_validate_json(decision.content, strict=True)
                    if "route_requirements" in task["context_manifest"]:
                        RouteRequirements(connection).accept(
                            row["scope_id"], row["input_ref"],
                            task["context_manifest"]["route_requirements"],
                            reply.requirement_updates,
                        )
                    actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                    tutor = Tutor(PgTutorStore(connection))
                    conversation = tutor.get(actor, row["scope_id"])
                    turn = tutor.get_turn(conversation.id, row["input_ref"])
                    saved = RouteRequirements(connection).get(conversation.id)
                    previous_state = turn.planning_state or next((
                        item.planning_state
                        for item in reversed(PgTutorStore(connection).turns(conversation.id))
                        if item.id != turn.id and item.planning_state
                    ), None)
                    requested = turn.planning_requested or reply.request_plan
                    complete_material_goal = (
                        PlanningMaterials.complete_objective_in(connection, conversation.id)
                        if requested else None
                    )
                    state = PlanningState(
                        requirements_revision=saved["revision"] if saved else 1,
                        information_complete=reply.ready_for_route or (
                            bool(previous_state and previous_state.information_complete)
                            and turn.planning_requested
                        ),
                        missing_information=reply.missing_information,
                        plan_requested=requested,
                        start_action=bool(
                            turn.planning_state and turn.planning_state.start_action
                        ),
                        material_goal=complete_material_goal or (
                            previous_state.material_goal if previous_state
                            and reply.rag_intent.action != "revise" else None
                        ) or reply.rag_intent.goal or (
                            (saved or {}).get("learner_stated", {}).get("goal", {}).get("value")
                        ),
                        material_topics=[] if complete_material_goal else list(dict.fromkeys([
                            *(
                                previous_state.material_topics
                                if previous_state and reply.rag_intent.action != "revise" else []
                            ),
                            *reply.rag_intent.topics,
                        ])),
                        material_gaps=reply.material_gaps,
                    )
                    PgTutorStore(connection).planning_state(turn.id, state)
                    turn = tutor.get_turn(conversation.id, turn.id)
                    demand = PlanningMaterials.apply_in(
                        connection, actor, conversation, turn, reply, row["session_digest"],
                        previous=self._material_demand(
                            connection, actor, turn.id, "planning",
                        ),
                        model_first=task["context_manifest"].get("planning_policy")
                        == "model-first.v1",
                    )
                    if requested and demand and (
                        PlanningMaterials.blocks_drafting(turn, task["context_manifest"])
                        and consumer_material_required_in(connection, actor, demand)
                    ):
                        try:
                            if PlanningMaterials.is_batch(demand):
                                selection = PlanningMaterials.ready_in(
                                    connection, actor, row["session_digest"], demand,
                                )
                                if selection and task["context_manifest"].get(
                                    "material_evidence_selection_id"
                                ) != str(selection.id):
                                    raise BusinessError(
                                        "material_pending", "route_context_refresh_required",
                                    )
                            else:
                                from leornian.bootstrap.material_consumers import (
                                    ensure_consumer_material_in,
                                )

                                ensure_consumer_material_in(
                                    connection, actor, row["session_digest"], demand,
                                )
                        except BusinessError as error:
                            if error.code != "material_pending":
                                raise
                            Deliveries(connection).await_route_materials(
                                task["id"], demand, route_draft=reply.route,
                            )
                            runs.applied(call.id)
                            if error.message == "route_context_refresh_required":
                                TutorActivity.material_wait(connection, row, demand.id)
                                runs.messages(row["id"], [])
                                self._finish(connection, row, "failed", "material_pending")
                                Deliveries(connection).material_ready(demand.id)
                            else:
                                self._planning_wait(connection, actor, row, task, demand)
                            return False
                    if reply.route is None or reply.material_gaps:
                        if requested:
                            if reply.material_gaps and previous_state and set(
                                previous_state.material_gaps,
                            ) == set(
                                reply.material_gaps,
                            ):
                                runs.applied(call.id)
                                self._planning_blocked(
                                    connection, row, task, "planning_evidence_gap",
                                    "补充检索后仍缺少以下主题的有效依据："
                                    + "、".join(reply.material_gaps)
                                    + "。请补充资料或检查已授权的来源，修复前不会重复调用。",
                                )
                                return False
                            Deliveries(connection).await_route_materials(
                                task["id"], demand, route_draft=reply.route,
                            )
                            runs.messages(row["id"], [])
                            runs.applied(call.id)
                            self._finish(connection, row, "failed", "material_pending")
                            Deliveries(connection).continue_route_discussion(task["id"])
                            return False
                        Tutor(PgTutorStore(connection)).complete(
                            row["input_ref"], RouteDiscussion.present(reply)
                        )
                        runs.applied(call.id)
                        self._finish(connection, row, "succeeded")
                        return False
                    decision = decision.model_copy(
                        update={"content": reply.route.model_dump_json()}
                    )
                try:
                    document = PlanDocument.model_validate_json(decision.content, strict=True)
                    from leornian.modules.execution.environments import Environments

                    Environments.route_requirements(
                        document.environment_recipes, document.environment_dependencies,
                    )
                except BusinessError as error:
                    raise ModelProtocolError("invalid_plan_environment") from error
                except (ValueError, TypeError):
                    raise ModelProtocolError("invalid_plan_output") from None
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                tutor = Tutor(PgTutorStore(connection))
                conversation = tutor.get(actor, row["scope_id"])
                turn = tutor.get_turn(conversation.id, row["input_ref"])
                materials = Knowledge(connection).current(
                    actor,
                    conversation.goal_id,
                    [SourceRef(**ref) for ref in row["context_refs"]],
                )
                citations = manifest_citations(
                    task["context_manifest"], "planning"
                ) if task else []
                read_citations_in(connection, actor, conversation.goal_id, citations)
                if not materials and not citations and not document.assumptions and not discussion:
                    raise ModelProtocolError("invalid_plan_output")
                model_first = bool(
                    task and task["context_manifest"].get("planning_policy") == "model-first.v1"
                )
                if document.curriculum is not None or (citations and discussion):
                    from leornian.bootstrap.planning_materials import PlanningMaterials

                    try:
                        PlanningMaterials.validate_route_in(
                            connection, actor, conversation.goal_id, document,
                            materials_required=not model_first,
                        )
                    except BusinessError as error:
                        if error.code != "invalid_plan_output":
                            raise
                        raise ModelProtocolError("invalid_plan_output") from error
                plan = Plans(connection).record(
                    actor,
                    conversation.goal_id,
                    turn.plan_base_revision,
                    row["id"],
                    document,
                    materials,
                    citations,
                    require_evidence=not model_first,
                )
                Events(connection).append(
                    actor.id,
                    "learning.dynamic_plan_drafted",
                    plan.id,
                    EventPayload(
                        goal_id=conversation.goal_id,
                        plan_id=plan.id,
                        plan_revision=plan.latest.revision,
                        run_id=row["id"],
                    ),
                )
                tutor.complete(
                    turn.id,
                    RouteDiscussion.present(reply) if discussion else (
                        f"{document.title}\n{document.summary}\n"
                        f"计划草案 v{plan.latest.revision} 已保存，等待你确认；"
                        "未生成配套课时或题包。"
                    ),
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                return False
            if runs.tool_count(row["id"]) == 0 and delivery is None:
                raise ModelProtocolError("required_tool_missing")
            from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

            actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
            text = LearningArtifactWorkflow.accept_reply_in(
                connection, actor, row, task, decision.content
            )
            from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow

            TeachingSessionWorkflow.publish_in(connection, actor, row["input_ref"], text)
            Tutor(PgTutorStore(connection)).complete(row["input_ref"], text)
            runs.applied(call.id)
            self._finish(connection, row, "succeeded")
            return False
