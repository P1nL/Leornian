from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.agent_runtime.contracts import Run, ToolActivity
from leornian.modules.assessment.contracts import Attempt
from leornian.modules.assessment.gate_contracts import GateSummary, Remediation
from leornian.modules.assessment.program_contracts import ProgramPracticeAttempt
from leornian.modules.assessment.python_contracts import PythonAttempt
from leornian.modules.assessment.transfer_contracts import TransferSummary
from leornian.modules.identity.contracts import Actor
from leornian.modules.item_bank.contracts import Exercise
from leornian.modules.item_bank.demand_contracts import SupplyDemand
from leornian.modules.item_bank.supply_contracts import ChoiceResult, PackSummary
from leornian.modules.knowledge.contracts import Source
from leornian.modules.learning.contracts import GeneratedLesson, Goal, LearningPlan, NodeProgress
from leornian.modules.learning.execution_contracts import ExecutionProgress
from leornian.modules.learning.journey_contracts import Lesson, Track
from leornian.modules.learning.review_contracts import ReviewCard
from leornian.modules.tutor.artifact_contracts import ArtifactJob, ArtifactSummary
from leornian.modules.tutor.contracts import Conversation, Turn
from leornian.modules.tutor.deliveries import DeliveryTask
from leornian.modules.tutor.evaluation_contracts import Evaluation
from leornian.modules.tutor.learning_artifact_contracts import LearningArtifactSummary
from leornian.modules.tutor.teaching_session_contracts import TeachingBranch, TeachingSession
from leornian.modules.tutor.thinking_contracts import ThinkingStep
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
    pack_id: UUID | None = None
    gate_id: UUID | None = None
    transfer_id: UUID | None = None
    artifact_id: UUID | None = None
    artifact_job_id: UUID | None = None
    learning_artifact_id: UUID | None = None
    document_id: UUID | None = None
    document_revision: int | None = None
    teaching_intent_id: UUID | None = None
    material_update_offer_id: UUID | None = None
    material_update_decision_id: UUID | None = None
    notification_id: UUID | None = None
    thinking_summary: str | None = None
    thinking_text: str | None = None
    thinking_step: ThinkingStep | None = None
    reply_text: str | None = None
    reply_id: UUID | None = None


class PublicEvent(Contract):
    sequence: int
    event_id: UUID
    event_type: Literal[
        "job.queued",
        "goal.created",
        "goal.updated",
        "goal.deleted",
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
        "tutor.thinking",
        "tutor.stage_reply",
        "tutor.conversation_hidden",
        "learning.plan_drafted",
        "learning.plan_confirmed",
        "assessment.queued",
        "assessment.completed",
        "learning.lesson_completed",
        "knowledge.created",
        "knowledge.revised",
        "knowledge.admitted",
        "knowledge.revoked",
        "knowledge.material_permission_changed",
        "knowledge.material_update_offered",
        "learning.material_update_decided",
        "delivery.notification_updated",
        "learning.review_scheduled",
        "learning.review_recorded",
        "learning.review_status_changed",
        "learning.dynamic_plan_drafted",
        "learning.dynamic_plan_confirmed",
        "learning.lesson_document_created",
        "item_bank.updated",
        "assessment.choice_recorded",
        "assessment.response_recorded",
        "assessment.remediation_updated",
        "assessment.gate_updated",
        "learning.node_completed",
        "assessment.transfer_updated",
        "tutor.artifact_updated",
        "tutor.learning_artifact_updated",
        "tutor.teaching_session_updated",
        "tutor.teaching_intent_updated",
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
    teaching_sessions: list[TeachingSession] = []
    teaching_branches: list[TeachingBranch] = []
    turns: list[ConversationTurns] = []
    runs: list[Run] = []
    tracks: list[Track] = []
    attempts: list[Attempt] = []
    sources: list[Source] = []
    reviews: list[ReviewCard] = []
    plans: list[LearningPlan] = []
    lessons: list[GeneratedLesson] = []
    packs: list[PackSummary] = []
    choice_results: list[ChoiceResult] = []
    remediations: list[Remediation] = []
    gates: list[GateSummary] = []
    node_progress: list[NodeProgress] = []
    transfers: list[TransferSummary] = []
    supply_demands: list[SupplyDemand] = []
    evaluations: list[Evaluation] = []
    python_attempts: list[PythonAttempt] = []
    program_attempts: list[ProgramPracticeAttempt] = []
    execution_progress: list[ExecutionProgress] = []
    delivery_tasks: list[DeliveryTask] = []
    artifacts: list[ArtifactSummary] = []
    artifact_jobs: list[ArtifactJob] = []
    tool_activities: list[ToolActivity] = []
    learning_artifacts: list[LearningArtifactSummary] = []


class LessonView(Contract):
    lesson: Lesson
    exercise: Exercise
