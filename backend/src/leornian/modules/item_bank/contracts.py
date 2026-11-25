from leornian.modules.item_bank.assistance_contracts import (
    DirectAnswerContent as DirectAnswerContent,
)
from leornian.modules.item_bank.program_contracts import HttpAnswer as HttpAnswer
from leornian.modules.item_bank.program_contracts import ProgramAnswer as ProgramAnswer
from leornian.modules.item_bank.program_contracts import ProjectAnswer as ProjectAnswer
from leornian.modules.item_bank.program_contracts import (
    PublicProgramQuestion as PublicProgramQuestion,
)
from leornian.modules.item_bank.program_contracts import SqlAnswer as SqlAnswer
from leornian.modules.item_bank.program_contracts import StdioAnswer as StdioAnswer
from leornian.modules.item_bank.program_contracts import WebAnswer as WebAnswer
from leornian.modules.item_bank.python_contracts import PythonQuestion as PythonQuestion
from leornian.modules.item_bank.response_contracts import (
    ReferenceFinding as ReferenceFinding,
)
from leornian.modules.item_bank.response_contracts import (
    ResponsePracticeFormats as ResponsePracticeFormats,
)
from leornian.modules.item_bank.response_contracts import (
    ResponseQuestion as ResponseQuestion,
)
from leornian.modules.item_bank.response_contracts import (
    ResponseSubmission as ResponseSubmission,
)
from leornian.modules.item_bank.response_contracts import (
    ResponseValue as ResponseValue,
)
from leornian.modules.item_bank.response_contracts import (
    compare_response as compare_response,
)
from leornian.modules.item_bank.supply_contracts import ChoiceInput, ChoiceResult, PublicQuestion
from leornian.shared_kernel.contracts import Contract

__all__ = [
    "ChoiceInput",
    "ChoiceResult",
    "Exercise",
    "PublishedItem",
    "PublicQuestion",
    "PythonQuestion",
    "ResponseQuestion", "ResponseSubmission", "ResponseValue", "ResponsePracticeFormats",
    "ReferenceFinding", "compare_response",
    "ProgramAnswer", "ProjectAnswer", "PublicProgramQuestion", "SqlAnswer", "DirectAnswerContent",
    "StdioAnswer", "WebAnswer", "HttpAnswer",
]


class Exercise(Contract):
    version: str
    title: str
    prompt: str
    starter_code: str
    provenance: str


class PublishedItem(Contract):
    exercise: Exercise
    execution_inputs: list[list[int]]
