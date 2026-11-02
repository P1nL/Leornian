import asyncio
import secrets
import time
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from leornian.agent_runtime.contracts import ModelAvailability, Run, ToolActivity, TurnAccepted
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.artifacts import ArtifactWorkflow
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.evaluation import EvaluationWorkflow
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.bootstrap.services import GoalWorkflow
from leornian.bootstrap.supply_demand import SupplyWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.delivery.contracts import LessonView, Snapshot
from leornian.modules.assessment.contracts import Attempt, Submission
from leornian.modules.assessment.gate_contracts import (
    GateRequest,
    GateSubmission,
    GateSummary,
    GateView,
)
from leornian.modules.assessment.python_contracts import (
    PythonAttempt,
    PythonGateSubmission,
    PythonTraining,
)
from leornian.modules.assessment.transfer_contracts import (
    TransferAnswer,
    TransferRequest,
    TransferSummary,
    TransferView,
)
from leornian.modules.execution.contracts import ExecutionClaim, RunnerClaim, RunnerReport
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import LocalSessionRequest, Session
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.demand_contracts import SupplyDemand, SupplyRequest, SupplyRevision
from leornian.modules.item_bank.python_contracts import PythonQuestion
from leornian.modules.item_bank.supply_contracts import (
    ChoiceInput,
    ChoiceResult,
    PackAccepted,
    PackRequest,
    PackSummary,
    PracticeSet,
    PublicQuestion,
)
from leornian.modules.knowledge.contracts import (
    AdmitSource,
    Source,
    SourceAction,
    SourceInput,
    SourceRevision,
)
from leornian.modules.learning.contracts import (
    ConfirmDynamicPlan,
    GeneratedLesson,
    GoalInput,
    LearningPlan,
    LessonRequestInput,
    PlanRevision,
)
from leornian.modules.learning.journey_contracts import ConfirmPlan, Track, TrackInput
from leornian.modules.learning.review_contracts import ReviewCard, ReviewInput, ReviewStatus
from leornian.modules.tutor.artifact_contracts import (
    ArtifactJob,
    ArtifactRequestInput,
    ArtifactView,
)
from leornian.modules.tutor.contracts import (
    Conversation,
    ConversationInput,
    PlanningInput,
    Turn,
    TurnInput,
)
from leornian.modules.tutor.deliveries import DeliveryResume, DeliveryTask
from leornian.platform.config import Settings
from leornian.platform.database import Database
from leornian.platform.jobs import Accepted, Job
from leornian.shared_kernel.contracts import ErrorResponse
from leornian.shared_kernel.errors import BusinessError

security = HTTPBearer(auto_error=False)


