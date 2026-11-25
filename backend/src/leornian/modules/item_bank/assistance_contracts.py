"""Published references released only by an explicit ordinary-practice action."""

from typing import Annotated, Literal

from pydantic import Field

from leornian.modules.item_bank.program_contracts import ProgramAnswer
from leornian.modules.item_bank.response_contracts import ReferenceFinding, ResponseValue
from leornian.modules.item_bank.supply_contracts import OptionKey
from leornian.shared_kernel.contracts import Contract


class ChoiceDirectAnswer(Contract):
    type: Literal["choice"] = "choice"
    correct_key: OptionKey
    explanation: str = Field(min_length=1, max_length=2000)


class PythonDirectAnswer(Contract):
    type: Literal["python"] = "python"
    code: str = Field(min_length=1, max_length=12000)
    explanation: str = Field(min_length=1, max_length=2000)


class ResponseDirectAnswer(Contract):
    type: Literal["response"] = "response"
    response: ResponseValue
    explanation: str = Field(min_length=1, max_length=2000)
    findings: list[ReferenceFinding] = Field(default_factory=list, max_length=40)


class ProgramDirectAnswer(Contract):
    type: Literal["program"] = "program"
    answer: ProgramAnswer
    explanation: str = Field(min_length=1, max_length=2000)


DirectAnswerContent = Annotated[
    ChoiceDirectAnswer | PythonDirectAnswer | ResponseDirectAnswer | ProgramDirectAnswer,
    Field(discriminator="type"),
]
