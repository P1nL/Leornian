from leornian.modules.item_bank.python_contracts import PythonQuestion as PythonQuestion
from leornian.modules.item_bank.supply_contracts import ChoiceInput, ChoiceResult, PublicQuestion
from leornian.shared_kernel.contracts import Contract

__all__ = [
    "ChoiceInput",
    "ChoiceResult",
    "Exercise",
    "PublishedItem",
    "PublicQuestion",
    "PythonQuestion",
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
