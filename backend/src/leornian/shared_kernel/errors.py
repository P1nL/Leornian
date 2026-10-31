from typing import Literal

ErrorCode = Literal[
    "unauthorized",
    "not_found",
    "idempotency_conflict",
    "cursor_invalid",
    "run_active",
    "model_unavailable",
    "unknown_unresolved",
    "resume_not_allowed",
    "stale_version",
    "precondition_failed",
    "source_not_current",
    "invalid_plan_output",
    "invalid_lesson_output",
]


class BusinessError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
