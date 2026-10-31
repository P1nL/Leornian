from leornian.shared_kernel.contracts import Contract


class Exercise(Contract):
    version: str
    title: str
    prompt: str
    starter_code: str
    provenance: str


class PublishedItem(Contract):
    exercise: Exercise
    execution_inputs: list[list[int]]
