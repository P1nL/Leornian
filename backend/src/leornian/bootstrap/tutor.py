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
from leornian.agent_runtime.tools import TEACHING_TOOLS, allowed
from leornian.bootstrap.artifacts import ArtifactWorkflow
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.evaluation import EvaluationWorkflow
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.bootstrap.teaching_context import TeachingContext
from leornian.bootstrap.teaching_delivery import TeachingDelivery
from leornian.bootstrap.tools import ToolRouter
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.application import Assessment
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.transfers import Transfers
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
from leornian.shared_kernel.errors import BusinessError


class TutorWorkflow:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    @staticmethod
    def _event(connection, row: dict, status: str, code: str | None = None) -> None:
        Events(connection).append(
            row["actor_id"],
            "tutor." + status,
            row["id"],
            EventPayload(
                run_id=row["id"],
                conversation_id=row["scope_id"],
                turn_id=row["input_ref"],
                error_code=code,
            ),
        )

    def _finish(self, connection, row: dict, status: str, code: str | None = None) -> None:
        delivery = Deliveries(connection).for_run(row["id"])
        if delivery:
            if status == "cancelled":
                Deliveries(connection).state(delivery["id"], "cancelled")
            elif status == "blocked_unknown":
                Deliveries(connection).state(delivery["id"], "blocked_unknown")
            elif status == "failed" and TeachingDelivery.failure(connection, row, code):
                self._event(connection, row, "queued", code)
                return
        if status == "cancelled":
            Runs(connection).mark_unknown(row["id"])
        Runs(connection).finish(row["id"], status, code)
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
        self._event(connection, row, status, code)

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
                Gates(connection).require_no_exam(actor)
                frozen_focus = TeachingFocus(**delivery["focus"])
                if delivery["context_manifest"].get("lesson_ids"):
                    frozen_focus = frozen_focus.model_copy(
                        update={"lesson_id": UUID(delivery["context_manifest"]["lesson_ids"][0])}
                    )
                _, current_manifest = TeachingContext.build(
                    connection,
                    actor,
                    Tutor(PgTutorStore(connection)).get(actor, row["scope_id"]),
                    frozen_focus,
                )
                if delivery["author_messages"] and (
                    current_manifest["plan_binding"]
                    != delivery["context_manifest"].get("plan_binding")
                ):
                    raise BusinessError("stale_version", "Delivery plan binding changed.")
            except BusinessError as error:
                self._finish(connection, row, "failed", error.code)
                return None
        return row

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

    def submit(self, token: str, conversation_id: UUID, key: str, data: TurnInput) -> TurnAccepted:
        return self._submit(token, conversation_id, key, data, "teaching", None)

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
            plan = Plans(connection).get(actor, plan_id)
            tutor = Tutor(PgTutorStore(connection))
            conversation = tutor.conversation(actor, plan.goal_id)
            tutor.get(actor, conversation.id, lock=True)
            lessons = Lessons(connection)
            request, _created = lessons.request(actor, plan_id, key, data)
            turn, created = tutor.request_turn(
                conversation.id,
                key,
                data.instruction,
                "lesson",
                None,
                request.id,
            )
            runs = Runs(connection)
            if not created:
                run = runs.for_turn(actor.id, turn.id)
                task = Deliveries(connection).for_run(run.id)
                return TurnAccepted(
                    run_id=run.id, turn_id=turn.id, delivery_task_id=task["id"] if task else None
                )
            Gates(connection).require_no_exam(actor)
            if runs.active(conversation.id):
                raise BusinessError("run_active", "Finish the active conversation run first.")
            ChatCompletionsGateway(self.settings).require_ready()
            node = lessons.current(actor, request)
            Knowledge(connection).current(actor, plan.goal_id, node.source_refs)
            lessons.current(actor, request, lock=True)
            run = runs.create(
                actor.id, conversation.id, turn.id, identity.digest(token), "lesson.v1"
            )
            runs.bind_sources(run.id, [ref.model_dump(mode="json") for ref in node.source_refs])
            task = None
            if self.settings.delivery_enabled:
                focus = TeachingFocus(
                    kind="node",
                    plan_id=plan_id,
                    expected_plan_revision=request.plan_revision,
                    node_key=request.node_key,
                )
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
            tutor = Tutor(PgTutorStore(connection))
            conversation = tutor.get(actor, conversation_id, lock=True)
            turn, created = tutor.request_turn(
                conversation_id,
                key,
                data.text,
                purpose,
                base_revision,
            )
            runs = Runs(connection)
            if not created:
                if turn.context_focus != data.focus:
                    raise BusinessError("idempotency_conflict", "Turn focus changed.")
                run = runs.for_turn(actor.id, turn.id)
                task = Deliveries(connection).for_run(run.id)
                return TurnAccepted(
                    run_id=run.id, turn_id=turn.id, delivery_task_id=task["id"] if task else None
                )
            Gates(connection).require_no_exam(actor)
            if runs.active(conversation_id):
                raise BusinessError(
                    "run_active", "Finish or cancel the current teaching turn first."
                )
            ChatCompletionsGateway(self.settings).require_ready()
            if purpose == "planning":
                Plans(connection).require_base(actor, conversation.goal_id, base_revision)
            task = None
            if self.settings.delivery_enabled:
                TeachingContext.build(connection, actor, conversation, data.focus)
                PgTutorStore(connection).bind_focus(turn.id, data.focus)
            run = runs.create(
                actor.id,
                conversation_id,
                turn.id,
                identity.digest(token),
                "planner.v1" if purpose == "planning" else "tutor.v1",
                tools=TEACHING_TOOLS
                if purpose == "teaching" and self.settings.delivery_enabled
                else None,
            )
            if self.settings.delivery_enabled:
                task = Deliveries(connection).create(
                    actor, run.id, purpose, data.focus.model_dump(mode="json")
                )
            row = runs.lock(run.id)
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

    def confirm_plan(self, token: str, plan_id: UUID, revision: int) -> LearningPlan:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Gates(connection).require_no_exam(actor)
            plans = Plans(connection)
            plan = plans.get(actor, plan_id)
            if plan.latest.revision != revision:
                raise BusinessError("stale_version", "Only the current draft may be confirmed.")
            if plan.active and plan.active.revision == revision:
                return plan
            Knowledge(connection).current(
                actor,
                plan.goal_id,
                [
                    SourceRef(source_id=item.source_id, revision=item.revision)
                    for item in plan.latest.sources
                ],
            )
            plan, changed = plans.confirm(actor, plan_id, revision)
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
            if task["cancel_requested"] or task["status"] not in {
                "waiting_input",
                "waiting_dependency",
                "waiting_config",
                "blocked_unknown",
            }:
                raise BusinessError("resume_not_allowed", "Delivery is not awaiting recovery.")
            if task["status"] == "waiting_input" and not additional_instruction.strip():
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
            if call and call.status == "failed_known":
                runs.applied(call.id)
            if task["status"] == "blocked_unknown" and (
                not call or call.status != "result_recorded" or call.applied
            ):
                raise BusinessError(
                    "unknown_unresolved", "No complete receipt authorizes recovery."
                )
            if additional_instruction:
                if task["status"] == "blocked_unknown":
                    raise BusinessError(
                        "resume_not_allowed", "Consume the receipt before changing input."
                    )
                messages = task["author_messages"] + [
                    {"role": "user", "content": additional_instruction}
                ]
                connection.execute(
                    "UPDATE tutor.delivery_tasks SET author_messages=%s,phase='author',issues='[]' "
                    "WHERE id=%s",
                    (Jsonb(messages), task_id),
                )
            connection.execute(
                "UPDATE runtime.runs SET session_digest=%s WHERE id=%s",
                (digest, row["id"]),
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
            return PgTutorStore(connection).page(conversation_id, before, limit)

    def cancel(self, token: str, run_id: UUID) -> Run:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
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
                self._finish(connection, row, "cancelled")
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

    def context(self, lease: Lease) -> RoleSpec | None:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            if row is None:
                return None
            task = Deliveries(connection).for_run(row["id"])
            if task:
                if task["phase"] == "review":
                    return TeachingDelivery.review_role(task)
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                tutor = Tutor(PgTutorStore(connection))
                turn = tutor.get_turn(row["scope_id"], row["input_ref"])
                role = TeachingContext.role(connection, row, tutor, turn, task)
                if not task["author_messages"]:
                    Deliveries(connection).context(task["id"], role.messages, role.context_manifest)
                    Runs(connection).bind_sources(row["id"], role.context_manifest["sources"])
                else:
                    role = role.model_copy(
                        update={
                            "messages": task["author_messages"],
                            "context_manifest": task["context_manifest"],
                        }
                    )
                role = TeachingDelivery.author_role(role, task)
                return role.model_copy(update={"messages": role.messages + row["messages"]})
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
                    role = tutor.lesson_role(context, turn)
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
            return RoleSpec(
                messages=row["messages"],
                policy_version=row["policy_version"],
                allowed_tools=() if structured else ("learning_get_context",),
            )

    def latest(self, lease: Lease) -> StoredCall | None:
        with self.database.transaction() as connection:
            row = self._current(connection, lease)
            return Runs(connection).latest(lease.run_id) if row else None

    def prepare(
        self, lease: Lease, endpoint: str, request: dict, policy=None, manifest=None
    ) -> StoredCall | None:
        with self.database.transaction() as connection:
            if self._current(connection, lease) is None:
                return None
            return Runs(connection).prepare(lease.run_id, endpoint, request, policy, manifest)

    def dispatch(self, lease: Lease, call_id: UUID) -> bool:
        with self.database.transaction() as connection:
            if self._current(connection, lease) is None:
                return False
            return Runs(connection).dispatch(call_id)

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
            planning = row["policy_version"] == "planner.v1"
            lesson_run = row["policy_version"] == "lesson.v1"
            item_run = row["policy_version"].startswith("item_")
            gate_run = row["policy_version"] == "gate_relation.v1"
            transfer_run = row["policy_version"] == "transfer_relation.v1"
            evaluation_run = row["policy_version"] == "evaluation.v1"
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

                def context_result():
                    if task:
                        return TeachingContext.build(
                            connection, actor, conversation, TeachingFocus(**task["focus"])
                        )[0]
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
                outcomes = router.batch(connection, decision.tools)
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
                    runs.tool(
                        row["id"],
                        call,
                        tool,
                        result,
                        outcome=result.get("status", "completed"),
                        duration_ms=duration_ms,
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
                    PythonWorkflow.qualify(connection, actor, pack, row["session_digest"])
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
                lesson = lessons.record(actor, request, row["id"], document, materials)
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
                try:
                    document = PlanDocument.model_validate_json(decision.content, strict=True)
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
                if not materials and not document.assumptions:
                    raise ModelProtocolError("invalid_plan_output")
                plan = Plans(connection).record(
                    actor,
                    conversation.goal_id,
                    turn.plan_base_revision,
                    row["id"],
                    document,
                    materials,
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
                    f"{document.title}\n{document.summary}\n"
                    f"计划草案 v{plan.latest.revision} 已保存，等待你确认；未生成配套课时或题包。",
                )
                runs.applied(call.id)
                self._finish(connection, row, "succeeded")
                return False
            if runs.tool_count(row["id"]) == 0 and delivery is None:
                raise ModelProtocolError("required_tool_missing")
            Tutor(PgTutorStore(connection)).complete(row["input_ref"], decision.content.strip())
            runs.applied(call.id)
            self._finish(connection, row, "succeeded")
            return False
