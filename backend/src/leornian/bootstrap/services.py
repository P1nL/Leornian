from uuid import UUID

from leornian.agent_runtime.repository import Runs
from leornian.delivery.contracts import ConversationTurns, EventPayload, PublicEvent, Snapshot
from leornian.delivery.events import Events
from leornian.modules.assessment.application import Assessment
from leornian.modules.assessment.choices import Choices
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.assessment.remediation import Remediations
from leornian.modules.assessment.transfers import Transfers
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import Session
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.demands import Demands
from leornian.modules.item_bank.supply import Packs
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.learning.application import Learning
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.journey import Journey
from leornian.modules.learning.lessons import Lessons
from leornian.modules.learning.planning import Plans
from leornian.modules.learning.progress import Progress
from leornian.modules.learning.reviews import Reviews
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.artifacts import Artifacts
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.evaluations import Evaluations
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.modules.tutor.teaching_sessions import TeachingSessions
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

    def refresh_session(self, token: str) -> Session:
        with self.database.transaction() as connection:
            return Identity(PgIdentityStore(connection)).renew_local_session(token)

    def end_session(self, token: str) -> None:
        with self.database.transaction() as connection:
            Identity(PgIdentityStore(connection)).revoke_local_session(token)

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

    def goal_request(self, token: str, key: str) -> Accepted:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            request = Learning(PgGoalStore(connection)).goal_request(actor, key)
            job = Jobs(connection).for_request(actor, request.id)
            return Accepted(job_id=job.id)

    def rename_goal(self, token, goal_id, title, motivation=None):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            goal = Learning(PgGoalStore(connection)).rename_goal(actor, goal_id, title, motivation)
            Events(connection).append(
                actor.id, "goal.updated", goal.id, EventPayload(goal_id=goal.id),
            )
            return goal

    def delete_goal(self, token, goal_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            conversations = Tutor(PgTutorStore(connection)).list_conversations(actor)
            if any(item.goal_id == goal_id and Runs(connection).active(item.id)
                   for item in conversations):
                raise BusinessError("run_active", "先结束或取消当前教学，再删除学习计划。")
            Learning(PgGoalStore(connection)).delete_goal(actor, goal_id)
            Events(connection).append(
                actor.id, "goal.deleted", goal_id, EventPayload(goal_id=goal_id),
            )
            return {"deleted": True}

    def snapshot(self, token: str) -> Snapshot:
        # State and cursor must describe the same database snapshot.
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            tutor = Tutor(PgTutorStore(connection))
            conversations = tutor.list_conversations(actor)
            turns = [
                ConversationTurns(conversation_id=item.id, turns=tutor.turns(item.id))
                for item in conversations
            ]
            thinking = Events(connection).thinking(
                actor.id, [turn.id for page in turns for turn in page.turns],
            )
            steps = Events(connection).thinking_steps(
                actor.id, [turn.id for page in turns for turn in page.turns],
            )
            turns = [
                page.model_copy(update={"turns": [
                    Events(connection).attach_reply_thinking(
                        actor.id, turn, thinking.get(str(turn.id)), steps.get(str(turn.id), []),
                    )
                    for turn in page.turns
                ]})
                for page in turns
            ]
            return Snapshot(
                actor=actor,
                goals=Learning(PgGoalStore(connection)).list_goals(actor),
                jobs=Jobs(connection).list(actor),
                events=Events(connection).recent(actor),
                cursor=Events(connection).cursor(actor),
                conversations=conversations,
                teaching_sessions=TeachingSessions(connection).list(actor),
                teaching_branches=TeachingSessions(connection).branches(actor, limit=100),
                turns=turns,
                runs=Runs(connection).list(actor.id),
                delivery_tasks=Deliveries(connection).page(actor, limit=100),
                artifacts=Artifacts(connection).list(actor),
                learning_artifacts=LearningArtifacts(connection).list(actor),
                artifact_jobs=Artifacts(connection).jobs(actor),
                tool_activities=Runs(connection).activities(actor.id),
                tracks=Journey(connection).list(actor),
                attempts=Assessment(connection).list(actor),
                sources=Knowledge(connection).list(actor),
                reviews=Reviews(connection).list(actor),
                plans=Plans(connection).list(actor),
                lessons=Lessons(connection).list(actor),
                packs=Packs(connection).list(actor),
                choice_results=Choices(connection).list(actor),
                remediations=Remediations(connection).list(actor),
                gates=Gates(connection).list(actor),
                node_progress=Progress(connection).list(actor),
                transfers=Transfers(connection).list(actor),
                supply_demands=Demands(connection).list(actor),
                evaluations=Evaluations(connection).list(actor),
                python_attempts=PythonAssessment(connection).list(actor),
                program_attempts=ProgramAssessment(connection).list(actor),
                execution_progress=Progress(connection).python_list(actor),
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
