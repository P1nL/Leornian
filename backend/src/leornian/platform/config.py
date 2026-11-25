import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        repr=False,
        default_factory=lambda: os.environ.get(
            "LEORNIAN_DATABASE_URL",
            "postgresql://leornian@127.0.0.1:5448/leornian",
        ),
    )
    broker_url: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_BROKER_URL", "redis://127.0.0.1:6388/0")
    )
    redispatch_seconds: int = field(
        default_factory=lambda: int(os.environ.get("LEORNIAN_REDISPATCH_SECONDS", "15"))
    )
    model_enabled: bool = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_ENABLED", "false").lower() == "true"
    )
    model_configuration_mode: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_CONFIGURATION_MODE", "user")
    )
    credential_master_file: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_CREDENTIAL_MASTER_FILE", ""),
        repr=False,
    )
    model_network_guard: bool = False
    model_local_endpoint: bool = False
    model_profile_timeout: int | None = None
    material_check_days: int = field(
        default_factory=lambda: int(os.environ.get("LEORNIAN_MATERIAL_CHECK_DAYS", "30"))
    )
    material_review_days: int = field(
        default_factory=lambda: int(os.environ.get("LEORNIAN_MATERIAL_REVIEW_DAYS", "180"))
    )
    material_completion_grace_days: int = field(
        default_factory=lambda: int(os.environ.get("LEORNIAN_MATERIAL_COMPLETION_GRACE_DAYS", "30"))
    )
    material_source_timeout_seconds: int = field(
        default_factory=lambda: int(
            os.environ.get("LEORNIAN_MATERIAL_SOURCE_TIMEOUT_SECONDS", "30")
        )
    )
    material_source_max_redirects: int = field(
        default_factory=lambda: int(os.environ.get("LEORNIAN_MATERIAL_SOURCE_MAX_REDIRECTS", "4"))
    )
    material_source_check_seconds: int = field(
        default_factory=lambda: int(
            os.environ.get("LEORNIAN_MATERIAL_SOURCE_CHECK_SECONDS", "86400")
        )
    )
    material_storage_dir: str = field(
        default_factory=lambda: os.environ.get(
            "LEORNIAN_MATERIAL_STORAGE_DIR",
            os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~/.local/share")),
                "Leornian",
                "materials",
            ),
        ),
        repr=False,
    )
    model_base_url: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_BASE_URL", "").rstrip("/")
    )
    model_name: str = field(default_factory=lambda: os.environ.get("LEORNIAN_MODEL_NAME", ""))
    model_api_key: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_API_KEY", ""), repr=False
    )
    model_thinking: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_THINKING", "")
    )
    model_stage_thinking: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_STAGE_THINKING", "{}")
    )
    model_timeout: float = 40.0
    run_lease_seconds: int = 120
    heartbeat_seconds: float = 20.0
    delivery_enabled: bool = True
    model_context_tokens: int = field(
        default_factory=lambda: int(os.environ.get("LEORNIAN_MODEL_CONTEXT_TOKENS", "0"))
    )
    model_max_output_tokens: int = field(
        default_factory=lambda: int(os.environ.get("LEORNIAN_MODEL_MAX_OUTPUT_TOKENS", "0"))
    )
    model_output_budget_multiplier: int = 1
    runner_token: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_RUNNER_TOKEN", ""),
        repr=False,
    )
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5178",
        "http://localhost:5178",
        "http://tauri.localhost",
        "tauri://localhost",
    )
