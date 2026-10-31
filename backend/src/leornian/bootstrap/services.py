from uuid import UUID

from leornian.agent_runtime.repository import Runs
from leornian.delivery.contracts import ConversationTurns, EventPayload, PublicEvent, Snapshot
from leornian.delivery.events import Events
from leornian.modules.assessment.application import Assessment
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import Session
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.learning.application import Learning
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.journey import Journey
from leornian.modules.learning.lessons import Lessons
from leornian.modules.learning.planning import Plans
from leornian.modules.learning.reviews import Reviews
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.platform.database import Database
from leornian.platform.jobs import Accepted, Job, Jobs
from leornian.shared_kernel.errors import BusinessError


class GoalWorkflow:
    """Named cross-module transaction coordinator; adapters are composed only here."""

    def __init__(self, database: Database):
        self.database = database

    def create_session(self, display_name: str) -> Session:
        with self.database.transaction() as connection:
            return Identity(PgIdentityStore(connection)).create_local_session(display_name)

    def submit(self, token: str, key: str, data: GoalInput) -> Accepted:
        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection))
            actor = identity.authenticate(token)
            identity.require_active(actor)
            request = Learning(PgGoalStore(connection)).request_goal(actor, key, data)
            job, created = Jobs(connection).enqueue(actor, request.id)
            if created:
                Events(connection).append(
                    actor.id, "job.queued", job.id, EventPayload(job_id=job.id)
                )
            return Accepted(job_id=job.id)

    def job(self, token: str, job_id: UUID) -> Job:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Jobs(connection).get(actor, job_id)

    def snapshot(self, token: str) -> Snapshot:
        # State and cursor must describe the same database snapshot.
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            tutor = Tutor(PgTutorStore(connection))
            conversations = tutor.list_conversations(actor)
            return Snapshot(
                actor=actor,
                goals=Learning(PgGoalStore(connection)).list_goals(actor),
                jobs=Jobs(connection).list(actor),
                events=Events(connection).recent(actor),
                cursor=Events(connection).cursor(actor),
                conversations=conversations,
                turns=[
                    ConversationTurns(conversation_id=item.id, turns=tutor.turns(item.id))
                    for item in conversations
                ],
                runs=Runs(connection).list(actor.id),
                tracks=Journey(connection).list(actor),
                attempts=Assessment(connection).list(actor),
                sources=Knowledge(connection).list(actor),
                reviews=Reviews(connection).list(actor),
                plans=Plans(connection).list(actor),
                lessons=Lessons(connection).list(actor),
            )

    def events(self, token: str, after: int) -> list[PublicEvent]:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Events(connection).list(actor, after)

    def process_goal(self, event_id: UUID) -> None:
        # Only this deterministic, DB-only operation may be redispatched automatically.
        # Do not reuse it as authorization to repeat model or other external calls.
        with self.database.transaction() as connection:
            jobs = Jobs(connection)
            work = jobs.lock(event_id)
            if work is None or work.status != "queued" or not jobs.consume(event_id):
                return
            try:
                with connection.transaction():
                    actor = Identity(PgIdentityStore(connection)).get_actor(work.actor_id)
                    goal = Learning(PgGoalStore(connection)).create_goal(actor, work.input_ref)
                    jobs.succeed(work.id, goal.id)
                    events = Events(connection)
                    payload = EventPayload(job_id=work.id, goal_id=goal.id)
                    events.append(actor.id, "goal.created", goal.id, payload, causation_id=event_id)
                    events.append(
                        actor.id, "job.succeeded", work.id, payload, causation_id=event_id
                    )
            except BusinessError as error:
                jobs.fail(work.id, error.code)
                Events(connection).append(
                    work.actor_id,
                    "job.failed",
                    work.id,
                    EventPayload(job_id=work.id, error_code=error.code),
                    causation_id=event_id,
                )
