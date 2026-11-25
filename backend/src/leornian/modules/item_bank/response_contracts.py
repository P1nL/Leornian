"""Published response formats and private keys; no model-selected grading code."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from leornian.modules.item_bank.generation_contracts import SupplyStageOutput
from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.learning.contracts import MaterialCitation
from leornian.shared_kernel.contracts import Contract

ResponseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")]
ResponseText = Annotated[str, StringConstraints(min_length=1, max_length=4000, pattern=r"\S")]
ResponseSlot = Literal[
    "practice_1", "practice_2", "assessment_1", "assessment_2", "remediation_1"
]
ResponseFormat = Literal["multiple", "prediction", "short", "ordering", "line_review"]


class ResponsePracticeFormats(Contract):
    practice_1: ResponseFormat
    practice_2: ResponseFormat


class ResponseOption(Contract):
    id: ResponseId
    text: str = Field(min_length=1, max_length=500)


class ResponseQuestionBase(Contract):
    slot: ResponseSlot
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=1800)
    difficulty: int = Field(ge=1, le=5)
    source_refs: list[SourceRef] = Field(max_length=3)
    material_citations: list[MaterialCitation] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def cited(self):
        if not self.source_refs and not self.material_citations:
            raise ValueError("A response question needs an exact supplied citation.")
        return self


class MultipleQuestion(ResponseQuestionBase):
    response_type: Literal["multiple"]
    options: list[ResponseOption] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def distinct_options(self):
        if len({o.id for o in self.options}) != len(self.options) or len({
            o.text.strip().casefold() for o in self.options
        }) != len(self.options):
            raise ValueError("Multiple-choice options must be distinct.")
        return self


class PredictionQuestion(ResponseQuestionBase):
    response_type: Literal["prediction"]
    code: str = Field(min_length=1, max_length=12000)
    comparison: Literal["lines-rstrip.v1"] = "lines-rstrip.v1"


class ShortQuestion(ResponseQuestionBase):
    response_type: Literal["short"]
    assessment_mode: Literal["reference_only"] = "reference_only"


class OrderingQuestion(ResponseQuestionBase):
    response_type: Literal["ordering"]
    items: list[ResponseOption] = Field(min_length=2, max_length=30)

    @model_validator(mode="after")
    def distinct_items(self):
        if len({o.id for o in self.items}) != len(self.items) or len({
            o.text.strip().casefold() for o in self.items
        }) != len(self.items):
            raise ValueError("Ordering items must be distinct.")
        return self


class LineQuestion(ResponseQuestionBase):
    response_type: Literal["line_review"]
    code: str = Field(min_length=1, max_length=12000)
    assessment_mode: Literal["location_only"] = "location_only"

    @model_validator(mode="after")
    def bounded_lines(self):
        if len(self.code.split("\n")) > 240:
            raise ValueError("A review snapshot supports at most 240 lines.")
        return self


ResponseQuestion = Annotated[
    MultipleQuestion | PredictionQuestion | ShortQuestion | OrderingQuestion | LineQuestion,
    Field(discriminator="response_type"),
]


class MultipleResponse(Contract):
    type: Literal["multiple"]
    selected_ids: list[ResponseId] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_selection(self):
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise ValueError("Selected option ids must be distinct.")
        return self


class PredictionResponse(Contract):
    type: Literal["prediction"]
    text: str = Field(max_length=4000)


class ShortResponse(Contract):
    type: Literal["short"]
    text: ResponseText


class OrderingResponse(Contract):
    type: Literal["ordering"]
    ordered_ids: list[ResponseId] = Field(min_length=2, max_length=30)

    @model_validator(mode="after")
    def unique_items(self):
        if len(set(self.ordered_ids)) != len(self.ordered_ids):
            raise ValueError("Ordered item ids must be distinct.")
        return self


class LineAnnotation(Contract):
    line: int = Field(ge=1, le=240)
    reason: Annotated[str, StringConstraints(min_length=1, max_length=1000, pattern=r"\S")]


class LineResponse(Contract):
    type: Literal["line_review"]
    annotations: list[LineAnnotation] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({a.line for a in self.annotations}) != len(self.annotations):
            raise ValueError("Each line has one saved annotation.")
        return self


ResponseValue = Annotated[
    MultipleResponse | PredictionResponse | ShortResponse | OrderingResponse | LineResponse,
    Field(discriminator="type"),
]


class ResponseSubmission(Contract):
    slot: Literal["practice_1", "practice_2"]
    response: ResponseValue


class ReferenceFinding(Contract):
    line: int = Field(ge=1, le=240)
    content: str = Field(min_length=1, max_length=1200)


class ResponseAnswerKey(Contract):
    """Private, reviewed data. Its shape cannot introduce a scorer or expression."""

    response: ResponseValue
    explanation: str = Field(min_length=1, max_length=2000)
    findings: list[ReferenceFinding] = Field(default_factory=list, max_length=40)


def validate_response(question, response):
    if response.type != question.response_type:
        raise ValueError("The answer format must match the published question.")
    if response.type == "multiple" and not set(response.selected_ids) <= {
        o.id for o in question.options
    }:
        raise ValueError("The response names an unpublished option.")
    if response.type == "ordering" and set(response.ordered_ids) != {
        o.id for o in question.items
    }:
        raise ValueError("An ordering response must be the complete published permutation.")
    if response.type == "line_review" and any(
        a.line > len(question.code.split("\n")) for a in response.annotations
    ):
        raise ValueError("An annotation is outside the immutable code snapshot.")


def compare_response(question, response, key):
    """V1 data comparison, reused for blind consistency and owner assessment."""
    validate_response(question, response)
    reference = key.response
    if response.type == "multiple":
        return set(response.selected_ids) == set(reference.selected_ids)
    if response.type == "prediction":
        def lines(text):
            return "\n".join(
                line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
            ).rstrip("\n")
        return lines(response.text) == lines(reference.text)
    if response.type == "ordering":
        return response.ordered_ids == reference.ordered_ids
    if response.type == "line_review":
        return {a.line for a in response.annotations} == {a.line for a in reference.annotations}
    return None


class AuthoredResponseQuestion(Contract):
    question: ResponseQuestion
    answer: ResponseAnswerKey

    @model_validator(mode="after")
    def compatible_key(self):
        validate_response(self.question, self.answer.response)
        if self.question.response_type == "line_review":
            lines = {a.line for a in self.answer.response.annotations}
            if {f.line for f in self.answer.findings} != lines or len(
                self.answer.findings
            ) != len(lines):
                raise ValueError("Each reference line needs exactly one finding.")
        elif self.answer.findings:
            raise ValueError("Only a line review carries line findings.")
        return self

    @property
    def slot(self):
        return self.question.slot

    @property
    def prompt(self):
        return self.question.prompt

    @property
    def difficulty(self):
        return self.question.difficulty

    @property
    def source_refs(self):
        return self.question.source_refs

    @property
    def material_citations(self):
        return self.question.material_citations

    def public(self):
        return self.question


class ResponsePack(SupplyStageOutput):
    items: list[AuthoredResponseQuestion] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete_slots(self):
        if {item.slot for item in self.items} != {
            "practice_1", "practice_2", "assessment_1", "assessment_2", "remediation_1"
        } or len({"".join(i.prompt.split()).casefold() for i in self.items}) != 5:
            raise ValueError("Use each distinct slot and contextual prompt exactly once.")
        return self


class BlindResponse(Contract):
    slot: ResponseSlot
    response: ResponseValue


class BlindResponses(SupplyStageOutput):
    answers: list[BlindResponse] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete_slots(self):
        if {a.slot for a in self.answers} != {
            "practice_1", "practice_2", "assessment_1", "assessment_2", "remediation_1"
        }:
            raise ValueError("Blind responses must cover each slot exactly once.")
        return self


class ResponsePracticeSet(Contract):
    pack_id: UUID
    questions: list[ResponseQuestion]
