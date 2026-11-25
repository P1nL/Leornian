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
    "invalid_item_output",
    "invalid_gate_output",
    "assessment_not_independent",
    "invalid_transfer_output",
    "no_transfer_candidate",
    "supply_cancelled",
    "material_storage_unavailable",
    "material_original_missing",
    "material_content_mismatch",
    "material_file_limit",
    "material_text_limit",
    "material_block_limit",
    "material_page_limit",
    "material_pdf_limit",
    "material_format_mismatch",
    "material_encoding_required",
    "material_encrypted",
    "material_pdf_invalid",
    "material_parser_timeout",
    "material_parser_limit",
    "material_parser_unavailable",
    "source_encoding_unsupported",
    "source_encoding_invalid",
    "source_redirect_limit",
    "source_response_invalid",
    "source_http_unavailable",
    "source_read_unknown",
    "source_network_unavailable",
    "invalid_material_goal_output",
    "material_pending",
]


class BusinessError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
