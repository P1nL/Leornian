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
    model_base_url: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_BASE_URL", "").rstrip("/")
    )
    model_name: str = field(default_factory=lambda: os.environ.get("LEORNIAN_MODEL_NAME", ""))
    model_api_key: str = field(
        default_factory=lambda: os.environ.get("LEORNIAN_MODEL_API_KEY", ""), repr=False
    )
    model_timeout: float = 40.0
    run_lease_seconds: int = 120
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
