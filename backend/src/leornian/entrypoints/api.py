import asyncio
import json
import secrets
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from leornian.agent_runtime.contracts import ModelAvailability, Run, ToolActivity, TurnAccepted
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.artifacts import ArtifactWorkflow
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.evaluation import EvaluationWorkflow
from leornian.bootstrap.example_runs import ExampleRuns
from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.learning_evidence import LearningEvidenceWorkflow
from leornian.bootstrap.material_change_reviews import MaterialChangeReviewWorkflow
from leornian.bootstrap.material_changes import MaterialChangeWorkflow
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.material_files import MaterialFilesWorkflow
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_recovery import MaterialRecoveryResult, MaterialRecoveryWorkflow
from leornian.bootstrap.material_repreparations import MaterialRepreparationWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.material_sources import MaterialSourceWorkflow
from leornian.bootstrap.material_updates import MaterialUpdateWorkflow
from leornian.bootstrap.materials import MaterialWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.model_tests import ModelTestWorkflow
from leornian.bootstrap.notifications import NotificationsWorkflow
from leornian.bootstrap.proactive_teaching import ProactiveTeachingWorkflow
from leornian.bootstrap.program_execution import ProgramWorkflow
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.bootstrap.reviews import ReviewsWorkflow
from leornian.bootstrap.services import GoalWorkflow
from leornian.bootstrap.supply_demand import SupplyWorkflow
from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.delivery.contracts import LessonView, Snapshot
from leornian.delivery.notification_contracts import Notification
from leornian.modules.assessment.contracts import Attempt, ResponseResult, Submission
from leornian.modules.assessment.gate_contracts import (
    GateRequest,
    GateSubmission,
    GateSummary,
    GateView,
)
from leornian.modules.assessment.program_contracts import (
    ProgramGateSubmission,
    ProgramPracticeAttempt,
    ProgramPracticeHistory,
    ProgramPracticeSubmission,
    ProgramTransferSubmission,
)
from leornian.modules.assessment.python_contracts import (
    PythonAttempt,
    PythonGateSubmission,
    PythonPracticeAttempt,
    PythonPracticeHistory,
    PythonPracticeSubmission,
    PythonTraining,
)
from leornian.modules.assessment.transfer_contracts import (
    TransferAnswer,
    TransferRequest,
    TransferSummary,
    TransferView,
)
from leornian.modules.execution.contracts import (
    ExecutionClaim,
    ExecutionVerificationInput,
    ProgramExecutionClaim,
    RunnerClaim,
    RunnerReport,
)
from leornian.modules.execution.environment_contracts import (
    EngineObservationInput,
    EnvironmentDecision,
    EnvironmentDecisionInput,
    EnvironmentDemand,
    EnvironmentDemandInput,
    EnvironmentPreparationClaim,
    EnvironmentPreparationClaimInput,
    EnvironmentPreparationProgress,
    EnvironmentPreparationReport,
    EnvironmentRebuildInput,
    EnvironmentRelease,
    EnvironmentReleaseUnavailable,
    EnvironmentReleaseVerificationInput,
    ExecutionEnvironments,
    RouteEnvironmentManifest,
)
from leornian.modules.execution.example_contracts import (
    ExampleRunInput,
    ExampleRunResult,
    ExampleTerminalExchange,
    ExampleTerminalLine,
)
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import LocalSessionRequest, Session
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.contracts import PublicProgramQuestion
from leornian.modules.item_bank.demand_contracts import SupplyDemand, SupplyRequest, SupplyRevision
from leornian.modules.item_bank.generation_contracts import BankNode, GenerationReport
from leornian.modules.item_bank.python_contracts import PythonQuestion
from leornian.modules.item_bank.response_contracts import ResponsePracticeSet, ResponseSubmission
from leornian.modules.item_bank.supply_contracts import (
    ChoiceInput,
    ChoiceResult,
    PackAccepted,
    PackRequest,
    PackSummary,
    PracticeSet,
    PublicQuestion,
)
from leornian.modules.knowledge.change_contracts import (
    MaterialChangeInput,
    MaterialChangeReport,
    MaterialChangeReview,
)
from leornian.modules.knowledge.contracts import (
    AdmitSource,
    Source,
    SourceAction,
    SourceInput,
    SourceRevision,
)
from leornian.modules.knowledge.file_contracts import (
    MaterialFileJobInput,
    MaterialUpload,
    MaterialUploadInput,
)
from leornian.modules.knowledge.intake_contracts import (
    MaterialDemand,
    MaterialDemandInput,
    MaterialJob,
    MaterialTextJobInput,
)
from leornian.modules.knowledge.material_contracts import (
    DocumentBlockPage,
    DocumentPermissionAction,
    DocumentVersion,
    LegacyMaterialImport,
    MaterialPurpose,
    TextMaterialImport,
)
from leornian.modules.knowledge.progress_contracts import MaterialPreparationProgress
from leornian.modules.knowledge.retrieval_contracts import (
    MaterialSearch,
    MaterialSearchInput,
    MaterialSelection,
)
from leornian.modules.knowledge.source_contracts import (
    MaterialDiscovery,
    MaterialSource,
    MaterialSourceAction,
    MaterialSourceInput,
    MaterialSourceObservation,
)
from leornian.modules.knowledge.update_contracts import (
    MaterialUpdateOffer,
    MaterialUpdatePreparation,
    MaterialUpdatePrepareInput,
)
from leornian.modules.learning.contracts import (
    ConfirmDynamicPlan,
    GeneratedLesson,
    Goal,
    GoalInput,
    GoalRename,
    LearningPlan,
    LessonRequestInput,
    PlanConfirmation,
    PlanRevision,
)
from leornian.modules.learning.evidence_contracts import LearningEvidenceProjection
from leornian.modules.learning.journey_contracts import ConfirmPlan, Track, TrackInput
from leornian.modules.learning.material_contracts import (
    BoundMaterialPage,
    MaterialBinding,
    MaterialBindingInput,
)
from leornian.modules.learning.material_update_contracts import (
    MaterialRepreparation,
    MaterialUpdateDecision,
    MaterialUpdateDecisionInput,
)
from leornian.modules.learning.review_contracts import (
    PresentReview,
    ReviewActivity,
    ReviewCard,
    ReviewInput,
    ReviewLog,
    ReviewStatus,
)
from leornian.modules.tutor.artifact_contracts import (
    ArtifactJob,
    ArtifactRequestInput,
    ArtifactView,
)
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionActionReceipt,
    CompositionArtifactSummary,
    CompositionArtifactView,
    CompositionSourceView,
    LearningArtifactActionV2,
)
from leornian.modules.tutor.contracts import (
    Conversation,
    ConversationInput,
    PlanningInput,
    Turn,
    TurnInput,
)
from leornian.modules.tutor.deliveries import DeliveryResume, DeliveryTask
from leornian.modules.tutor.demo_contracts import DemoActionReceipt, DemoHistory
from leornian.modules.tutor.learning_artifact_contracts import (
    LearningActionReceipt,
    LearningArtifactAction,
    LearningArtifactSummary,
    LearningArtifactView,
    LearningCandidate,
    LearningCandidateInput,
    PracticeSampleRunInput,
)
from leornian.modules.tutor.proactive_contracts import (
    ProactivePreference,
    ProactivePreferenceInput,
)
from leornian.modules.tutor.review_contracts import ReviewActionReceipt
from leornian.modules.tutor.teaching_intent_contracts import (
    CancelTeachingIntent,
    TeachingIntent,
)
from leornian.modules.tutor.teaching_session_contracts import (
    ContinueNode,
    TeachingBranch,
    TeachingSession,
    TeachingSessionCommand,
)
from leornian.platform.config import Settings
from leornian.platform.database import Database
from leornian.platform.jobs import Accepted, Job
from leornian.platform.material_search_configuration import (
    TavilyConfiguration,
    TavilyConfigurationInput,
)
from leornian.platform.model_contracts import (
    ModelConfiguration,
    ModelConnection,
    ModelConnectionDelete,
    ModelConnectionInput,
    ModelConnectionPatch,
    ModelConnectionTest,
    ModelConnectionTestInput,
    ModelConnectionUseInput,
    ModelCustomProviderInput,
    ModelPresetId,
    ModelPresetInput,
    ModelProfile,
    ModelProfileInput,
    ModelProfilePatch,
    ModelRole,
    ModelRoleAssignmentInput,
    ModelRoleMapping,
)
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
    materials = MaterialWorkflow(database, settings)
    material_intake = MaterialIntakeWorkflow(database, settings)
    material_search = MaterialSearchWorkflow(database, settings)
    material_changes = MaterialChangeWorkflow(database)
    material_change_reviews = MaterialChangeReviewWorkflow(database, settings)
    material_updates = MaterialUpdateWorkflow(database, settings)
    material_repreparations = MaterialRepreparationWorkflow(database, settings)
    material_sources = MaterialSourceWorkflow(database, settings)
    material_discovery = MaterialDiscoveryWorkflow(database, settings)
    notifications = NotificationsWorkflow(database)
    learning_artifacts = LearningArtifactWorkflow(database)
    material_files = MaterialFilesWorkflow(database, settings)
    models = ModelConfigurationWorkflow(database, settings)
    model_tests = ModelTestWorkflow(database, settings)
    items = ItemSupply(database, settings)
    concept_gates = ConceptGate(database, settings)
    transfers = TransferWorkflow(database, settings)
    supply_demands = SupplyWorkflow(database, settings)
    evaluations = EvaluationWorkflow(database, settings)
    python = PythonWorkflow(database)
    programs = ProgramWorkflow(database)
    execution_environments = ExecutionEnvironmentWorkflow(database)
    reviews = ReviewsWorkflow(database)
    learning_evidence = LearningEvidenceWorkflow(database)
    proactive_teaching = ProactiveTeachingWorkflow(database)
    artifacts = ArtifactWorkflow(database, settings)
    app = FastAPI(title="Leornian API", version="0.1.0")

    @app.post("/v1/material-demands", status_code=201, response_model=MaterialDemand)
    def create_material_demand(
        data: MaterialDemandInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_intake.create_demand(token, key, data)

    @app.get("/v1/material-demands", response_model=list[MaterialDemand])
    def material_demands(
        goal_id: UUID,
        token: Annotated[str, Depends(bearer)],
        before: UUID | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ):
        return material_intake.demands(token, goal_id, before, limit)

    @app.get("/v1/material-demands/commands/{request_key}", response_model=MaterialDemand)
    def material_demand_receipt(
        token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return material_intake.demand_receipt(token, request_key)

    @app.get("/v1/material-demands/{demand_id}", response_model=MaterialDemand)
    def material_demand(demand_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_intake.demand(token, demand_id)

    @app.post("/v1/material-demands/{demand_id}/texts", status_code=202, response_model=MaterialJob)
    def prepare_text_material(
        demand_id: UUID,
        data: MaterialTextJobInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_intake.submit_text(token, demand_id, key, data)

    @app.post(
        "/v1/material-demands/{demand_id}/uploads", status_code=201, response_model=MaterialUpload
    )
    def reserve_material_upload(
        demand_id: UUID,
        data: MaterialUploadInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_files.reserve(token, demand_id, key, data)

    @app.get("/v1/material-uploads/{upload_id}", response_model=MaterialUpload)
    def material_upload(upload_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_files.upload(token, upload_id)

    @app.get(
        "/v1/material-demands/{demand_id}/uploads/commands/{request_key}",
        response_model=MaterialUpload,
    )
    def material_upload_receipt(
        demand_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return material_files.upload_receipt(token, demand_id, request_key)

    @app.get(
        "/v1/material-demands/{demand_id}/files/commands/{request_key}",
        response_model=MaterialJob,
    )
    def material_file_job_receipt(
        demand_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return material_intake.file_receipt(token, demand_id, request_key)

    @app.get("/v1/material-jobs/{job_id}/cancellation", response_model=MaterialJob)
    def material_job_cancellation(job_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_intake.cancel_receipt(token, job_id)

    @app.get(
        "/v1/documents/{document_id}/versions/{revision}/revocation",
        response_model=DocumentVersion,
    )
    def material_document_revocation(
        document_id: UUID, revision: int, token: Annotated[str, Depends(bearer)],
    ):
        return materials.revoke_receipt(token, document_id, revision)

    @app.put(
        "/v1/material-uploads/{upload_id}/content",
        response_model=MaterialUpload,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def upload_original_material(
        upload_id: UUID,
        request: Request,
        token: Annotated[str, Depends(bearer)],
        content_length: Annotated[int | None, Header(ge=0)] = None,
    ):
        upload = await run_in_threadpool(material_files.preflight, token, upload_id)
        if content_length is not None and content_length != upload.byte_size:
            raise BusinessError("material_content_mismatch", "Upload byte length changed.")
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/octet-stream":
            raise BusinessError(
                "precondition_failed", "Send original bytes as application/octet-stream."
            )
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > upload.byte_size:
                raise BusinessError(
                    "material_file_limit", "Upload exceeds its declared byte limit."
                )
            chunks.append(chunk)
        return await run_in_threadpool(
            material_files.store_content, token, upload_id, b"".join(chunks)
        )

    @app.get(
        "/v1/material-uploads/{upload_id}/content",
        response_class=Response,
        responses={
            200: {
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    def original_material(
        upload_id: UUID,
        purpose: MaterialPurpose,
        token: Annotated[str, Depends(bearer)],
    ):
        content = material_files.original(token, upload_id, purpose)
        return Response(
            content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="original-material"',
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox",
                "Cache-Control": "no-store",
            },
        )

    @app.post("/v1/material-demands/{demand_id}/files", status_code=202, response_model=MaterialJob)
    def prepare_file_material(
        demand_id: UUID,
        data: MaterialFileJobInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_files.submit(token, demand_id, key, data)

    @app.get("/v1/material-demands/{demand_id}/jobs", response_model=list[MaterialJob])
    def demand_jobs(
        demand_id: UUID,
        token: Annotated[str, Depends(bearer)],
        before: UUID | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ):
        return material_intake.jobs(token, demand_id, before, limit)

    @app.get("/v1/material-jobs/{job_id}", response_model=MaterialJob)
    def material_job(job_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_intake.job(token, job_id)

    @app.post("/v1/material-jobs/{job_id}/cancel", response_model=MaterialJob)
    def cancel_material_job(job_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_intake.cancel(token, job_id)

    @app.post("/v1/material-searches", status_code=202, response_model=MaterialSearch)
    def search_material(
        data: MaterialSearchInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)],
    ):
        return material_search.submit(token, key, data)

    @app.get("/v1/material-searches/{search_id}", response_model=MaterialSearch)
    def material_search_status(search_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_search.get(token, search_id)

    @app.post("/v1/material-searches/{search_id}/cancel", response_model=MaterialSearch)
    def cancel_material_search(search_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_search.cancel(token, search_id)

    @app.get("/v1/material-selections/{selection_id}", response_model=MaterialSelection)
    def material_selection(selection_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_search.selection(token, selection_id)

    @app.post("/v1/material-change-checks", status_code=201, response_model=MaterialChangeReport)
    def compare_material_versions(
        data: MaterialChangeInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_changes.compare(token, key, data)

    @app.get("/v1/material-change-checks/{check_id}", response_model=MaterialChangeReport)
    def material_change_check(check_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_changes.get(token, check_id)

    @app.get(
        "/v1/material-change-checks/{check_id}/review", response_model=MaterialChangeReview | None
    )
    def material_change_review(check_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_change_reviews.get(token, check_id)

    @app.post(
        "/v1/material-change-checks/{check_id}/review/cancel", response_model=MaterialChangeReview
    )
    def cancel_material_change_review(check_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_change_reviews.cancel(token, check_id)

    @app.get(
        "/v1/material-change-checks/{check_id}/preparation",
        response_model=MaterialUpdatePreparation | None,
    )
    def material_update_preparation(check_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_updates.get_preparation(token, check_id)

    @app.post(
        "/v1/material-change-checks/{check_id}/offers",
        status_code=201, response_model=MaterialUpdateOffer,
    )
    def prepare_material_update(
        check_id: UUID, data: MaterialUpdatePrepareInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_updates.prepare(token, check_id, key, data)

    @app.get("/v1/material-update-offers/{offer_id}", response_model=MaterialUpdateOffer)
    def material_update_offer(offer_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_updates.get(token, offer_id)

    @app.post(
        "/v1/material-update-offers/{offer_id}/decisions",
        status_code=201, response_model=MaterialUpdateDecision,
    )
    def decide_material_update(
        offer_id: UUID, data: MaterialUpdateDecisionInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_updates.decide(token, offer_id, key, data)

    @app.get(
        "/v1/material-update-offers/{offer_id}/decisions/{request_key}",
        response_model=MaterialUpdateDecision,
    )
    def material_update_decision_receipt(
        offer_id: UUID, request_key: Annotated[str, Path(min_length=8, max_length=128)],
        token: Annotated[str, Depends(bearer)],
    ):
        return material_updates.decision_receipt(token, offer_id, request_key)

    @app.get(
        "/v1/material-update-decisions/{decision_id}/repreparations",
        response_model=list[MaterialRepreparation],
    )
    def material_dependency_preparations(
        decision_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return material_repreparations.list(token, decision_id)

    @app.post("/v1/material-sources", response_model=MaterialSource, status_code=201)
    def register_material_source(
        data: MaterialSourceInput, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_sources.register(token, key, data)

    @app.get("/v1/material-sources/commands/{request_key}", response_model=MaterialSource)
    def material_source_registration_receipt(
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
        token: Annotated[str, Depends(bearer)],
    ):
        return material_sources.registration_receipt(token, request_key)

    @app.get("/v1/material-sources", response_model=list[MaterialSource])
    def list_material_sources(goal_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_sources.list(token, goal_id)

    @app.get("/v1/material-sources/{source_id}", response_model=MaterialSource)
    def material_source(source_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_sources.get(token, source_id)

    @app.post(
        "/v1/material-sources/{source_id}/checks", response_model=MaterialSourceObservation,
        status_code=202,
    )
    def check_material_source(
        source_id: UUID, data: MaterialSourceAction,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return material_sources.check(token, source_id, key, data)

    @app.get(
        "/v1/material-sources/{source_id}/checks/commands/{request_key}",
        response_model=MaterialSourceObservation,
    )
    @app.get(
        "/v1/material-sources/{source_id}/checks/{request_key}",
        response_model=MaterialSourceObservation,
    )
    def material_source_check_receipt(
        source_id: UUID, request_key: Annotated[str, Path(min_length=8, max_length=128)],
        token: Annotated[str, Depends(bearer)],
    ):
        return material_sources.check_receipt(token, source_id, request_key)

    @app.post("/v1/material-sources/{source_id}/revoke", response_model=MaterialSource)
    def revoke_material_source(
        source_id: UUID, data: MaterialSourceAction, token: Annotated[str, Depends(bearer)],
    ):
        return material_sources.revoke(token, source_id, data)

    @app.get("/v1/material-sources/{source_id}/revocation", response_model=MaterialSource)
    def material_source_revocation_receipt(
        source_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return material_sources.revocation_receipt(token, source_id)

    @app.get(
        "/v1/material-source-observations/{observation_id}",
        response_model=MaterialSourceObservation,
    )
    def material_source_observation(
        observation_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return material_sources.observation(token, observation_id)

    @app.get("/v1/material-source-observations/{observation_id}/original")
    def material_source_original(
        observation_id: UUID, purpose: str, token: Annotated[str, Depends(bearer)],
    ):
        return Response(
            material_sources.original(token, observation_id, purpose),
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="material-source-original"'},
        )

    @app.get(
        "/v1/material-demands/{demand_id}/discovery", response_model=MaterialDiscovery,
    )
    def material_demand_discovery(demand_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_discovery.get(token, demand_id)

    @app.post(
        "/v1/material-demands/{demand_id}/discovery", response_model=MaterialDiscovery,
        status_code=202,
    )
    def request_material_discovery(demand_id: UUID, token: Annotated[str, Depends(bearer)]):
        return material_discovery.ensure(token, demand_id)

    @app.get("/v1/notifications", response_model=list[Notification])
    def notification_list(
        token: Annotated[str, Depends(bearer)],
        before: UUID | None = None, limit: int = Query(default=20, ge=1, le=100),
    ):
        return notifications.list(token, before, limit)

    @app.post("/v1/notifications/{notification_id}/read", response_model=Notification)
    def read_notification(notification_id: UUID, token: Annotated[str, Depends(bearer)]):
        return notifications.read(token, notification_id)

    @app.post(
        "/v1/conversations/{conversation_id}/learning-artifact-candidates",
        status_code=201, response_model=LearningCandidate,
    )
    def learning_candidate(
        conversation_id: UUID, data: LearningCandidateInput,
        token: Annotated[str, Depends(bearer)],
    ):
        return learning_artifacts.candidate(token, conversation_id, data)

    @app.get(
        "/v1/conversations/{conversation_id}/learning-artifacts",
        response_model=list[LearningArtifactSummary],
    )
    def learning_artifact_list(
        conversation_id: UUID, token: Annotated[str, Depends(bearer)],
        before: UUID | None = None, limit: int = Query(default=20, ge=1, le=100),
    ):
        return learning_artifacts.list(token, conversation_id, before, limit)

    @app.get(
        "/v1/conversations/{conversation_id}/learning-artifacts/{artifact_id}",
        response_model=LearningArtifactView,
    )
    def learning_artifact(
        conversation_id: UUID, artifact_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return learning_artifacts.get(token, conversation_id, artifact_id)

    @app.post(
        "/v1/conversations/{conversation_id}/learning-artifacts/{artifact_id}/actions",
        response_model=LearningActionReceipt,
    )
    def learning_artifact_action(
        conversation_id: UUID, artifact_id: UUID, data: LearningArtifactAction,
        token: Annotated[str, Depends(bearer)],
    ):
        return learning_artifacts.action(token, conversation_id, artifact_id, data)

    @app.get(
        "/v2/conversations/{conversation_id}/learning-artifacts",
        response_model=list[LearningArtifactSummary | CompositionArtifactSummary],
    )
    def learning_artifact_list_v2(
        conversation_id: UUID, token: Annotated[str, Depends(bearer)],
        before: UUID | None = None, limit: int = Query(default=20, ge=1, le=100),
    ):
        return learning_artifacts.list_v2(token, conversation_id, before, limit)

    @app.get(
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}",
        response_model=LearningArtifactView | CompositionArtifactView,
    )
    def learning_artifact_v2(
        conversation_id: UUID, artifact_id: UUID, token: Annotated[str, Depends(bearer)],
        response_capability: Literal["learning_responses.v1"] | None = None,
        code_review_capability: Literal[
            "learning_code_review.v1", "learning_code_review.v2",
        ] | None = None,
        program_capability: Literal["learning_programs.v1", "learning_programs.v2"] | None = None,
        direct_answer_capability: Literal["learning_direct_answers.v1"] | None = None,
        hint_capability: Literal["learning_hints.v1"] | None = None,
        demo_capability: Literal["learning_demo_events.v1"] | None = None,
        example_capability: Literal[
            "learning_example_runs.v1", "learning_example_runs.v2",
        ] | None = None,
    ):
        return learning_artifacts.get_v2(
            token, conversation_id, artifact_id, response_capability=response_capability,
            code_review_capability=code_review_capability,
            program_capability=program_capability,
            direct_answer_capability=direct_answer_capability,
            hint_capability=hint_capability,
            demo_capability=demo_capability, example_capability=example_capability,
        )

    @app.post(
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}/example-runs",
        status_code=202, response_model=ExampleRunResult,
    )
    def run_example(
        conversation_id: UUID, artifact_id: UUID, data: ExampleRunInput | PracticeSampleRunInput,
        token: Annotated[str, Depends(bearer)],
    ):
        return ExampleRuns(database).submit(token, conversation_id, artifact_id, data)

    @app.get(
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}/example-runs/{command_id}",
        response_model=ExampleRunResult,
    )
    def example_result(
        conversation_id: UUID, artifact_id: UUID, command_id: UUID,
        token: Annotated[str, Depends(bearer)],
    ):
        return ExampleRuns(database).get(token, conversation_id, artifact_id, command_id)

    example_terminal = (
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}/example-runs/{command_id}"
    )

    @app.post(example_terminal + "/input", response_model=ExampleRunResult)
    def send_example_input(
        conversation_id: UUID, artifact_id: UUID, command_id: UUID, data: ExampleTerminalLine,
        token: Annotated[str, Depends(bearer)],
    ):
        return ExampleRuns(database).control(
            token, conversation_id, artifact_id, command_id, line=data,
        )

    @app.post(example_terminal + "/stop", response_model=ExampleRunResult)
    def stop_example(
        conversation_id: UUID, artifact_id: UUID, command_id: UUID,
        token: Annotated[str, Depends(bearer)],
    ):
        return ExampleRuns(database).control(token, conversation_id, artifact_id, command_id)

    @app.get(
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}"
        "/demos/{component_id}/completions",
        response_model=DemoHistory,
    )
    def demonstration_history(
        conversation_id: UUID, artifact_id: UUID, component_id: str,
        demo_capability: Literal["learning_demo_events.v1"],
        token: Annotated[str, Depends(bearer)],
        before: int | None = Query(default=None, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        return learning_artifacts.demo_history(
            token, conversation_id, artifact_id, component_id, before, limit,
        )

    @app.get(
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}/sources/{component_id}",
        response_model=CompositionSourceView,
    )
    def composition_source(
        conversation_id: UUID, artifact_id: UUID, component_id: str,
        token: Annotated[str, Depends(bearer)],
    ):
        return learning_artifacts.composition_source(
            token, conversation_id, artifact_id, component_id
        )

    @app.get(
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}/actions/{action_id}",
        response_model=(
            CompositionActionReceipt | LearningActionReceipt | DemoActionReceipt
            | ReviewActionReceipt
        ),
    )
    def learning_action_receipt(
        conversation_id: UUID, artifact_id: UUID, action_id: UUID,
        token: Annotated[str, Depends(bearer)],
    ):
        return learning_artifacts.action_receipt(token, conversation_id, artifact_id, action_id)

    @app.post(
        "/v2/conversations/{conversation_id}/learning-artifacts/{artifact_id}/actions",
        response_model=(
            CompositionActionReceipt | LearningActionReceipt | DemoActionReceipt
            | ReviewActionReceipt
        ),
    )
    def learning_artifact_action_v2(
        conversation_id: UUID, artifact_id: UUID, data: LearningArtifactActionV2,
        token: Annotated[str, Depends(bearer)],
    ):
        return learning_artifacts.action(token, conversation_id, artifact_id, data)

    @app.post(
        "/v1/model-connections/{connection_id}/tests",
        status_code=202,
        response_model=ModelConnectionTest,
    )
    def test_model_connection(
        connection_id: UUID,
        data: ModelConnectionTestInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return model_tests.submit(token, connection_id, key, data)

    @app.get("/v1/model-connection-tests/{test_id}", response_model=ModelConnectionTest)
    def model_connection_test(test_id: UUID, token: Annotated[str, Depends(bearer)]):
        return model_tests.get(token, test_id)

    @app.get("/v1/model-connection-tests", response_model=list[ModelConnectionTest])
    def model_connection_tests(token: Annotated[str, Depends(bearer)]):
        return model_tests.list(token)

    @app.get("/v1/model-configuration", response_model=ModelConfiguration)
    def model_configuration(token: Annotated[str, Depends(bearer)]):
        return models.configuration(token)

    @app.get("/v1/material-search-configuration", response_model=TavilyConfiguration)
    def tavily_configuration(token: Annotated[str, Depends(bearer)]):
        return models.tavily_configuration(token)

    @app.put("/v1/material-search-configuration", response_model=TavilyConfiguration)
    def save_tavily_configuration(
        data: TavilyConfigurationInput, token: Annotated[str, Depends(bearer)],
    ):
        return models.save_tavily(token, data)

    @app.post("/v1/model-presets/{preset_id}", status_code=201, response_model=ModelConnection)
    def apply_model_preset(
        preset_id: ModelPresetId,
        data: ModelPresetInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return models.apply_preset(token, key, preset_id, data)

    @app.post("/v1/model-connections/{connection_id}/use", response_model=ModelConfiguration)
    def use_model_connection(
        connection_id: UUID,
        data: ModelConnectionUseInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return models.use_connection(token, key, connection_id, data)

    @app.post("/v1/model-providers/custom", response_model=ModelConnection, status_code=201)
    def create_custom_model_provider(
        data: ModelCustomProviderInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return models.create_custom_provider(token, key, data)

    @app.get("/v1/model-connections", response_model=list[ModelConnection])
    def model_connections(token: Annotated[str, Depends(bearer)]):
        return models.configuration(token).connections

    @app.post("/v1/model-connections", status_code=201, response_model=ModelConnection)
    def create_model_connection(
        data: ModelConnectionInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return models.create_connection(token, key, data)

    @app.patch("/v1/model-connections/{connection_id}", response_model=ModelConnection)
    def patch_model_connection(
        connection_id: UUID,
        data: ModelConnectionPatch,
        token: Annotated[str, Depends(bearer)],
    ):
        return models.patch_connection(token, connection_id, data)

    @app.delete("/v1/model-connections/{connection_id}", response_model=ModelConnection)
    def delete_model_connection(
        connection_id: UUID,
        data: ModelConnectionDelete,
        token: Annotated[str, Depends(bearer)],
    ):
        return models.delete_connection(token, connection_id, data.expected_revision)

    @app.get("/v1/model-profiles", response_model=list[ModelProfile])
    def model_profiles(token: Annotated[str, Depends(bearer)]):
        return models.configuration(token).profiles

    @app.post("/v1/model-profiles", status_code=201, response_model=ModelProfile)
    def create_model_profile(
        data: ModelProfileInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
        assign_roles: bool = True,
    ):
        return models.save_profile(token, key, data, assign_roles=assign_roles)

    @app.patch("/v1/model-profiles/{profile_id}", response_model=ModelProfile)
    def patch_model_profile(
        profile_id: UUID,
        data: ModelProfilePatch,
        token: Annotated[str, Depends(bearer)],
        assign_roles: bool = True,
    ):
        return models.save_profile(token, "", data, profile_id, assign_roles=assign_roles)

    @app.put("/v1/model-role-mappings/{role}", response_model=ModelRoleMapping)
    def assign_model_role(
        role: ModelRole,
        data: ModelRoleAssignmentInput,
        token: Annotated[str, Depends(bearer)],
    ):
        return models.assign_role(token, role, data)

    @app.post("/v1/material-texts", status_code=201, response_model=DocumentVersion)
    def material_text(
        data: TextMaterialImport,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return materials.import_text(token, key, data)

    @app.post(
        "/v1/sources/{source_id}/material-compatibility",
        status_code=201,
        response_model=DocumentVersion,
    )
    def legacy_material(
        source_id: UUID, data: LegacyMaterialImport, token: Annotated[str, Depends(bearer)]
    ):
        return materials.import_legacy(token, source_id, data.expected_revision)

    @app.get("/v1/documents/{document_id}/versions/{revision}", response_model=DocumentVersion)
    def document_version(document_id: UUID, revision: int, token: Annotated[str, Depends(bearer)]):
        return materials.version(token, document_id, revision)

    @app.get(
        "/v1/documents/{document_id}/versions/{revision}/blocks", response_model=DocumentBlockPage
    )
    def document_blocks(
        document_id: UUID,
        revision: int,
        token: Annotated[str, Depends(bearer)],
        purpose: MaterialPurpose = "reference",
        after: int = Query(default=-1, ge=-1),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        return materials.blocks(token, document_id, revision, purpose, after, limit)

    @app.post(
        "/v1/documents/{document_id}/versions/{revision}/permissions",
        response_model=DocumentVersion,
    )
    def document_permission(
        document_id: UUID,
        revision: int,
        data: DocumentPermissionAction,
        token: Annotated[str, Depends(bearer)],
    ):
        return materials.revoke(token, document_id, revision, data)

    @app.post("/v1/material-bindings", status_code=201, response_model=MaterialBinding)
    def bind_material(
        data: MaterialBindingInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return materials.bind(token, key, data)

    @app.get("/v1/material-bindings/{binding_id}", response_model=MaterialBinding)
    def material_binding(
        binding_id: UUID,
        token: Annotated[str, Depends(bearer)],
        revision: int | None = Query(default=None, ge=1),
    ):
        return materials.binding(token, binding_id, revision)

    @app.get("/v1/material-bindings/{binding_id}/blocks", response_model=BoundMaterialPage)
    def bound_material_blocks(
        binding_id: UUID,
        token: Annotated[str, Depends(bearer)],
        expected_revision: int = Query(ge=1),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        return materials.bound_blocks(token, binding_id, expected_revision, offset, limit)

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

    @app.get(
        "/v1/conversations/{conversation_id}/material-progress",
        response_model=MaterialPreparationProgress,
    )
    def material_progress(
        conversation_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return tutor.material_progress(token, conversation_id)

    @app.post(
        "/v1/conversations/{conversation_id}/material-repair",
        response_model=MaterialRecoveryResult,
    )
    def repair_conversation_materials(
        conversation_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return MaterialRecoveryWorkflow(database, settings).repair(token, conversation_id)

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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        # Pydantic's default error input can echo a whole body, including API keys.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
                    for item in error.errors()
                ]
            },
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
            "material_storage_unavailable": 503,
            "material_original_missing": 409,
            "material_content_mismatch": 409,
            "material_file_limit": 413,
            "material_text_limit": 413,
            "material_block_limit": 413,
            "material_page_limit": 413,
            "material_pdf_limit": 413,
            "material_format_mismatch": 422,
            "material_encoding_required": 422,
            "material_encrypted": 422,
            "material_pdf_invalid": 422,
            "material_parser_timeout": 503,
            "material_parser_limit": 503,
            "material_parser_unavailable": 503,
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

    @app.post("/v1/local-sessions/refresh", response_model=Session)
    def refresh_local_session(token: Annotated[str, Depends(bearer)]) -> Session:
        return workflow.refresh_session(token)

    @app.delete("/v1/local-sessions/current", status_code=204)
    def end_local_session(token: Annotated[str, Depends(bearer)]) -> None:
        workflow.end_session(token)

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

    @app.patch("/v1/goals/{goal_id}", response_model=Goal)
    def rename_goal(goal_id: UUID, data: GoalRename, token: Annotated[str, Depends(bearer)]):
        return workflow.rename_goal(token, goal_id, data.title, data.motivation)

    @app.delete("/v1/goals/{goal_id}")
    def delete_goal(goal_id: UUID, token: Annotated[str, Depends(bearer)]):
        return workflow.delete_goal(token, goal_id)

    @app.get("/v1/goal-requests/{request_key}", response_model=Accepted)
    def goal_request_receipt(
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
        token: Annotated[str, Depends(bearer)],
    ) -> Accepted:
        return workflow.goal_request(token, request_key)

    @app.get("/v1/jobs/{job_id}", response_model=Job)
    def get_job(job_id: UUID, token: Annotated[str, Depends(bearer)]) -> Job:
        return workflow.job(token, job_id)

    @app.get("/v1/snapshot", response_model=Snapshot)
    def get_snapshot(token: Annotated[str, Depends(bearer)]) -> Snapshot:
        return workflow.snapshot(token)

    @app.get("/v1/tutor/availability", response_model=ModelAvailability)
    def tutor_availability(token: Annotated[str, Depends(bearer)]) -> ModelAvailability:
        return models.availability(token)

    @app.post("/v1/conversations", status_code=201, response_model=Conversation)
    def create_conversation(
        data: ConversationInput,
        token: Annotated[str, Depends(bearer)],
    ) -> Conversation:
        return tutor.conversation(token, data.goal_id)

    @app.delete(
        "/v1/conversations/{conversation_id}/recent-entry", response_model=Conversation,
    )
    def hide_conversation(conversation_id: UUID, token: Annotated[str, Depends(bearer)]):
        return tutor.hide_conversation(token, conversation_id)

    @app.get(
        "/v2/conversations/{conversation_id}/teaching-session",
        response_model=TeachingSession | None,
    )
    def teaching_session(conversation_id: UUID, token: Annotated[str, Depends(bearer)]):
        return TeachingSessionWorkflow(database).get(token, conversation_id)

    @app.post(
        "/v2/conversations/{conversation_id}/teaching-session/continue",
        response_model=TurnAccepted, status_code=202,
    )
    def continue_node(
        conversation_id: UUID, data: ContinueNode, token: Annotated[str, Depends(bearer)],
    ):
        return TeachingContinuationWorkflow(database, settings).continue_node(
            token, conversation_id, data,
        )

    @app.get(
        "/v1/conversations/{conversation_id}/teaching-intents",
        response_model=list[TeachingIntent],
    )
    def teaching_intents(
        conversation_id: UUID, token: Annotated[str, Depends(bearer)],
        before: UUID | None = None, limit: int = Query(default=20, ge=1, le=100),
    ):
        return TeachingContinuationWorkflow(database, settings).list(
            token, conversation_id, before, limit,
        )

    @app.post(
        "/v1/conversations/{conversation_id}/teaching-intents/{intent_id}/cancel",
        response_model=TeachingIntent,
    )
    def cancel_teaching_intent(
        conversation_id: UUID, intent_id: UUID, data: CancelTeachingIntent,
        token: Annotated[str, Depends(bearer)],
    ):
        return TeachingContinuationWorkflow(database, settings).cancel(
            token, conversation_id, intent_id, data,
        )

    @app.get(
        "/v1/conversations/{conversation_id}/teaching-intents/{intent_id}/cancel/{action_id}",
        response_model=TeachingIntent,
    )
    def teaching_intent_cancellation_receipt(
        conversation_id: UUID, intent_id: UUID, action_id: UUID,
        token: Annotated[str, Depends(bearer)],
    ):
        return TeachingContinuationWorkflow(database, settings).cancel_receipt(
            token, conversation_id, intent_id, action_id,
        )

    @app.post(
        "/v2/conversations/{conversation_id}/teaching-session/actions",
        response_model=TeachingSession,
    )
    def control_teaching_session(
        conversation_id: UUID, data: TeachingSessionCommand,
        token: Annotated[str, Depends(bearer)],
    ):
        return TeachingSessionWorkflow(database).command(token, conversation_id, data)

    @app.get(
        "/v2/conversations/{conversation_id}/teaching-session/actions/{action_id}",
        response_model=TeachingSession,
    )
    def teaching_session_receipt(
        conversation_id: UUID, action_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return TeachingSessionWorkflow(database).receipt(token, conversation_id, action_id)

    @app.get(
        "/v2/conversations/{conversation_id}/teaching-branches",
        response_model=list[TeachingBranch],
    )
    def teaching_branches(
        conversation_id: UUID, token: Annotated[str, Depends(bearer)],
        before: UUID | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        return TeachingSessionWorkflow(database).branches(token, conversation_id, before, limit)

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

    @app.get(
        "/v1/conversations/{conversation_id}/turn-requests/{request_key}",
        response_model=TurnAccepted,
    )
    def requested_turn(
        conversation_id: UUID, request_key: str,
        token: Annotated[str, Depends(bearer)],
    ):
        return tutor.requested_turn(token, conversation_id, request_key)

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

    @app.get(
        "/v1/plans/{plan_id}/confirmations/{revision}", response_model=PlanConfirmation,
    )
    def plan_confirmation(
        plan_id: UUID, revision: int, token: Annotated[str, Depends(bearer)],
    ):
        return tutor.plan_confirmation(token, plan_id, revision)

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
        return tutor.confirm_plan(
            token, plan_id, data.expected_revision, data.environment_requirements,
        )

    @app.get(
        "/v1/plans/{plan_id}/environment-requirements/{revision}",
        response_model=RouteEnvironmentManifest,
    )
    def route_environment_manifest(
        plan_id: UUID, revision: int, token: Annotated[str, Depends(bearer)],
    ):
        return execution_environments.route_manifest(token, plan_id, revision)

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

    @app.get("/v1/plans/{plan_id}/question-bank", response_model=list[BankNode])
    def question_bank(plan_id: UUID, token: Annotated[str, Depends(bearer)]):
        return items.question_bank(token, plan_id)

    @app.get("/v1/packs/{pack_id}/generation", response_model=GenerationReport)
    def pack_generation(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return items.generation(token, pack_id)

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

    @app.get("/v1/supply-requests/{key}", response_model=SupplyDemand)
    def supply_request_receipt(key: str, token: Annotated[str, Depends(bearer)]):
        return supply_demands.request_receipt(token, key)

    @app.get("/v1/supply-demands/{demand_id}", response_model=SupplyDemand)
    def get_supply_demand(demand_id: UUID, token: Annotated[str, Depends(bearer)]):
        return supply_demands.view(token, demand_id)

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
        "/v2/packs/{pack_id}/execution-submissions",
        response_model=PythonPracticeAttempt, status_code=202,
    )
    def practice_submission_v2(
        pack_id: UUID, data: PythonPracticeSubmission,
        token: Annotated[str, Depends(bearer)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    ):
        return python.submit_practice(token, pack_id, idempotency_key, data)

    @app.get(
        "/v2/packs/{pack_id}/execution-practice-attempts", response_model=PythonPracticeHistory,
    )
    def practice_history_v2(
        pack_id: UUID, token: Annotated[str, Depends(bearer)],
        slot: Annotated[str, Query(pattern=r"^(practice_[12]|remediation_1)$")],
        before: UUID | None = None, limit: int = Query(default=20, ge=1, le=100),
    ):
        return python.practice_history(token, pack_id, slot, before, limit)

    @app.get("/v2/python-practice-attempts/{attempt_id}", response_model=PythonPracticeAttempt)
    def practice_attempt_v2(attempt_id: UUID, token: Annotated[str, Depends(bearer)]):
        return python.practice_attempt(token, attempt_id)

    @app.get("/v2/python-practice-requests/{key}", response_model=PythonPracticeAttempt)
    def practice_request_v2(key: str, token: Annotated[str, Depends(bearer)]):
        return python.practice_request(token, key)

    @app.post(
        "/v2/python-practice-attempts/{attempt_id}/cancel", response_model=PythonPracticeAttempt,
    )
    def cancel_practice_v2(attempt_id: UUID, token: Annotated[str, Depends(bearer)]):
        return python.cancel_practice(token, attempt_id)

    @app.get("/v2/packs/{pack_id}/program-practice", response_model=list[PublicProgramQuestion])
    def program_practice(
        pack_id: UUID, token: Annotated[str, Depends(bearer)], remediation: bool = False,
    ):
        return programs.training(token, pack_id, remediation=remediation)

    @app.post(
        "/v2/packs/{pack_id}/program-submissions",
        response_model=ProgramPracticeAttempt, status_code=202,
    )
    def program_submission(
        pack_id: UUID, data: ProgramPracticeSubmission,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)],
    ):
        return programs.submit_practice(token, pack_id, key, data)

    @app.get(
        "/v2/packs/{pack_id}/program-practice-attempts", response_model=ProgramPracticeHistory,
    )
    def program_history(
        pack_id: UUID, token: Annotated[str, Depends(bearer)],
        slot: Annotated[str, Query(pattern=r"^(practice_[12]|remediation_1)$")],
        before: UUID | None = None, limit: int = Query(default=20, ge=1, le=100),
    ):
        return programs.history(token, pack_id, slot, before, limit)

    @app.get("/v2/program-practice-attempts/{attempt_id}", response_model=ProgramPracticeAttempt)
    def program_attempt(attempt_id: UUID, token: Annotated[str, Depends(bearer)]):
        return programs.attempt(token, attempt_id)

    @app.get("/v2/program-practice-requests/{key}", response_model=ProgramPracticeAttempt)
    def program_request(key: str, token: Annotated[str, Depends(bearer)]):
        return programs.request(token, key)

    @app.post(
        "/v2/program-practice-attempts/{attempt_id}/cancel", response_model=ProgramPracticeAttempt,
    )
    def cancel_program(attempt_id: UUID, token: Annotated[str, Depends(bearer)]):
        return programs.cancel(token, attempt_id)

    @app.post("/v2/packs/{pack_id}/program-review", response_model=PackSummary)
    def program_review(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return programs.continue_review(token, pack_id)

    @app.post(
        "/v2/packs/{pack_id}/program-gate-requests", response_model=GateSummary, status_code=202,
    )
    def request_program_gate(
        pack_id: UUID, data: GateRequest, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return concept_gates.request(token, pack_id, key, data, required_kind="program")

    @app.get(
        "/v2/packs/{pack_id}/program-gate-requests/{request_key}", response_model=GateSummary,
    )
    def program_gate_request_receipt(
        pack_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return concept_gates.request_receipt(token, pack_id, request_key)

    @app.post(
        "/v2/gates/{gate_id}/program-submissions", response_model=GateView, status_code=202,
    )
    def submit_program_gate(
        gate_id: UUID, data: ProgramGateSubmission, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return programs.submit_gate(token, gate_id, key, data)

    @app.get(
        "/v2/gates/{gate_id}/program-submissions/{request_key}", response_model=GateView,
    )
    def program_gate_submission_receipt(
        gate_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return programs.gate_submission_receipt(token, gate_id, request_key)

    @app.post(
        "/v2/program-attempts/{attempt_id}/transfer-requests",
        response_model=TransferSummary, status_code=202,
    )
    def request_program_transfer(
        attempt_id: UUID, data: TransferRequest, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return transfers.request_program(token, attempt_id, key, data)

    @app.post(
        "/v2/transfers/{transfer_id}/program-submissions",
        response_model=TransferView, status_code=202,
    )
    def submit_program_transfer(
        transfer_id: UUID, data: ProgramTransferSubmission,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return transfers.submit_program(token, transfer_id, key, data)

    @app.post(
        "/v2/program-attempts/{attempt_id}/supply-demands",
        response_model=SupplyDemand, status_code=202,
    )
    def request_program_supply(
        attempt_id: UUID, data: SupplyRequest, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return supply_demands.request_program(token, attempt_id, key, data)

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

    @app.get("/v1/transfer-requests/{key}", response_model=TransferSummary)
    def transfer_request_receipt(key: str, token: Annotated[str, Depends(bearer)]):
        return transfers.request_receipt(token, key)

    @app.get("/v1/transfers/{transfer_id}", response_model=TransferView)
    def get_transfer(transfer_id: UUID, token: Annotated[str, Depends(bearer)]) -> TransferView:
        return transfers.view(token, transfer_id)

    @app.get("/v1/transfers/{transfer_id}/opening", response_model=TransferView)
    def transfer_opening_receipt(
        transfer_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return transfers.action_receipt(token, transfer_id, "open")

    @app.get("/v1/transfers/{transfer_id}/submissions/{key}", response_model=TransferView)
    def transfer_submission_receipt(
        transfer_id: UUID, key: str, token: Annotated[str, Depends(bearer)],
    ):
        return transfers.action_receipt(token, transfer_id, "submit", key)

    @app.get("/v1/transfers/{transfer_id}/cancellation", response_model=TransferView)
    def transfer_cancellation_receipt(
        transfer_id: UUID, token: Annotated[str, Depends(bearer)],
    ):
        return transfers.action_receipt(token, transfer_id, "cancel")

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

    @app.get("/v1/gates/{gate_id}", response_model=GateView)
    @app.get("/v1/concept-gates/{gate_id}", response_model=GateView)
    def get_concept_gate(gate_id: UUID, token: Annotated[str, Depends(bearer)]) -> GateView:
        return concept_gates.view(token, gate_id)

    @app.post("/v1/gates/{gate_id}/start", response_model=GateView)
    @app.post("/v1/concept-gates/{gate_id}/start", response_model=GateView)
    def start_concept_gate(gate_id: UUID, token: Annotated[str, Depends(bearer)]) -> GateView:
        return concept_gates.start(token, gate_id)

    @app.get("/v1/gates/{gate_id}/start-receipt", response_model=GateView)
    def gate_start_receipt(gate_id: UUID, token: Annotated[str, Depends(bearer)]):
        return concept_gates.start_receipt(token, gate_id)

    @app.get("/v1/gates/{gate_id}/cancellation", response_model=GateView)
    def gate_cancellation_receipt(gate_id: UUID, token: Annotated[str, Depends(bearer)]):
        return concept_gates.cancellation_receipt(token, gate_id)

    @app.get("/v1/packs/{pack_id}/gate-requests/{request_key}", response_model=GateSummary)
    @app.get(
        "/v1/packs/{pack_id}/execution-gate-requests/{request_key}", response_model=GateSummary,
    )
    def legacy_gate_request_receipt(
        pack_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return concept_gates.request_receipt(token, pack_id, request_key)

    @app.get(
        "/v1/concept-gates/{gate_id}/submissions/{request_key}", response_model=GateView,
    )
    def concept_gate_submission_receipt(
        gate_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return concept_gates.submission_receipt(
            token, gate_id, request_key, policy="concept-gate.v1",
        )

    @app.get(
        "/v1/concept-gates/{gate_id}/execution-submissions/{request_key}", response_model=GateView,
    )
    def python_gate_submission_receipt(
        gate_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return concept_gates.submission_receipt(
            token, gate_id, request_key, policy="python-io-gate.v1",
        )

    @app.post("/v1/concept-gates/{gate_id}/submissions", response_model=GateView)
    def submit_concept_gate(
        gate_id: UUID,
        data: GateSubmission,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> GateView:
        return concept_gates.submit(token, gate_id, key, data)

    @app.post("/v1/gates/{gate_id}/cancel", response_model=GateView)
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

    @app.get("/v2/packs/{pack_id}/response-practice", response_model=ResponsePracticeSet)
    def response_practice(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return items.response_practice(token, pack_id)

    @app.post("/v2/packs/{pack_id}/responses", response_model=ResponseResult)
    def submit_response(
        pack_id: UUID, data: ResponseSubmission, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return items.respond(token, pack_id, key, data)

    @app.get("/v2/packs/{pack_id}/response-results", response_model=list[ResponseResult])
    def response_results(pack_id: UUID, token: Annotated[str, Depends(bearer)]):
        return items.response_results(token, pack_id)

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

    @app.get("/v1/review-activities", response_model=list[ReviewActivity])
    def review_activities(
        token: Annotated[str, Depends(bearer)], conversation_id: UUID | None = None,
    ):
        return reviews.list(token, conversation_id)

    @app.get("/v1/review-activities/{activity_id}", response_model=ReviewActivity)
    def review_activity(activity_id: UUID, token: Annotated[str, Depends(bearer)]):
        return reviews.get(token, activity_id)

    @app.post("/v1/review-activities/{activity_id}/present", response_model=ReviewActivity)
    def present_review_activity(
        activity_id: UUID, data: PresentReview, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return reviews.present(token, activity_id, key, data)

    @app.post("/v1/review-activities/{activity_id}/responses", response_model=ReviewActivity)
    def respond_review_activity(
        activity_id: UUID, data: ReviewInput, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return reviews.respond(token, activity_id, key, data)

    @app.post("/v1/review-activities/{activity_id}/cancel", response_model=ReviewActivity)
    def cancel_review_activity(
        activity_id: UUID, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return reviews.cancel(token, activity_id, key)

    @app.get(
        "/v1/review-activities/{activity_id}/commands/{request_key}",
        response_model=ReviewActivity | None,
    )
    def review_activity_receipt(
        activity_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return reviews.receipt(token, activity_id, request_key)

    @app.get("/v1/reviews/{card_id}/logs", response_model=list[ReviewLog])
    def review_logs(card_id: UUID, token: Annotated[str, Depends(bearer)]):
        return reviews.logs(token, card_id)

    @app.get("/v1/learning-evidence", response_model=LearningEvidenceProjection)
    def get_learning_evidence(
        token: Annotated[str, Depends(bearer)],
        plan_id: UUID | None = None,
        node_key: str | None = Query(default=None, min_length=1, max_length=60),
    ):
        return learning_evidence.get(token, plan_id, node_key)

    @app.get(
        "/v1/conversations/{conversation_id}/proactive-preference",
        response_model=ProactivePreference | None,
    )
    def proactive_preference(conversation_id: UUID, token: Annotated[str, Depends(bearer)]):
        return proactive_teaching.preference(token, conversation_id)

    @app.post(
        "/v1/conversations/{conversation_id}/proactive-preference",
        response_model=ProactivePreference,
    )
    def set_proactive_preference(
        conversation_id: UUID, data: ProactivePreferenceInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return proactive_teaching.set_preference(token, conversation_id, key, data)

    @app.get(
        "/v1/conversations/{conversation_id}/proactive-preference/commands/{request_key}",
        response_model=ProactivePreference,
    )
    def proactive_preference_receipt(
        conversation_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return proactive_teaching.preference_receipt(token, conversation_id, request_key)

    @app.get("/v1/execution-environments", response_model=ExecutionEnvironments)
    def execution_environment_snapshot(token: Annotated[str, Depends(bearer)]):
        return execution_environments.snapshot(token)

    @app.post("/v1/environment-demands", response_model=EnvironmentDemand, status_code=201)
    def request_execution_environment(
        data: EnvironmentDemandInput, token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return execution_environments.request(token, key, data)

    @app.get("/v1/environment-demand-requests/{request_key}", response_model=EnvironmentDemand)
    def execution_environment_request_receipt(
        token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return execution_environments.request_receipt(token, request_key)

    @app.post(
        "/v1/environment-demands/{demand_id}/decisions", response_model=EnvironmentDecision,
    )
    def decide_execution_environment(
        demand_id: UUID, data: EnvironmentDecisionInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return execution_environments.decide(token, demand_id, key, data)

    @app.get(
        "/v1/environment-demands/{demand_id}/decisions/{request_key}",
        response_model=EnvironmentDecision,
    )
    def execution_environment_decision_receipt(
        demand_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return execution_environments.decision_receipt(token, demand_id, request_key)

    @app.post("/v1/environment-demands/{demand_id}/rebuild", response_model=EnvironmentDemand)
    def rebuild_execution_environment(
        demand_id: UUID, data: EnvironmentRebuildInput,
        token: Annotated[str, Depends(bearer)],
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ):
        return execution_environments.rebuild(token, demand_id, key, data)

    @app.get(
        "/v1/environment-demands/{demand_id}/rebuilds/{request_key}",
        response_model=EnvironmentDemand,
    )
    def execution_environment_rebuild_receipt(
        demand_id: UUID, token: Annotated[str, Depends(bearer)],
        request_key: Annotated[str, Path(min_length=8, max_length=128)],
    ):
        return execution_environments.rebuild_receipt(token, demand_id, request_key)

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

    @app.post("/internal/environment-engine", dependencies=[Depends(runner_auth)])
    def observe_execution_engine(data: EngineObservationInput):
        execution_environments.observe_engine(data)
        return {"recorded": True}

    @app.post(
        "/internal/environment-preparations/claim",
        response_model=EnvironmentPreparationClaim | None,
        dependencies=[Depends(runner_auth)],
    )
    def claim_environment_preparation(data: EnvironmentPreparationClaimInput):
        return execution_environments.claim(data)

    @app.post(
        "/internal/environment-preparations/{job_id}/progress",
        dependencies=[Depends(runner_auth)],
    )
    def environment_preparation_progress(job_id: UUID, data: EnvironmentPreparationProgress):
        return execution_environments.progress(job_id, data)

    @app.post(
        "/internal/environment-preparations/{job_id}/report",
        response_model=EnvironmentRelease | None,
        dependencies=[Depends(runner_auth)],
    )
    def environment_preparation_report(job_id: UUID, data: EnvironmentPreparationReport):
        return execution_environments.report(job_id, data)

    @app.post(
        "/internal/environment-releases/{release_id}/unavailable",
        dependencies=[Depends(runner_auth)],
    )
    def environment_release_unavailable(release_id: UUID, data: EnvironmentReleaseUnavailable):
        return execution_environments.unavailable(release_id, data)

    @app.post(
        "/internal/environment-releases/{release_id}/verify",
        dependencies=[Depends(runner_auth)],
    )
    def verify_environment_release(release_id: UUID, data: EnvironmentReleaseVerificationInput):
        return execution_environments.verify_release(release_id, data)

    @app.post(
        "/internal/executions/claim",
        response_model=ExecutionClaim | ProgramExecutionClaim | None,
        dependencies=[Depends(runner_auth)],
    )
    def runner_claim(data: RunnerClaim) -> ExecutionClaim | ProgramExecutionClaim | None:
        return journey.claim(
            data.runner_id, data.program_environments, example_terminal=data.example_terminal,
        )

    @app.post("/internal/executions/{job_id}/terminal", dependencies=[Depends(runner_auth)])
    def example_terminal_exchange(job_id: UUID, data: ExampleTerminalExchange):
        return ExampleRuns(database).exchange(job_id, data)

    @app.post("/internal/executions/{job_id}/verify", dependencies=[Depends(runner_auth)])
    def verify_execution(job_id: UUID, data: ExecutionVerificationInput):
        return journey.verify_execution(job_id, data)

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
                    # Only an accepted public reply is sent to the presentation stream.
                    text = event.payload.reply_text
                    if event.event_type == "tutor.succeeded" and text:
                        for offset in range(0, len(text), 64):
                            delta = {
                                "sequence": event.sequence,
                                "event_type": "tutor.reply_delta",
                                "payload": {
                                    "conversation_id": str(event.payload.conversation_id),
                                    "turn_id": str(event.payload.turn_id),
                                    "reply_text": text[offset:offset + 64],
                                    "offset": offset,
                                },
                            }
                            yield (
                                f"event: tutor.reply_delta\n"
                                f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
                            )
                            await asyncio.sleep(0.012)
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
