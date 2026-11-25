"""Static, versioned tool contracts. Business execution belongs to bootstrap Facades."""

import json
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.execution.environment_contracts import (
    EnvironmentDemandToolReceipt,
    ExecutionEnvironmentSnapshot,
    GetExecutionEnvironments,
    RequestExecutionEnvironment,
)
from leornian.modules.tutor.artifact_contracts import ArtifactSection, ArtifactSummary
from leornian.modules.tutor.artifact_templates import PrepareLearningTemplate
from leornian.modules.tutor.composition_delivery_contracts import (
    PrepareCodeReviewComposition,
    PrepareComposition,
    PreparedComposition,
    PrepareDemoComposition,
    PrepareDemoWire,
    PreparedHintComposition,
    PrepareHintComposition,
    PreparePracticeComposition,
    ReadComponentContracts,
)
from leornian.modules.tutor.learning_artifact_contracts import LearningCandidateList
from leornian.modules.tutor.practice_supply_contracts import (
    PracticeSupplyStatus,
    ProgramSupplyStatus,
    QueuedPracticeSupply,
    ReadPracticeSupply,
    RequestPracticeSupply,
    RequestProgramSupply,
)
from leornian.modules.tutor.program_interaction_contracts import ProgramCandidateList
from leornian.modules.tutor.response_interaction_contracts import ResponseCandidateList
from leornian.shared_kernel.contracts import Contract


class EmptyArguments(Contract):
    pass


NODE_WEB_TOOL = "lookup_public_teaching_fact"


class PublicTeachingQuestion(Contract):
    excerpts: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(
        min_length=1, max_length=4, description=(
            "Copy the public question from the current learner message. Keep the exact feature "
            "(including the parameter), version and requested source together. If separated, "
            "copy multiple verbatim excerpts. An isolated 'it' or '它' loses the subject. "
            "Omit personal details, code listings and private reading passages."
        ),
    )
    symbol: str | None = Field(
        default=None, max_length=80, pattern=r"^[\w.:\-]+$",
        description="Use only for an API name from earlier teaching missing from the excerpts.",
    )


class ArtifactPage(Contract):
    before: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ArtifactRead(Contract):
    artifact_id: UUID
    revision: int = Field(ge=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=5, ge=1, le=20)


class ArtifactCreate(Contract):
    command_key: str = Field(min_length=8, max_length=128)
    instruction: str = Field(min_length=1, max_length=4000)


class ArtifactRevise(ArtifactCreate):
    artifact_id: UUID
    expected_revision: int = Field(ge=1)


class ToolProblem(Contract):
    status: Literal["rejected", "conflict", "waiting_dependency", "unknown"]
    code: str
    message: str | None = None
    fields: list[dict[str, str]] = []
    next_action: str


class ArtifactListResult(Contract):
    status: Literal["completed"]
    items: list[ArtifactSummary]
    next_before: UUID | None


class ComponentDirectoryResult(Contract):
    status: Literal["completed"]
    schema_version: Literal["learning_composition.v2"]
    components: list[dict]


class ArtifactReadResult(Contract):
    status: Literal["completed"]
    artifact_id: UUID
    revision: int
    title: str
    sections: list[ArtifactSection]
    section_count: int
    offset: int
    next_offset: int | None
    code_is_inert: Literal[True]


class ArtifactQueuedResult(Contract):
    status: Literal["accepted"]
    job_id: UUID
    artifact_id: UUID
    expected_revision: int
    message: str


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type[Contract]
    effect: Literal["read", "enqueue"]
    parallel_safe: bool = False
    version: int = 1
    result: type[Contract] | None = None  # Legacy context v1 preserves its original shape.
    wire_arguments: type[Contract] | None = None

    def wire(self, *, shared_composition=False):
        schema = (self.wire_arguments or self.arguments).model_json_schema()
        if shared_composition and issubclass(self.arguments, PrepareComposition):
            schema["properties"]["definition"] = {
                "type": "object",
                "description": "Use the complete definition from prepare_learning_composition. "
                "Read exact named ports with get_learning_component_contracts.",
            }
            definitions = schema.pop("$defs", {})
            kept = {}

            def keep_refs(value):
                if isinstance(value, list):
                    for entry in value:
                        keep_refs(entry)
                elif isinstance(value, dict):
                    ref = value.get("$ref", "").removeprefix("#/$defs/")
                    if ref in definitions and ref not in kept:
                        kept[ref] = definitions[ref]
                        keep_refs(kept[ref])
                    for entry in value.values():
                        keep_refs(entry)

            keep_refs(schema)
            if kept:
                schema["$defs"] = kept
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    def validate(self, arguments):
        return self.arguments.model_validate_json(
            arguments if isinstance(arguments, str) else json.dumps(arguments), strict=True
        )