def bearer(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> str:
    if credentials is None:
        raise BusinessError("unauthorized", "A Bearer session token is required.")
    return credentials.credentials


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings.database_url)
    workflow = GoalWorkflow(database)
    tutor = TutorWorkflow(database, settings)
    journey = JourneyWorkflow(database)
    knowledge = KnowledgeWorkflow(database)
    items = ItemSupply(database, settings)
    concept_gates = ConceptGate(database, settings)
    transfers = TransferWorkflow(database, settings)
    supply_demands = SupplyWorkflow(database, settings)
    evaluations = EvaluationWorkflow(database, settings)
    python = PythonWorkflow(database)
    artifacts = ArtifactWorkflow(database, settings)
    app = FastAPI(title="Leornian API", version="0.1.0")

    @app.post(
        "/v1/conversations/{conversation_id}/artifact-requests",
        status_code=202,
        response_model=ArtifactJob,
    )
    def artifact_request(
        conversation_id: UUID,
        data: ArtifactRequestInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return artifacts.request(token, conversation_id, key, data)

    @app.get("/v1/artifacts/{artifact_id}", response_model=ArtifactView)
    def artifact(
        artifact_id: UUID,
        token: Annotated[str, Depends(bearer)],
        revision: int | None = Query(default=None, ge=1),
    ):
        return artifacts.get(token, artifact_id, revision)

    @app.get("/v1/artifact-jobs/{job_id}", response_model=ArtifactJob)
    def artifact_job(job_id: UUID, token: Annotated[str, Depends(bearer)]):
        return artifacts.job(token, job_id)

    @app.post("/v1/artifact-jobs/{job_id}/cancel", response_model=ArtifactJob)
    def cancel_artifact(job_id: UUID, token: Annotated[str, Depends(bearer)]):
        return artifacts.action(token, job_id, "cancel")

    @app.post("/v1/artifact-jobs/{job_id}/resume", response_model=ArtifactJob)
    def resume_artifact(job_id: UUID, token: Annotated[str, Depends(bearer)]):
        return artifacts.action(token, job_id, "resume")

    @app.get("/v1/runs/{run_id}/tools", response_model=list[ToolActivity])
    def tool_activities(run_id: UUID, token: Annotated[str, Depends(bearer)]):
        with database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            runs = Runs(connection)
            runs.get(actor.id, run_id)
            return runs.activities(actor.id, run_id)

    @app.get("/v1/delivery-tasks", response_model=list[DeliveryTask])
    def delivery_tasks(
        token: Annotated[str, Depends(bearer)],
        before: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ):
        return tutor.delivery_tasks(token, before, limit)

    @app.get("/v1/delivery-tasks/{task_id}", response_model=DeliveryTask)
    def delivery_task(task_id: UUID, token: Annotated[str, Depends(bearer)]):
        return tutor.delivery_task(token, task_id)

    @app.post("/v1/delivery-tasks/{task_id}/cancel", response_model=DeliveryTask)
    def cancel_delivery(task_id: UUID, token: Annotated[str, Depends(bearer)]):
        return tutor.cancel_delivery(token, task_id)

    @app.post("/v1/delivery-tasks/{task_id}/resume", response_model=DeliveryTask)
    def resume_delivery(
        task_id: UUID, data: DeliveryResume, token: Annotated[str, Depends(bearer)]
    ):
        return tutor.resume_delivery(token, task_id, data.additional_instruction)

    @app.get("/v1/conversations/{conversation_id}/history", response_model=list[Turn])
    def teaching_history(
        conversation_id: UUID,
        token: Annotated[str, Depends(bearer)],
        before: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ):
        return tutor.turn_history(token, conversation_id, before, limit)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @app.exception_handler(BusinessError)
    async def business_error(_request: Request, error: BusinessError) -> JSONResponse:
        status = {
            "unauthorized": 401,
            "not_found": 404,
            "idempotency_conflict": 409,
            "cursor_invalid": 409,
            "run_active": 409,
            "unknown_unresolved": 409,
            "resume_not_allowed": 409,
            "model_unavailable": 503,
            "stale_version": 409,
            "precondition_failed": 409,
            "source_not_current": 409,
            "invalid_plan_output": 409,
            "invalid_lesson_output": 409,
            "invalid_item_output": 409,
            "invalid_gate_output": 409,
            "assessment_not_independent": 409,
            "invalid_transfer_output": 409,
            "no_transfer_candidate": 409,
            "supply_cancelled": 409,
        }[error.code]
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
        return JSONResponse(
            status_code=status,
            content={"code": error.code, "message": error.message},
            headers=headers,
        )

    @app.get("/health/ready")
    def readiness() -> JSONResponse:
        try:
            ready = database.ready()
        except Exception:
            ready = False
        return JSONResponse(status_code=200 if ready else 503, content={"ready": ready})

    @app.post("/v1/local-sessions", status_code=201, response_model=Session)
    def local_session(data: LocalSessionRequest) -> Session:
        # Anonymous local identities, not production registration/login.
        return workflow.create_session(data.display_name)

    @app.post(
        "/v1/goals",
        status_code=202,
        response_model=Accepted,
        responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def submit_goal(
        data: GoalInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> Accepted:
        return workflow.submit(token, key, data)

    @app.get("/v1/jobs/{job_id}", response_model=Job)
    def get_job(job_id: UUID, token: Annotated[str, Depends(bearer)]) -> Job:
        return workflow.job(token, job_id)

    @app.get("/v1/snapshot", response_model=Snapshot)
    def get_snapshot(token: Annotated[str, Depends(bearer)]) -> Snapshot:
        return workflow.snapshot(token)

    @app.get("/v1/tutor/availability", response_model=ModelAvailability)
    def tutor_availability(token: Annotated[str, Depends(bearer)]) -> ModelAvailability:
        workflow.snapshot(token)
        return ChatCompletionsGateway(settings).availability()

    @app.post("/v1/conversations", status_code=201, response_model=Conversation)
    def create_conversation(
        data: ConversationInput,
        token: Annotated[str, Depends(bearer)],
    ) -> Conversation:
        return tutor.conversation(token, data.goal_id)

    @app.post(
        "/v1/conversations/{conversation_id}/turns", status_code=202, response_model=TurnAccepted
    )
    def submit_turn(
        conversation_id: UUID,
        data: TurnInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> TurnAccepted:
        return tutor.submit(token, conversation_id, key, data)

    @app.post(
        "/v1/conversations/{conversation_id}/plan-requests",
        status_code=202,
        response_model=TurnAccepted,
    )
    def request_plan(
        conversation_id: UUID,
        data: PlanningInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> TurnAccepted:
        return tutor.submit_plan(token, conversation_id, key, data)

    @app.get("/v1/plans/{plan_id}", response_model=LearningPlan)
    def get_dynamic_plan(plan_id: UUID, token: Annotated[str, Depends(bearer)]) -> LearningPlan:
        return tutor.plan(token, plan_id)

    @app.get("/v1/plans/{plan_id}/revisions", response_model=list[PlanRevision])
    def get_plan_history(
        plan_id: UUID,
        token: Annotated[str, Depends(bearer)],
        before: int | None = Query(default=None, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[PlanRevision]:
        return tutor.plan_history(token, plan_id, before, limit)

    @app.post("/v1/plans/{plan_id}/confirm", response_model=LearningPlan)
    def confirm_dynamic_plan(
        plan_id: UUID,
        data: ConfirmDynamicPlan,
        token: Annotated[str, Depends(bearer)],
    ) -> LearningPlan:
        return tutor.confirm_plan(token, plan_id, data.expected_revision)

    @app.post("/v1/plans/{plan_id}/lesson-requests", status_code=202, response_model=TurnAccepted)
    def request_lesson(
        plan_id: UUID,
        data: LessonRequestInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> TurnAccepted:
        return tutor.submit_lesson(token, plan_id, key, data)

    @app.get("/v1/lessons/{lesson_id}", response_model=GeneratedLesson)
    def get_generated_lesson(
        lesson_id: UUID, token: Annotated[str, Depends(bearer)]
    ) -> GeneratedLesson:
        return tutor.lesson_document(token, lesson_id)

    @app.post("/v1/plans/{plan_id}/pack-requests", status_code=202, response_model=PackAccepted)
    def request_pack(
        plan_id: UUID,
        data: PackRequest,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> PackAccepted:
        return items.submit(token, plan_id, key, data)

    @app.get("/v1/packs/{pack_id}", response_model=PackSummary)
    def get_pack(pack_id: UUID, token: Annotated[str, Depends(bearer)]) -> PackSummary:
        return items.get(token, pack_id)

    @app.get("/v1/remediations/{remediation_id}/question", response_model=PublicQuestion)
    def remediation_question(
        remediation_id: UUID,
        token: Annotated[str, Depends(bearer)],
    ) -> PublicQuestion:
        return items.remediation(token, remediation_id)

    @app.post(
        "/v1/remediations/{remediation_id}/transfer-requests",
        status_code=202,
        response_model=TransferSummary,
    )
    def request_transfer(
        remediation_id: UUID,
        data: TransferRequest,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> TransferSummary:
        return transfers.request(token, remediation_id, key, data)

    @app.post(
        "/v1/python-attempts/{attempt_id}/transfer-requests",
        status_code=202,
        response_model=TransferSummary,
    )
    def request_execution_transfer(
        attempt_id: UUID,
        data: TransferRequest,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> TransferSummary:
        return transfers.request(token, attempt_id, key, data, required_kind="python_io")

    @app.post(
        "/v1/python-attempts/{attempt_id}/supply-requests",
        response_model=SupplyDemand,
        status_code=202,
    )
    def request_execution_supply(
        attempt_id: UUID,
        data: SupplyRequest,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> SupplyDemand:
        return supply_demands.request(token, attempt_id, key, data, required_kind="python_io")

    @app.post(
        "/v1/remediations/{remediation_id}/supply-requests",
        response_model=SupplyDemand,
        status_code=202,
    )
    def request_supply(
        remediation_id: UUID,
        data: SupplyRequest,
        token: Annotated[str, Depends(bearer)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    ):
        return supply_demands.request(token, remediation_id, idempotency_key, data)

    @app.post(
        "/v1/supply-demands/{demand_id}/revisions", response_model=SupplyDemand, status_code=202
    )
    def revise_supply(
        demand_id: UUID,
        data: SupplyRevision,
        token: Annotated[str, Depends(bearer)],
    ):
        return supply_demands.revise(token, demand_id, data)

    @app.post("/v1/evaluations/{evaluation_id}/run", response_model=TurnAccepted, status_code=202)
    def request_evaluation(evaluation_id: UUID, token: Annotated[str, Depends(bearer)]):
        return evaluations.request(token, evaluation_id)

    @app.post("/v1/packs/{pack_id}/cancel", response_model=PackSummary)
    def cancel_pack(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return items.cancel_pack(token, pack_id)

    @app.post("/v1/packs/{pack_id}/automation-resume", response_model=PackSummary)
    def resume_supply(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return items.resume_automation(token, pack_id)

    @app.post("/v1/packs/{pack_id}/continue-review", response_model=PackSummary)
    def continue_python_review(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return python.continue_review(token, pack_id)

    @app.get("/v1/packs/{pack_id}/execution-practice", response_model=list[PythonQuestion])
    def execution_practice(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return python.training(token, pack_id)

    @app.post("/v1/packs/{pack_id}/execution-remediation", response_model=list[PythonQuestion])
    def execution_remediation(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return python.training(token, pack_id, remediation=True)

    @app.post(
        "/v1/packs/{pack_id}/execution-submissions", response_model=PythonAttempt, status_code=202
    )
    def execution_training_submission(
        pack_id: UUID,
        data: PythonTraining,
        token: Annotated[str, Depends(bearer)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    ):
        return python.submit_training(token, pack_id, idempotency_key, data)

    @app.post(
        "/v1/packs/{pack_id}/execution-gate-requests", response_model=GateSummary, status_code=202
    )
    def request_execution_gate(
        pack_id: UUID,
        data: GateRequest,
        token: Annotated[str, Depends(bearer)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    ):
        return concept_gates.request(
            token, pack_id, idempotency_key, data, required_kind="python_io"
        )

    @app.post(
        "/v1/concept-gates/{gate_id}/execution-submissions",
        response_model=GateView,
        status_code=202,
    )
    def execution_gate_submission(
        gate_id: UUID,
        data: PythonGateSubmission,
        token: Annotated[str, Depends(bearer)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    ):
        return python.submit_gate(token, gate_id, idempotency_key, data)

    @app.get("/v1/transfers/{transfer_id}", response_model=TransferView)
    def get_transfer(transfer_id: UUID, token: Annotated[str, Depends(bearer)]) -> TransferView:
        return transfers.view(token, transfer_id)

    @app.post("/v1/transfers/{transfer_id}/open", response_model=TransferView)
    def open_transfer(transfer_id: UUID, token: Annotated[str, Depends(bearer)]) -> TransferView:
        return transfers.open(token, transfer_id)

    @app.post("/v1/transfers/{transfer_id}/submissions", response_model=TransferView)
    def submit_transfer(
        transfer_id: UUID,
        data: TransferAnswer,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> TransferView:
        return transfers.submit(token, transfer_id, key, data)

    @app.post(
        "/v1/transfers/{transfer_id}/execution-submissions",
        response_model=TransferView,
        status_code=202,
    )
    def submit_execution_transfer(
        transfer_id: UUID,
        data: Submission,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> TransferView:
        return transfers.submit_python(token, transfer_id, key, data)

    @app.post("/v1/transfers/{transfer_id}/cancel", response_model=TransferView)
    def cancel_transfer(transfer_id: UUID, token: Annotated[str, Depends(bearer)]) -> TransferView:
        return transfers.cancel(token, transfer_id)

    @app.post("/v1/packs/{pack_id}/gate-requests", status_code=202, response_model=GateSummary)
    def request_concept_gate(
        pack_id: UUID,
        data: GateRequest,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> GateSummary:
        return concept_gates.request(token, pack_id, key, data)

    @app.get("/v1/concept-gates/{gate_id}", response_model=GateView)
    def get_concept_gate(gate_id: UUID, token: Annotated[str, Depends(bearer)]) -> GateView:
        return concept_gates.view(token, gate_id)

    @app.post("/v1/concept-gates/{gate_id}/start", response_model=GateView)
    def start_concept_gate(gate_id: UUID, token: Annotated[str, Depends(bearer)]) -> GateView:
        return concept_gates.start(token, gate_id)

    @app.post("/v1/concept-gates/{gate_id}/submissions", response_model=GateView)
    def submit_concept_gate(
        gate_id: UUID,
        data: GateSubmission,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> GateView:
        return concept_gates.submit(token, gate_id, key, data)

    @app.post("/v1/concept-gates/{gate_id}/cancel", response_model=GateView)
    def cancel_concept_gate(gate_id: UUID, token: Annotated[str, Depends(bearer)]) -> GateView:
        return concept_gates.cancel(token, gate_id)

    @app.post("/v1/packs/{pack_id}/publish", response_model=PackSummary)
    def publish_pack(pack_id: UUID, token: Annotated[str, Depends(bearer)]) -> PackSummary:
        return items.publish(token, pack_id)

    @app.post("/v1/packs/{pack_id}/review-format-correction", response_model=PackSummary)
    def correct_pack_review_format(
        pack_id: UUID,
        token: Annotated[str, Depends(bearer)],
    ) -> PackSummary:
        return items.correct_review_format(token, pack_id)

    @app.get("/v1/packs/{pack_id}/practice", response_model=PracticeSet)
    def open_practice(pack_id: UUID, token: Annotated[str, Depends(bearer)]) -> PracticeSet:
        return items.practice(token, pack_id)

    @app.post("/v1/packs/{pack_id}/answers", response_model=ChoiceResult)
    def submit_choice(
        pack_id: UUID,
        data: ChoiceInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> ChoiceResult:
        return items.answer(token, pack_id, key, data)

    @app.get("/v1/runs/{run_id}", response_model=Run)
    def get_run(run_id: UUID, token: Annotated[str, Depends(bearer)]) -> Run:
        return tutor.get(token, run_id)

    @app.post("/v1/runs/{run_id}/cancel", response_model=Run)
    def cancel_run(run_id: UUID, token: Annotated[str, Depends(bearer)]) -> Run:
        return tutor.cancel(token, run_id)

    @app.post("/v1/runs/{run_id}/resume", response_model=Run)
    def resume_run(run_id: UUID, token: Annotated[str, Depends(bearer)]) -> Run:
        return tutor.resume(token, run_id)

    @app.post("/v1/tracks", status_code=201, response_model=Track)
    def draft_plan(data: TrackInput, token: Annotated[str, Depends(bearer)]) -> Track:
        return journey.draft(token, data.goal_id)

    @app.post("/v1/tracks/{track_id}/confirm", response_model=Track)
    def confirm_plan(
        track_id: UUID,
        data: ConfirmPlan,
        token: Annotated[str, Depends(bearer)],
    ) -> Track:
        return journey.confirm(token, track_id, data.expected_revision)

    @app.get("/v1/tracks/{track_id}/lesson", response_model=LessonView)
    def get_lesson(track_id: UUID, token: Annotated[str, Depends(bearer)]) -> LessonView:
        lesson, exercise = journey.lesson(token, track_id)
        return LessonView(lesson=lesson, exercise=exercise)

    @app.post("/v1/tracks/{track_id}/submissions", status_code=202, response_model=Attempt)
    def submit_code(
        track_id: UUID,
        data: Submission,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> Attempt:
        return journey.submit(token, track_id, key, data)

    @app.get("/v1/attempts/{attempt_id}", response_model=Attempt)
    def get_attempt(attempt_id: UUID, token: Annotated[str, Depends(bearer)]) -> Attempt:
        return journey.attempt(token, attempt_id)

    @app.post("/v1/reviews/{card_id}/responses", response_model=ReviewCard)
    def respond_review(
        card_id: UUID,
        data: ReviewInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> ReviewCard:
        return journey.review(token, card_id, key, data)

    @app.post("/v1/reviews/{card_id}/status", response_model=ReviewCard)
    def change_review_status(
        card_id: UUID,
        data: ReviewStatus,
        token: Annotated[str, Depends(bearer)],
    ) -> ReviewCard:
        return journey.review_status(token, card_id, data)

    @app.post("/v1/goals/{goal_id}/sources", status_code=201, response_model=Source)
    def create_source(
        goal_id: UUID,
        data: SourceInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> Source:
        return knowledge.create(token, goal_id, key, data)

    @app.post("/v1/sources/{source_id}/revisions", response_model=Source)
    def revise_source(
        source_id: UUID,
        data: SourceRevision,
        token: Annotated[str, Depends(bearer)],
    ) -> Source:
        return knowledge.revise(token, source_id, data)

    @app.post("/v1/sources/{source_id}/admit", response_model=Source)
    def admit_source(
        source_id: UUID,
        data: AdmitSource,
        token: Annotated[str, Depends(bearer)],
    ) -> Source:
        return knowledge.admit(token, source_id, data)

    @app.post("/v1/sources/{source_id}/revoke", response_model=Source)
    def revoke_source(
        source_id: UUID,
        data: SourceAction,
        token: Annotated[str, Depends(bearer)],
    ) -> Source:
        return knowledge.revoke(token, source_id, data.expected_revision)

    def runner_auth(token: Annotated[str, Depends(bearer)]) -> None:
        if not settings.runner_token or not secrets.compare_digest(token, settings.runner_token):
            raise BusinessError("unauthorized", "A dedicated Runner credential is required.")

    @app.post(
        "/internal/executions/claim",
        response_model=ExecutionClaim | None,
        dependencies=[Depends(runner_auth)],
    )
    def runner_claim(data: RunnerClaim) -> ExecutionClaim | None:
        return journey.claim(data.runner_id)

    @app.post("/internal/executions/{job_id}/report", dependencies=[Depends(runner_auth)])
    def runner_report(job_id: UUID, data: RunnerReport) -> dict:
        journey.report(job_id, data)
        return {"recorded": True}

    @app.get(
        "/v1/events",
        response_model=None,
        responses={
            200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}},
            401: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def get_events(
        request: Request,
        token: Annotated[str, Depends(bearer)],
        after: Annotated[int, Query(ge=0)] = 0,
        last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None,
    ) -> StreamingResponse:
        cursor = last_event_id if last_event_id is not None else after
        first = await run_in_threadpool(workflow.events, token, cursor)

        async def stream():
            current = cursor
            batch = first
            heartbeat = time.monotonic()
            yield ": connected\n\n"
            while not await request.is_disconnected():
                for event in batch:
                    yield (
                        f"id: {event.sequence}\nevent: {event.event_type}\n"
                        f"data: {event.model_dump_json()}\n\n"
                    )
                    current = event.sequence
                if time.monotonic() - heartbeat >= 10:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.5)
                try:
                    batch = await run_in_threadpool(workflow.events, token, current)
                except BusinessError as error:
                    # HTTP status is already sent; ask the client to reauthenticate/reset.
                    yield f'event: stream.reset\ndata: {{"code":"{error.code}"}}\n\n'
                    return

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
