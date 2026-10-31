from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.agent_runtime.contracts import Run
from leornian.modules.assessment.contracts import Attempt
from leornian.modules.identity.contracts import Actor
from leornian.modules.item_bank.contracts import Exercise
from leornian.modules.knowledge.contracts import Source
from leornian.modules.learning.contracts import GeneratedLesson, Goal, LearningPlan
from leornian.modules.learning.journey_contracts import Lesson, Track
from leornian.modules.learning.review_contracts import ReviewCard
from leornian.modules.tutor.contracts import Conversation, Turn
from leornian.platform.jobs import Job
from leornian.shared_kernel.contracts import Contract


class EventPayload(Contract):
    job_id: UUID | None = None
    goal_id: UUID | None = None
    run_id: UUID | None = None
    conversation_id: UUID | None = None
    turn_id: UUID | None = None
    track_id: UUID | None = None
    attempt_id: UUID | None = None
    source_id: UUID | None = None
    error_code: str | None = None
    plan_id: UUID | None = None
    plan_revision: int | None = None
    lesson_id: UUID | None = None


class PublicEvent(Contract):
    sequence: int
    event_id: UUID
    event_type: Literal[
        "job.queued",
        "goal.created",
        "job.succeeded",
        "job.failed",
        "tutor.queued",
        "tutor.running",
        "tutor.tool_completed",
        "tutor.succeeded",
        "tutor.failed",
        "tutor.cancelled",
        "tutor.blocked_unknown",
        "tutor.result_available",
        "learning.plan_drafted",
        "learning.plan_confirmed",
        "assessment.queued",
        "assessment.completed",
        "learning.lesson_completed",
        "knowledge.created",
        "knowledge.revised",
        "knowledge.admitted",
        "knowledge.revoked",
        "learning.review_scheduled",
        "learning.review_recorded",
        "learning.review_status_changed",
        "learning.dynamic_plan_drafted",
        "learning.dynamic_plan_confirmed",
        "learning.lesson_document_created",
    ]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID | None
    schema_version: Literal[1] = 1
    occurred_at: datetime
    payload: EventPayload


class ConversationTurns(Contract):
    conversation_id: UUID
    turns: list[Turn]


class Snapshot(Contract):
    actor: Actor
    goals: list[Goal]
    jobs: list[Job]
    events: list[PublicEvent]
    cursor: int
    limit: Literal[100] = 100
    conversations: list[Conversation] = []
    turns: list[ConversationTurns] = []
    runs: list[Run] = []
    tracks: list[Track] = []
    attempts: list[Attempt] = []
    sources: list[Source] = []
    reviews: list[ReviewCard] = []
    plans: list[LearningPlan] = []
    lessons: list[GeneratedLesson] = []


class LessonView(Contract):
    lesson: Lesson
    exercise: Exercise
