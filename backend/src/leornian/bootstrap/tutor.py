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
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.application import Assessment
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.catalog import published_item
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
from leornian.modules.tutor.contracts import Conversation, PlanningInput, TurnInput
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
        Runs(connection).finish(row["id"], status, code)
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
                self._finish(connection, row, "failed", "source_not_current")
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
        return row

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
            identity = Identity(PgIdentityStore(connection, lock_session=True))
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
                return TurnAccepted(run_id=run.id, turn_id=turn.id)
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
            self._event(connection, runs.lock(run.id), "queued")
            return TurnAccepted(run_id=run.id, turn_id=turn.id)

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
            identity = Identity(PgIdentityStore(connection, lock_session=True))
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
                run = runs.for_turn(actor.id, turn.id)
                return TurnAccepted(run_id=run.id, turn_id=turn.id)
            if runs.active(conversation_id):
                raise BusinessError(
                    "run_active", "Finish or cancel the current teaching turn first."
                )
            ChatCompletionsGateway(self.settings).require_ready()
            if purpose == "planning":
                Plans(connection).require_base(actor, conversation.goal_id, base_revision)
            run = runs.create(
                actor.id,
                conversation_id,
                turn.id,
                identity.digest(token),
                "planner.v1" if purpose == "planning" else "tutor.v1",
            )
            row = runs.lock(run.id)
            self._event(connection, row, "queued")
            return TurnAccepted(run_id=run.id, turn_id=turn.id)

    def plan(self, token: str, plan_id: UUID) -> LearningPlan:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Plans(connection).get(actor, plan_id)

    def plan_history(self, token: str, plan_id: UUID) -> list[PlanRevision]:
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Plans(connection).history(actor, plan_id)

    def confirm_plan(self, token: str, plan_id: UUID, revision: int) -> LearningPlan:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
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

    def cancel(self, token: str, run_id: UUID) -> Run:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            runs = Runs(connection)
            runs.get(actor.id, run_id)
            row = runs.lock(run_id)
            if row["status"] not in {"succeeded", "failed", "cancelled"}:
                runs.cancel(run_id)
                runs.mark_unknown(run_id)
                self._finish(connection, row, "cancelled")
            return runs.get(actor.id, run_id)

    def resume(self, token: str, run_id: UUID) -> Run:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            runs = Runs(connection)
            runs.get(actor.id, run_id)
            row = runs.lock(run_id)
            call = runs.latest(run_id)
            if not row or row["status"] != "blocked_unknown" or row["cancel_requested"]:
                raise BusinessError("resume_not_allowed", "This run cannot be resumed.")
            if not call or call.status != "result_recorded" or call.applied:
                raise BusinessError("unknown_unresolved", "No recorded result supports resuming.")
            # A new session may authorize consuming a late result, never resending its call.
            connection.execute(
                "UPDATE runtime.runs SET session_digest = %s WHERE id = %s",
                (Identity.digest(token), run_id),
            )
            self._event(connection, row, "queued")
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
                    role = tutor.role(context, tutor.turns(conversation.id), row["input_ref"])
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

    def prepare(self, lease: Lease, endpoint: str, request: dict) -> StoredCall | None:
        with self.database.transaction() as connection:
            if self._current(connection, lease) is None:
                return None
            return Runs(connection).prepare(lease.run_id, endpoint, request)

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
            validate_tools(decision, () if planning or lesson_run else ("learning_get_context",))
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
            if decision.tools:
                if runs.tool_count(row["id"]) + len(decision.tools) > 2:
                    raise ModelProtocolError("tool_limit")
                actor = Identity(PgIdentityStore(connection)).get_actor(row["actor_id"])
                conversation = Tutor(PgTutorStore(connection)).get(actor, row["scope_id"])
                materials = Knowledge(connection).current(
                    actor,
                    conversation.goal_id,
                    [SourceRef(**ref) for ref in row["context_refs"]],
                )
                result = self._learning_context(connection, actor, conversation.goal_id, materials)
                messages = row["messages"] + [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool.id,
                                "type": "function",
                                "function": {
                                    "name": tool.name,
                                    "arguments": json.dumps(tool.arguments),
                                },
                            }
                            for tool in decision.tools
                        ],
                    }
                ]
                for tool in decision.tools:
                    runs.tool(row["id"], call, tool, result)
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
            if runs.tool_count(row["id"]) == 0:
                raise ModelProtocolError("required_tool_missing")
            Tutor(PgTutorStore(connection)).complete(row["input_ref"], decision.content.strip())
            runs.applied(call.id)
            self._finish(connection, row, "succeeded")
            return False
