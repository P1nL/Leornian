from typing import Annotated, Literal

from pydantic import Field, model_validator

from leornian.modules.item_bank.supply_contracts import SLOTS, Slot
from leornian.modules.knowledge.contracts import SourceRef
from leornian.shared_kernel.contracts import Contract

InputInt = Annotated[int, Field(strict=True, ge=-1_000_000, le=1_000_000)]
OutputInt = Annotated[int, Field(strict=True, ge=-1_000_000_000_000, le=1_000_000_000_000)]


class PythonCase(Contract):
    input: list[InputInt] = Field(max_length=20)
    expected: OutputInt


class PythonQuestion(Contract):
    slot: Slot
    language: Literal["python_io"] = "python_io"
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=1800)
    starter_code: str = Field(min_length=1, max_length=2000)
    sample: PythonCase
    difficulty: int = Field(ge=1, le=5)
    source_refs: list[SourceRef] = Field(min_length=1, max_length=3)


class PythonItem(PythonQuestion):
    tests: list[PythonCase] = Field(min_length=3, max_length=3)
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def distinct_cases(self):
        if len({tuple(case.input) for case in self.tests}) != 3:
            raise ValueError("Three distinct inputs are required.")
        if self.sample not in self.tests:
            raise ValueError("The public sample must be among the validated cases.")
        return self

    def public(self):
        return PythonQuestion(**self.model_dump(exclude={"tests", "explanation"}))


class PythonPack(Contract):
    items: list[PythonItem] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def all_slots(self):
        if {item.slot for item in self.items} != set(SLOTS):
            raise ValueError("All five execution slots are required.")
        if len({"".join(item.prompt.split()).casefold() for item in self.items}) != 5:
            raise ValueError("Each task must have a different decision.")
        return self


class BlindProgram(Contract):
    slot: Slot
    code: str = Field(min_length=1, max_length=4000)


class BlindPrograms(Contract):
    programs: list[BlindProgram] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def all_slots(self):
        if {item.slot for item in self.programs} != set(SLOTS):
            raise ValueError("Independently solve every public task exactly once.")
        return self
