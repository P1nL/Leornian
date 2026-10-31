from uuid import UUID

from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.application import Assessment
from leornian.modules.assessment.contracts import Attempt, Submission
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import ExecutionClaim, RunnerReport
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

    def claim(self, runner_id: str) -> ExecutionClaim | None:
        with self.database.transaction() as connection:
            work = Execution(connection).claim(runner_id)
            if work is None:
                return None
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
                attempt = assessment.get(
                    Actor(id=work["actor_id"], display_name=""), work["input_ref"]
                )
                self._event(
                    connection,
                    work["actor_id"],
                    "assessment.completed",
                    attempt.track_id,
                    attempt.id,
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

    def review(self, token: str, card_id: UUID, key: str, data: ReviewInput) -> ReviewCard:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            card, changed = Reviews(connection).respond(actor, card_id, key, data)
            if changed:
                self._event(connection, actor.id, "learning.review_recorded", card.track_id)
            return card

    def review_status(self, token: str, card_id: UUID, data: ReviewStatus) -> ReviewCard:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            card, changed = Reviews(connection).change_status(actor, card_id, data)
            if changed:
                self._event(connection, actor.id, "learning.review_status_changed", card.track_id)
            return card

    def expire_executions(self) -> int:
        with self.database.transaction() as connection:
            execution = Execution(connection)
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
            return len(rows)
