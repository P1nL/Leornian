"""Server-owned content references; presentation and action revisions are distinct."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_serializer, model_validator

from leornian.modules.assessment.contracts import (
    GraduatedHint,
    PracticeAssistanceReceipt,
    PracticeHintReceipt,
    ProgramPracticeAttempt,
    ProgramPracticeHistory,
    PythonPracticeAttempt,
    PythonPracticeHistory,
    ResponseResult,
    Submission,
)
from leornian.modules.execution.contracts import ProjectLanguage
from leornian.modules.execution.example_contracts import ExampleRunSurface
from leornian.modules.item_bank.contracts import ChoiceResult, PythonQuestion, ResponseValue
from leornian.modules.knowledge.contracts import DocumentBlock, DocumentPage, SourceRef
from leornian.modules.learning.contracts import MaterialCitation
from leornian.modules.tutor.artifact_templates import ExampleWorkspace
from leornian.modules.tutor.composition_catalog import ComponentName, CompositionState, Key, Label
from leornian.modules.tutor.composition_v2_contracts import AlgorithmInput, LearningCompositionV2
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.modules.tutor.demo_contracts import (
    DemoActionReceipt,
    DemoBinding,
    DemoCompleteAction,
    DemoEventAction,
    DemoStartAction,
    DemoView,
)
from leornian.modules.tutor.learning_artifact_contracts import (
    CancelAction,
    LearningActionBase,
    LearningActionReceipt,
    LearningCandidateOption,
    RespondAction,
    RespondPayload,
    RunAction,
)
from leornian.modules.tutor.program_interaction_contracts import (
    CompositionProgramRunAction,
    ProgramCandidateOption,
)
from leornian.modules.tutor.response_interaction_contracts import ResponseCandidateOption
from leornian.modules.tutor.review_contracts import (
    CompleteReviewAction,
    ReviewActionReceipt,
    ReviewReportView,
)
from leornian.shared_kernel.contracts import Contract


class CompositionContentRef(Contract):
    owner: Literal["tutor"] = "tutor"
    id: UUID
    revision: int = Field(ge=1)
    public_identity: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompositionPresentation(Contract):
    type: Literal["learning_composition"] = "learning_composition"
    definition: LearningCompositionV2
    example_workspace: ExampleWorkspace | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class CompositionOwnerBinding(Contract):
    component_id: Key
    source: Annotated[
        LearningCandidateOption | ResponseCandidateOption | ProgramCandidateOption,
        Field(discriminator="kind"),
    ]
    assistance_profile: Literal["practice-direct-answer.v1"] | None = None
    hint_profile: Literal["practice-hints.v1"] | None = None

    @model_serializer(mode="wrap")
    def omit_unavailable_assistance(self, handler):
        data = handler(self)
        if self.assistance_profile is None:
            data.pop("assistance_profile", None)
            data.pop("assistance_receipt", None)
        if self.hint_profile is None:
            data.pop("hint_profile", None)
            data.pop("hint_receipts", None)
            data.pop("next_hint_level", None)
        return data


class SubmittedCodeFinding(Contract):
    line: int = Field(ge=1, le=12000)
    source_line: str = Field(
        max_length=12000, pattern=r"^[^\r\n]*$", description="Exact source line without CR/LF."
    )
    content: str = Field(min_length=1, max_length=1800)


class SubmittedCodeReviewBinding(Contract):
    profile_version: Literal[
        "submitted-code-review.v1", "submitted-code-review.v2",
    ] = "submitted-code-review.v1"
    component_id: Key
    evaluation_id: UUID
    attempt: PythonPracticeAttempt
    task: PythonQuestion
    recorded_correct: bool
    findings: list[SubmittedCodeFinding] = Field(max_length=40)


class CompositionCandidate(Contract):
    id: UUID
    conversation_id: UUID
    kind: Literal["learning_composition"] = "learning_composition"
    focus: TeachingFocus
    content_ref: CompositionContentRef
    title: str
    presentation: CompositionPresentation
    owner_bindings: list[CompositionOwnerBinding] = Field(default_factory=list)
    review_bindings: list[SubmittedCodeReviewBinding] = Field(default_factory=list)
    demo_bindings: list[DemoBinding] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def omit_empty_bindings(self, handler):
        data = handler(self)
        if not self.owner_bindings:
            data.pop("owner_bindings", None)
        if not self.review_bindings:
            data.pop("review_bindings", None)
        if not self.demo_bindings:
            data.pop("demo_bindings", None)
        return data


class PrepareComposition(Contract):
    command_key: str = Field(min_length=8, max_length=128)
    definition: LearningCompositionV2


class PrepareCodeReviewComposition(PrepareComposition):
    code_component_id: Key
    findings: list[SubmittedCodeFinding] = Field(max_length=40)


class CompositionOwnerProposal(Contract):
    component_id: Key
    candidate_id: UUID


class PreparePracticeComposition(PrepareComposition):
    owner_bindings: list[CompositionOwnerProposal] = Field(min_length=1, max_length=8)


class CompositionHintBinding(Contract):
    component_id: Key
    hints: tuple[GraduatedHint, GraduatedHint, GraduatedHint]

    @model_validator(mode="after")
    def ordered_distinct(self):
        if tuple(hint.level for hint in self.hints) != (1, 2, 3) or len({
            hint.text.strip().casefold() for hint in self.hints
        }) != 3:
            raise ValueError("Supply distinct conceptual, strategic and next-step hints in order.")
        return self


class PrepareHintComposition(PreparePracticeComposition):
    hint_bindings: list[CompositionHintBinding] = Field(min_length=1, max_length=8)


class PrepareDemoComposition(PrepareComposition):
    demo_components: list[Key] = Field(min_length=1, max_length=8)
    owner_bindings: list[CompositionOwnerProposal] = Field(default_factory=list, max_length=8)
    hint_bindings: list[CompositionHintBinding] = Field(default_factory=list, max_length=8)


class DemoWireComponent(Contract):
    id: Key
    component: ComponentName
    props: dict[str, JsonValue] = Field(
        description="Read this component's exact props with get_learning_component_contracts. "
        "The server still validates the complete closed component and relational schema.",
    )


class DemoWireDefinition(Contract):
    schema_version: Literal["learning_composition.v2"]
    title: Label
    layout: Literal["stack", "split"] = "stack"
    states: dict[Key, CompositionState] = Field(default_factory=dict, max_length=32)
    inputs: dict[Key, AlgorithmInput] = Field(default_factory=dict, max_length=12)
    components: list[DemoWireComponent] = Field(min_length=1, max_length=40)


class PrepareDemoWire(Contract):
    """Compact wire index only; PrepareDemoComposition remains the actual validator."""

    command_key: str = Field(min_length=8, max_length=128)
    definition: DemoWireDefinition
    demo_components: list[Key] = Field(min_length=1, max_length=8)
    owner_bindings: list[CompositionOwnerProposal] = Field(default_factory=list, max_length=8)
    hint_bindings: list[CompositionHintBinding] = Field(default_factory=list, max_length=8)


class PreparedComposition(Contract):
    status: Literal["completed"] = "completed"
    candidate: CompositionCandidate
    approval: Literal["requires_checked_delivery"] = "requires_checked_delivery"
    example_runners: dict[str, list[ProjectLanguage]] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class PreparedHintComposition(PreparedComposition):
    hint_bindings: list[CompositionHintBinding]


class ReadComponentContracts(Contract):
    names: list[ComponentName] = Field(min_length=1, max_length=31)


class CompositionArtifactSummary(Contract):
    schema_version: Literal["learning_artifact.v2"] = "learning_artifact.v2"
    id: UUID
    conversation_id: UUID
    source_turn_id: UUID
    timeline_item_id: UUID
    revision: int
    kind: Literal["learning_composition"] = "learning_composition"
    state: Literal["ready", "running", "completed", "cancelled", "superseded"]
    created_at: datetime


class CompositionArtifactView(CompositionArtifactSummary):
    title: str
    practice_only: bool = False
    focus: TeachingFocus
    content_ref: CompositionContentRef
    presentation: CompositionPresentation
    allowed_actions: list[Literal["cancel"]]
    component_bindings: list["CompositionComponentView"] = Field(default_factory=list)
    review_bindings: list[SubmittedCodeReviewBinding] = Field(default_factory=list)
    demo_bindings: list[DemoView] = Field(default_factory=list)
    review_reports: list[ReviewReportView] = Field(default_factory=list)
    example_runners: dict[str, list[ProjectLanguage]] = Field(
        default_factory=dict, exclude_if=lambda value: not value,
    )
    example_run_surface: ExampleRunSurface | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )

    @model_serializer(mode="wrap")
    def omit_empty_components(self, handler):
        data = handler(self)
        if not self.component_bindings:
            data.pop("component_bindings", None)
        if not self.review_bindings:
            data.pop("review_bindings", None)
        if not self.demo_bindings:
            data.pop("demo_bindings", None)
        if not self.review_reports:
            data.pop("review_reports", None)
        return data


class CompositionComponentView(CompositionOwnerBinding):
    state: Literal["ready", "running", "completed", "cancelled"]
    action_id: UUID | None = None
    allowed_actions: list[Literal[
        "respond", "run", "retry", "cancel_run", "request_direct_answer", "request_hint",
    ]]
    result: (
        ChoiceResult | PythonPracticeAttempt | ResponseResult | ProgramPracticeAttempt | None
    ) = None
    attempts: PythonPracticeHistory | ProgramPracticeHistory | None = None
    assistance_receipt: PracticeAssistanceReceipt | None = None
    hint_receipts: list[PracticeHintReceipt] = Field(default_factory=list)
    next_hint_level: Literal[1, 2, 3] | None = None


class CompositionRunPayload(Submission):
    previous_attempt_id: UUID | None = None
    retry: bool = False


class CompositionRunAction(LearningActionBase):
    action: Literal["run_component"]
    component_id: Key
    payload: CompositionRunPayload


class CompositionRespondAction(LearningActionBase):
    action: Literal["respond_component"]
    component_id: Key
    payload: RespondPayload


class CompositionAnswerAction(LearningActionBase):
    action: Literal["answer_component"]
    component_id: Key
    payload: ResponseValue


class CompositionCancelRunAction(LearningActionBase):
    action: Literal["cancel_component_run"]
    component_id: Key
    expected_attempt_id: UUID


class CompositionDirectAnswerAction(LearningActionBase):
    action: Literal["request_direct_answer"]
    component_id: Key


class CompositionHintAction(LearningActionBase):
    action: Literal["request_hint"]
    component_id: Key
    level: Literal[1, 2, 3]


CompositionPracticeAction = Annotated[
    CompositionRunAction | CompositionRespondAction | CompositionCancelRunAction
    | CompositionAnswerAction | CompositionProgramRunAction | CompositionDirectAnswerAction
    | CompositionHintAction,
    Field(discriminator="action"),
]
LearningArtifactActionV2 = Annotated[
    RespondAction | RunAction | CancelAction
    | CompositionRunAction | CompositionRespondAction | CompositionCancelRunAction
    | CompositionAnswerAction | CompositionProgramRunAction | CompositionDirectAnswerAction
    | CompositionHintAction | DemoStartAction | DemoEventAction | DemoCompleteAction
    | CompleteReviewAction,
    Field(discriminator="action"),
]


class CompositionActionReceipt(LearningActionReceipt):
    schema_version: Literal["learning_action.v2"] = "learning_action.v2"
    component_id: Key
    component_state: Literal["ready", "running", "completed", "cancelled"]


def parse_action_receipt(data):
    return (
        ReviewActionReceipt if data.get("schema_version") == "learning_review_action.v1"
        else DemoActionReceipt if data.get("schema_version") == "learning_demo_action.v1"
        else CompositionActionReceipt if data.get("schema_version") == "learning_action.v2"
        else LearningActionReceipt
    ).model_validate(data)


class CompositionSourceView(Contract):
    component_id: str
    citation: MaterialCitation | SourceRef
    title: str
    block: DocumentBlock | None = None
    location: DocumentPage | None = None
    excerpt: str | None = None
    valid_until: datetime | None = None
