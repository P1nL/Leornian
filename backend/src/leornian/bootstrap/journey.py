from uuid import UUID

from leornian.bootstrap.example_runs import ExampleRuns
from leornian.bootstrap.program_execution import ProgramWorkflow
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.application import Assessment
from leornian.modules.assessment.contracts import Attempt, Submission
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import ExecutionClaim, ProgramExecutionClaim, RunnerReport
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import Actor
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.catalog import published_item
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.journey import Journey
from leornian.modules.learning.journey_contracts import Lesson, Track
from leornian.modules.learning.review_contracts import ReviewCard, ReviewInput, ReviewStatus
from leornian.modules.learning.reviews import Reviews
from leornian.platform.database import Database
from leornian.shared_kernel.errors import BusinessError


class JourneyWorkflow:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _event(connection, actor_id, event_type, track_id, attempt_id=None):
        Events(connection).append(
            actor_id,
            event_type,
            track_id,
            EventPayload(track_id=track_id, attempt_id=attempt_id),
        )

    def draft(self, token: str, goal_id: UUID) -> Track:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
            track, created = Journey(connection).draft(actor, goal_id)
            if created:
                self._event(connection, actor.id, "learning.plan_drafted", track.id)
            return track

    def confirm(self, token: str, track_id: UUID, revision: int) -> Track:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            track, changed = Journey(connection).confirm(actor, track_id, revision)
            if changed:
                self._event(connection, actor.id, "learning.plan_confirmed", track.id)
            return track

    def lesson(self, token: str, track_id: UUID):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            track = Journey(connection).get(actor, track_id)
            if track.status == "draft":
                raise BusinessError(
                    "precondition_failed", "Confirm the current plan before reading."
                )
            return Lesson(), published_item(track.course_version).exercise

    def submit(self, token: str, track_id: UUID, key: str, data: Submission) -> Attempt:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            track = Journey(connection).get(actor, track_id, lock=True)
            if track.status == "draft":
                raise BusinessError("precondition_failed", "Confirm the plan before submitting.")
            attempt, created = Assessment(connection).submit(
                actor,
                track_id,
                track.revision,
                key,
                data.code,
            )
            if created:
                Execution(connection).enqueue(actor, attempt.id, Identity.digest(token))
                self._event(connection, actor.id, "assessment.queued", track.id, attempt.id)
            return attempt

    def attempt(self, token: str, attempt_id: UUID) -> Attempt:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Assessment(connection).get(actor, attempt_id)

    def claim(
        self, runner_id: str, program_environments=(), *, example_terminal=False,
    ) -> ExecutionClaim | ProgramExecutionClaim | None:
        with self.database.transaction() as connection:
            work = Execution(connection).claim(
                runner_id, program_environments, example_terminal=example_terminal,
            )
            return self.claim_in(connection, work)

    @staticmethod
    def claim_in(connection, work) -> ExecutionClaim | ProgramExecutionClaim | None:
        if work is None:
            return None
        if work.get("example_input"):
            return ExampleRuns.claim_in(connection, work)
        if work["python_input_ref"]:
            return PythonWorkflow.claim_in(connection, work)
        if work["program_input_ref"]:
            return ProgramWorkflow.claim_in(connection, work)
        assessment = Assessment(connection)
        try:
            with connection.transaction():
                actor = Identity(
                    PgIdentityStore(connection, lock_session=True)
                ).authenticate_digest(work["session_digest"] or "")
                if actor.id != work["actor_id"]:
                    raise BusinessError("unauthorized", "Execution owner changed.")
                source = assessment.execution_input(actor, work["input_ref"])
                track = Journey(connection).get(actor, source["track_id"])
                if track.status == "draft" or track.revision != source["course_revision"]:
                    raise BusinessError("stale_version", "Plan does not match this attempt.")
        except BusinessError as error:
            Execution(connection).abandon(work["id"], error.code)
            assessment.fail(work["input_ref"], "执行前授权已失效。")
            attempt = assessment.get(Actor(id=work["actor_id"], display_name=""), work["input_ref"])
            JourneyWorkflow._event(
                connection, work["actor_id"], "assessment.completed", attempt.track_id, attempt.id
            )
            return None
        item = published_item(source["item_version"])
        return ExecutionClaim(
            job_id=work["id"],
            claim_token=work["claim_token"],
            code=source["code"],
            inputs=item.execution_inputs,
        )

    def report(self, job_id: UUID, report: RunnerReport) -> None:
        with self.database.transaction() as connection:
            # The immutable reference permits consistent identity -> plan -> execution locking.
            existing = Execution(connection).reference(job_id)
            if existing["example_input"]:
                execution = Execution(connection)
                try:
                    with connection.transaction():
                        _, practice = ExampleRuns.authorize(connection, existing)
                        if practice and not existing["example_input"].get("practice_only"):
                            execution.detach_example(job_id)
                except BusinessError as error:
                    execution.abandon(job_id, error.code)
                execution.report(job_id, report)
                return
            if existing["python_input_ref"]:
                return PythonWorkflow.report_in(connection, existing, job_id, report)
            if existing["program_input_ref"]:
                return ProgramWorkflow.report_in(connection, existing, job_id, report)
            owner = Actor(id=existing["actor_id"], display_name="")
            current = True
            try:
                actor = Identity(
                    PgIdentityStore(connection, lock_session=True)
                ).authenticate_digest(
                    existing["session_digest"] or "",
                )
                current = actor.id == owner.id
            except BusinessError:
                current = False
            assessment = Assessment(connection)
            source = assessment.execution_input(owner, existing["input_ref"])
            track = Journey(connection).get(owner, source["track_id"], lock=True)
            work, first, timely = Execution(connection).report(job_id, report)
            if not first:
                return
            applicable = (
                current
                and timely
                and track.status != "draft"
                and track.revision == source["course_revision"]
            )
            result = assessment.complete(work["input_ref"], report.cases) if applicable else None
            changed = applicable or assessment.fail(
                work["input_ref"], "回执已保存，但当前授权、计划或执行租约不再有效。"
            )
            if changed:
                self._event(
                    connection,
                    owner.id,
                    "assessment.completed",
                    source["track_id"],
                    work["input_ref"],
                )
            if (
                result
                and result.passed
                and Journey(connection).apply_assessment(
                    owner,
                    source["track_id"],
                    work["input_ref"],
                    source["course_revision"],
                )
            ):
                self._event(
                    connection,
                    owner.id,
                    "learning.lesson_completed",
                    source["track_id"],
                    work["input_ref"],
                )
                if Reviews(connection).schedule_completed(owner, source["track_id"]):
                    self._event(
                        connection, owner.id, "learning.review_scheduled", source["track_id"]
                    )

    def verify_execution(self, job_id, data):
        with self.database.transaction() as connection:
            try:
                work = Execution(connection).current_claim(job_id, data.claim_token)
                if (work["example_terminal"] or {}).get("stopping"):
                    return {"allowed": False}
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True),
                ).authenticate_digest(work["session_digest"] or "")
                if actor.id != work["actor_id"]:
                    return {"allowed": False}
                if work["example_input"]:
                    ExampleRuns.authorize(connection, work)
                elif work["program_input_ref"]:
                    source = ProgramAssessment(connection).row(actor, work["program_input_ref"])
                    ProgramWorkflow.current(connection, actor, source)
                elif work["python_input_ref"]:
                    source = PythonAssessment(connection).row(actor, work["python_input_ref"])
                    PythonWorkflow.current(connection, actor, source)
                else:
                    source = Assessment(connection).execution_input(actor, work["input_ref"])
                    track = Journey(connection).get(actor, source["track_id"])
                    if track.status == "draft" or track.revision != source["course_revision"]:
                        return {"allowed": False}
                Execution(connection).current_claim(job_id, data.claim_token)
            except BusinessError:
                return {"allowed": False}
            return {"allowed": True}

    def review(self, token: str, card_id: UUID, key: str, data: ReviewInput) -> ReviewCard:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            card, changed = Reviews(connection).respond(actor, card_id, key, data)
            if changed:
                Events(connection).append(
                    actor.id, "learning.review_recorded", card.track_id or card.id,
                    EventPayload(track_id=card.track_id),
                )
            return card

    def review_status(self, token: str, card_id: UUID, data: ReviewStatus) -> ReviewCard:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            card, changed = Reviews(connection).change_status(actor, card_id, data)
            if changed:
                Events(connection).append(
                    actor.id, "learning.review_status_changed", card.track_id or card.id,
                    EventPayload(track_id=card.track_id),
                )
            return card

    def expire_executions(self) -> int:
        with self.database.transaction() as connection:
            execution = Execution(connection)
            examples = execution.expire_examples()
            rows = execution.expired()
            for row in rows:
                execution.abandon(row["id"], "runner_lease_expired")
                Assessment(connection).fail(
                    row["input_ref"], "Runner 未在租约内返回结果；未自动重跑。"
                )
                actor = Actor(id=row["actor_id"], display_name="")
                attempt = Assessment(connection).get(actor, row["input_ref"])
                self._event(
                    connection, actor.id, "assessment.completed", attempt.track_id, attempt.id
                )
        return (
            len(rows) + examples + PythonWorkflow(self.database).expire_executions()
            + ProgramWorkflow(self.database).expire_executions()
        )
