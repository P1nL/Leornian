from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from leornian.modules.execution.contracts import CaseOutput, ProjectLanguage
from leornian.shared_kernel.contracts import Contract


class ExampleRunSurface(Contract):
    run_label: str
    stdin_label: str
    stdin_hint: str
    input_mode: Literal["multiline_before_run", "line_during_run"]
    output_mode: Literal["replace_on_next_run", "live_terminal"]
    share_code_label: str | None = Field(default=None, exclude_if=lambda value: value is None)


EXAMPLE_RUN_SURFACE = ExampleRunSurface(
    run_label="运行", stdin_label="标准输入", stdin_hint="运行前填写，多次输入请分行。",
    input_mode="multiline_before_run", output_mode="replace_on_next_run",
    share_code_label="本次运行成功后，将代码分享给 Tutor，在本路线接着使用",
)

EXAMPLE_TERMINAL_SURFACE = ExampleRunSurface(
    run_label="运行", stdin_label="终端",
    stdin_hint="点击「运行」，看到程序提示后输入，按回车发送。",
    input_mode="line_during_run", output_mode="live_terminal",
)


def example_capability(actions):
    return next((version for version in ("learning_example_runs.v2", "learning_example_runs.v1")
                 if version in actions), None)


def example_surface(capability):
    if capability == "learning_example_runs.v2":
        return EXAMPLE_TERMINAL_SURFACE
    return EXAMPLE_RUN_SURFACE


class ExampleRunInput(Contract):
    command_id: UUID
    expected_artifact_revision: int = Field(ge=1)
    component_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    language: ProjectLanguage
    code: str = Field(min_length=1, max_length=20000)
    stdin: str = Field(default="", max_length=8192)
    interactive: bool = Field(default=False, strict=True, exclude_if=lambda value: not value)
    share_code_for_teaching: bool = Field(default=False, strict=True,
                                          exclude_if=lambda shared: not shared)

    @model_validator(mode="after")
    def terminal_starts_empty(self):
        if self.interactive and self.stdin:
            raise ValueError("交互程序启动后再输入。")
        return self


class ExampleTerminalLine(Contract):
    input_id: UUID
    text: str = Field(max_length=2048, pattern=r"^[^\r\n\x00]*$")


class ExampleTerminalExchange(Contract):
    claim_token: UUID
    frame: int = Field(ge=0)
    text: str = Field(default="", max_length=8192, pattern=r"^[^\x00]*$")
    after_input: int = Field(ge=0, le=128)
    closed: bool = False


class ExampleTerminalView(Contract):
    transcript: str
    accepting_input: bool
    stopping: bool


class ExampleRunResult(Contract):
    command_id: UUID
    status: Literal["queued", "running", "reported", "expired"]
    compilation: CaseOutput | None = None
    output: CaseOutput | None = None
    error_code: str | None = None
    terminal: ExampleTerminalView | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