DEFINITIONS = (
    ToolDefinition(
        "learning_get_context",
        "Refresh only the server-bound learning goal/node, admitted sources and public feedback. "
        "Read-only; cannot select identities, execute, publish, grade or update progress.",
        EmptyArguments,
        "read",
    ),
    ToolDefinition(
        "list_artifacts",
        "List accepted teaching artifacts in this exact goal/node scope. Metadata only; "
        "use returned exact id/revision with read_artifact. Pages do not imply full coverage.",
        ArtifactPage,
        "read",
        True,
        result=ArtifactListResult,
    ),
    ToolDefinition(
        "read_artifact",
        "Read a page of an immutable accepted teaching artifact revision in the bound scope. "
        "Follow next_offset until null when full content is required. Code is inert.",
        ArtifactRead,
        "read",
        True,
        result=ArtifactReadResult,
    ),
    ToolDefinition(
        "request_teaching_artifact",
        "Queue a checked teaching note/example document in the current scope. Reuse command_key "
        "for the same intent; a different intent needs a different key. accepted means queued, "
        "NOT delivered. It uses the native Runtime after this conversation turn finishes. "
        "No executable HTML, grading, publication or progress authority.",
        ArtifactCreate,
        "enqueue",
        result=ArtifactQueuedResult,
    ),
    ToolDefinition(
        "request_artifact_revision",
        "Queue a new checked revision without overwriting history. Read the artifact first; "
        "expected_revision must match its current head. Reuse command_key for the same intent. "
        "A conflict requires rereading, not silently rebasing. accepted is not delivery.",
        ArtifactRevise,
        "enqueue",
        result=ArtifactQueuedResult,
    ),
    ToolDefinition(
        "list_learning_artifact_candidates",
        "List legal ordinary practice candidates for this exact node. Public content only. "
        "Read all needed pages using next_before (a pack cursor). Handles do not authorize "
        "execution, grading or exams. A final reply may use one returned item.id as exact_handle "
        "with intent introduce_only; the server revalidates it before checked delivery.",
        ArtifactPage,
        "read",
        result=LearningCandidateList,
    ),
    ToolDefinition(
        "get_learning_component_contracts",
        "Read named component data/state ports from the authoritative composition directory. "
        "No permission or execution is granted. Do not invent props or callbacks.",
        ReadComponentContracts,
        "read",
        result=ComponentDirectoryResult,
    ),
    ToolDefinition(
        "prepare_learning_composition",
        "Prepare a public, inert learning composition in this exact teaching scope. "
        "Use the closed component/state contracts; shared state links compatible ports. "
        "This returns an exact candidate handle, NOT delivery, scoring or execution. "
        "Choose the returned candidate.id in the final interaction for independent review. "
        "Reusing command_key requires identical content and scope.",
        PrepareComposition,
        "enqueue",
        result=PreparedComposition,
    ),
    ToolDefinition(
        "prepare_learning_template",
        "Use a ready-made learning artifact for an original example, comparison, preview, "
        "walkthrough or private local activity. Supply the content, not a component tree. "
        "For a code workspace give the file, language and optional example input values. "
        "There is no published question, submission or grade. Use the original candidate "
        "instead when teaching a specific published exercise. Select the returned candidate.id "
        "for checked delivery; this tool does not run the example.",
        PrepareLearningTemplate, "enqueue", result=PreparedComposition,
    ),
    ToolDefinition(
        "prepare_learning_practice_composition",
        "Prepare a checked composition bound to ordinary published practice. First list exact "
        "candidates in this Run; bind each response/editor component to a returned candidate id. "
        "Use identical published options or Python starter code; never supply answers, tests, "
        "grades or execution permissions. The separate learner actions keep their original "
        "assessment/execution owners. The returned candidate still requires checked delivery.",
        PreparePracticeComposition,
        "enqueue",
        result=PreparedComposition,
    ),
    ToolDefinition(
        "list_learning_response_candidates",
        "List reviewed ordinary response practices for this exact node: multiple choice, "
        "prediction, reference-only short answer, ordering and line-location review. Public "
        "content only; private keys/findings remain hidden. Read next_before pages as needed. "
        "These source handles are NOT directly deliverable: bind them using "
        "prepare_learning_response_composition. No execution, Gate or semantic grading authority.",
        ArtifactPage,
        "read",
        result=ResponseCandidateList,
    ),
    ToolDefinition(
        "prepare_learning_response_composition",
        "Prepare a composition using original-owner response candidates actually listed in "
        "this Run. Match multiple ChoiceAnswer, TextAnswer, OrderingAnswer or LineRangeAnswer "
        "to its published format; freeze exact option/item ids and read-only review code. "
        "AnswerFeedback and ReviewFinding display only actual owner receipts, not model "
        "answers. Short responses are reference-only; line reasons are not automatically "
        "graded. Original single-choice/Python sources may also be composed if listed. "
        "Only this returned candidate.id is selectable for independent checked delivery.",
        PreparePracticeComposition,
        "enqueue",
        result=PreparedComposition,
    ),
    ToolDefinition(
        "prepare_learning_code_review_composition",
        "Prepare teaching review of the exact completed ordinary Python receipt in this "
        "attempt focus. Target a CodeBlock with an empty code state: the original Assessment "
        "fills the immutable submitted code. Include ReviewFinding for that target and quote "
        "each source_line exactly, without CR/LF. Findings are teaching comments, not grades, "
        "compiler output or evidence of execution. No caller attempt, score or tests accepted. "
        "Return the candidate.id for independent checked delivery. Keep explanation/reflection "
        "in the message; revisions and execution use the original practice workspace.",
        PrepareCodeReviewComposition,
        "enqueue",
        result=PreparedComposition,
    ),
    ToolDefinition(
        "prepare_learning_code_review_composition_v2",
        "Prepare a checked review of the exact public Python submission in this attempt "
        "focus, with an explicit learner reading-confirmation port. The original Assessment "
        "fills the immutable CodeBlock; ReviewFinding targets it and findings quote exact "
        "source lines. Review the full task and submitted code, preserving its original "
        "result. The learner may separately complete_review after reading; preparing or "
        "publishing never records that confirmation. Select the returned candidate.id for "
        "independent checked delivery. Revisions and execution stay in the original workspace.",
        PrepareCodeReviewComposition,
        "enqueue",
        result=PreparedComposition,
    ),
    ToolDefinition(
        "list_learning_program_candidates",
        "List published ordinary SQL/multifile practice for this exact node. Public task, "
        "fixed runtime/dialect, manifest and sample only; no hidden cases or answers. "
        "These handles are not directly deliverable. Bind an actually listed candidate using "
        "prepare_learning_program_composition; no execution or installation is authorized.",
        ArtifactPage,
        "read",
        result=ProgramCandidateList,
    ),
    ToolDefinition(
        "prepare_learning_program_composition",
        "Prepare a checked composition using actually listed ordinary SQL/project sources. "
        "Bind SQL to the exact starter query in a code editor/diff, projects to the complete "
        "unchanged public files in a files editor. Keep protected contents/flags, environment "
        "and task fixed. ResultFeedback/check_code target the same owner component. "
        "Other original owners may be mixed only with their separately frozen capabilities. "
        "Only explicit learner actions create Attempts through original Assessment/Runner; "
        "actual public sample output comes from owner receipts, never a model table. "
        "Select only the returned candidate.id for independent checked delivery.",
        PreparePracticeComposition,
        "enqueue",
        result=PreparedComposition,
    ),
    ToolDefinition(
        "prepare_learning_assisted_composition",
        "Prepare ordinary practice with an explicit learner-only direct-answer control. "
        "Use actually listed sources; every bound owner still needs its separately frozen "
        "practice/response/program capability. Keep original options, starter query/code and "
        "complete protected files unchanged. This tool never reads a reference, solves, runs "
        "or grades. Original Assessment records assistance and ItemBank records exposure only "
        "after the learner explicitly requests the published reference. No H1-H3 hints, exam "
        "sources or model-authored answers. Select its exact returned candidate for checked "
        "delivery as usual.",
        PreparePracticeComposition,
        "enqueue",
        result=PreparedComposition,
    ),
    ToolDefinition(
        "prepare_learning_hint_composition",
        "Prepare ordinary practice with three private, independently checked teaching hints. "
        "Use actually listed sources and each owner's separately frozen original capability. "
        "For each hinted component supply H1 concept, H2 strategy, H3 a concrete next step, "
        "in order and with distinct useful text. Ground them in the public task and supplied "
        "materials; do not split an explanation, disclose an option/result/full solution, "
        "invent tests, or include locked hints in visible text/code/state. Keep the original "
        "question/editor unchanged. The returned private hint_bindings are review input, NOT "
        "learner-visible delivery. Select only its exact candidate for independent review. "
        "Only later explicit sequential learner actions release a level and record assistance. "
        "Direct answers remain a separate capability/action; no auto-answer, run or grading.",
        PrepareHintComposition,
        "enqueue",
        result=PreparedHintComposition,
    ),
    ToolDefinition(
        "prepare_learning_demo_composition",
        "Prepare a checked composition with bounded learner-reported demonstration events. "
        "demo_components names AlgorithmPlayer, StepPlayer, SequenceDiagram or IsolatedPreview "
        "ports in this exact definition; the server derives their expected event. No callbacks, "
        "clocks, code execution, mastery or grading are authorized. A later explicit learner "
        "start freezes current allowed inputs and issues a generation/nonce; the learner "
        "separately reports the endpoint/current preview and confirms browsing completion. "
        "These are learner reports, not proof of visibility, comprehension or independent skill. "
        "Ordinary practice/hints may be mixed only with actually listed sources and separately "
        "frozen original capabilities. Select the returned exact handle for independent review.",
        PrepareDemoComposition,
        "enqueue",
        result=PreparedHintComposition,
        wire_arguments=PrepareDemoWire,
    ),
    ToolDefinition(
        "request_learning_practice_supply",
        "Request new ordinary practice for this exact confirmed node, using the original "
        "ItemBank supply task after this teaching turn yields. Use only supported choice, "
        "Python IO or response kind; response requires typed formats for both ordinary slots. "
        "Reuse command_key for the same intent. No question content, answer, grading, execution "
        "or publication is accepted. accepted is queued, NOT a usable candidate. Finish this "
        "turn and use task status later; never poll in a loop or request duplicate supplies.",
        RequestPracticeSupply,
        "enqueue",
        result=QueuedPracticeSupply,
    ),
    ToolDefinition(
        "get_learning_practice_supply",
        "Read original supply status in this exact node without advancing it or calling a "
        "model. A published pack is not a delivery: list its public candidates in this Run "
        "before preparing/selecting a composition. Waiting/UNKNOWN does not grant retries.",
        ReadPracticeSupply,
        "read",
        result=PracticeSupplyStatus,
    ),
    ToolDefinition(
        "get_execution_environments",
        "Read this learner's local engine, trusted recipes, current exact plan demands and "
        "usable environment releases. Copy an actually usable exact environment tuple when "
        "requesting program practice. A recipe or pending demand is not a ready environment.",
        GetExecutionEnvironments,
        "read",
        result=ExecutionEnvironmentSnapshot,
    ),
    ToolDefinition(
        "request_execution_environment",
        "Register the route's exact trusted local environment requirement for the learner's "
        "explicit decision. Never installs, allows, expands permission or changes global SDKs. "
        "Use the same command key for the same scope. Ask the learner to review the native "
        "environment decision; wait for an actually verified ready release before supplying "
        "program practice. A model request never authorizes installation.",
        RequestExecutionEnvironment,
        "enqueue",
        result=EnvironmentDemandToolReceipt,
    ),
    ToolDefinition(
        "request_learning_program_supply",
        "Request a real program pack for this exact confirmed node through the original "
        "author, public-only blind solve, isolated qualification, six reviews and publication. "
        "This is assessed practice, not a free-form Run button. Do not commission a scored "
        "pack for a local edit or a fixed example with no meaningful test variation. "
        "Copy the exact ready user-allowed program_environment from get_execution_environments. "
        "Use project_stdio for Python/JavaScript/TypeScript/Java/Go/C#, sql_query for the "
        "explicit SQL dialect, web_project for browser projects or http_project for "
        "task-local HTTP services and their declared writable database. No model-authored "
        "tests or answers "
        "are accepted here. Reuse the original key, finish this turn and wait for supply; "
        "qualification and ordinary practice do not complete a formal Gate.",
        RequestProgramSupply,
        "enqueue",
        result=QueuedPracticeSupply,
    ),
    ToolDefinition(
        "get_learning_program_supply",
        "Read the exact original program supply task without advancing it. When published, "
        "list actual program candidates in this Run before checked composition preparation. "
        "Waiting or UNKNOWN does not authorize a duplicate supply request.",
        ReadPracticeSupply,
        "read",
        result=ProgramSupplyStatus,
    ),
    ToolDefinition(
        NODE_WEB_TOOL,
        "Check a specific public version change, current documentation or requested attribution "
        "not established by this turn's readings. Call alone, once, only when needed. "
        "Do not search for a basic explanation or an original example. Use the returned sources.",
        PublicTeachingQuestion, "read",
    ),
)
REGISTRY = {tool.name: tool for tool in DEFINITIONS}
LEGACY_TOOLS = ("learning_get_context",)
COMPOSITION_TOOLS = ("get_learning_component_contracts", "prepare_learning_composition")
TEMPLATE_TOOLS = ("prepare_learning_template",)
PRACTICE_COMPOSITION_TOOLS = ("prepare_learning_practice_composition",)
RESPONSE_COMPOSITION_TOOLS = (
    "list_learning_response_candidates", "prepare_learning_response_composition",
)
CODE_REVIEW_COMPOSITION_TOOLS = ("prepare_learning_code_review_composition",)
CODE_REVIEW_COMPLETION_TOOLS = ("prepare_learning_code_review_composition_v2",)
PROGRAM_COMPOSITION_TOOLS = (
    "list_learning_program_candidates", "prepare_learning_program_composition",
    "get_execution_environments", "request_execution_environment",
    "request_learning_program_supply", "get_learning_program_supply",
)
ASSISTED_COMPOSITION_TOOLS = ("prepare_learning_assisted_composition",)
HINT_COMPOSITION_TOOLS = ("prepare_learning_hint_composition",)
DEMO_COMPOSITION_TOOLS = ("prepare_learning_demo_composition",)
PRACTICE_SUPPLY_TOOLS = ("request_learning_practice_supply", "get_learning_practice_supply")
TEACHING_TOOLS = tuple(
    name for name in REGISTRY
    if name not in (
        COMPOSITION_TOOLS + TEMPLATE_TOOLS + PRACTICE_COMPOSITION_TOOLS + RESPONSE_COMPOSITION_TOOLS
        + PRACTICE_SUPPLY_TOOLS + CODE_REVIEW_COMPOSITION_TOOLS + CODE_REVIEW_COMPLETION_TOOLS
        + PROGRAM_COMPOSITION_TOOLS
        + ASSISTED_COMPOSITION_TOOLS + HINT_COMPOSITION_TOOLS + DEMO_COMPOSITION_TOOLS
        + (NODE_WEB_TOOL,)
    )
)


def contracts(names):
    return {name: REGISTRY[name].version for name in names}


def allowed(frozen):
    return tuple(name for name, tool in REGISTRY.items() if frozen.get(name) == tool.version)
