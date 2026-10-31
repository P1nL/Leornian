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

from leornian.agent_runtime.contracts import ModelAvailability, Run, TurnAccepted
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.services import GoalWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.delivery.contracts import LessonView, Snapshot
from leornian.modules.assessment.contracts import Attempt, Submission
from leornian.modules.execution.contracts import ExecutionClaim, RunnerClaim, RunnerReport
from leornian.modules.identity.contracts import LocalSessionRequest, Session
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
from leornian.modules.tutor.contracts import (
    Conversation,
    ConversationInput,
    PlanningInput,
    TurnInput,
)
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
    app = FastAPI(title="Leornian API", version="0.1.0")
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
        plan_id: UUID, token: Annotated[str, Depends(bearer)]
    ) -> list[PlanRevision]:
        return tutor.plan_history(token, plan_id)

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
