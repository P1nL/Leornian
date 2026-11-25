from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from leornian.shared_kernel.contracts import Contract

ModelOperation = Literal["chat", "ocr", "embedding", "rerank"]
ModelRole = Literal[
    "tutor.v1",
    "planner.v1",
    "lesson.v1",
    "delivery_review.v1",
    "material_check.v1",
    "material_review.v1",
    "evaluation.v1",
    "artifact.v1",
    "item_author.v1",
    "item_blind.v1",
    "item_review.v1",
    "gate_relation.v1",
    "transfer_relation.v1",
    "ocr",
    "embedding",
    "rerank",
]
CHAT_ROLES = (
    "tutor.v1",
    "planner.v1",
    "lesson.v1",
    "delivery_review.v1",
    "material_check.v1",
    "material_review.v1",
    "evaluation.v1",
    "artifact.v1",
    "item_author.v1",
    "item_blind.v1",
    "item_review.v1",
    "gate_relation.v1",
    "transfer_relation.v1",
)


class ModelConnectionInput(Contract):
    label: str = Field(min_length=1, max_length=100)
    protocol: Literal["chat_completions", "dashscope"]
    base_url: str = Field(min_length=1, max_length=2048)
    region: str = Field(min_length=1, max_length=80)
    local_endpoint: bool = False
    enabled: bool = False
    api_key: SecretStr = Field(repr=False, exclude=True, min_length=1, max_length=16384)

    @field_validator("base_url")
    @classmethod
    def clean_base(cls, value: str) -> str:
        url = urlsplit(value)
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("A model endpoint cannot contain credentials, queries or fragments")
        if url.scheme not in {"http", "https"}:
            raise ValueError("Model endpoints use HTTP(S)")
        return value.rstrip("/")

    @field_validator("label", "region")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()

    @field_validator("api_key")
    @classmethod
    def clean_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw.strip() or any(ch.isspace() for ch in raw):
            raise ValueError("API key cannot be blank or contain whitespace")
        return value


class ModelConnectionPatch(Contract):
    expected_revision: int = Field(ge=1)
    label: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    api_key: SecretStr | None = Field(
        default=None, repr=False, exclude=True, min_length=1, max_length=16384
    )

    @field_validator("api_key")
    @classmethod
    def clean_secret(cls, value):
        return ModelConnectionInput.clean_secret(value) if value is not None else None


class ModelConnectionDelete(Contract):
    expected_revision: int = Field(ge=1)


class ModelConnection(Contract):
    id: UUID
    revision: int
    label: str
    protocol: Literal["chat_completions", "dashscope"]
    base_url: str
    region: str
    local_endpoint: bool
    enabled: bool
    deleted: bool
    credential_version: int
    credential_present: bool
    created_at: datetime


class ModelProfileParameters(Contract):
    label: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_./:-]+$")
    operation: ModelOperation
    context_tokens: int = Field(default=0, ge=0, le=10_000_000)
    max_output_tokens: int = Field(default=0, ge=0, le=2_000_000)
    embedding_dimensions: int = Field(default=1024, ge=1, le=16384)
    thinking: Literal["", "enabled", "disabled"] = ""
    timeout_seconds: int = Field(default=300, ge=10, le=1800)

    @model_validator(mode="after")
    def model_capacity(self) -> Self:
        if self.operation == "chat":
            if not self.thinking:
                object.__setattr__(self, "thinking", "enabled")
            if not self.context_tokens or not self.max_output_tokens:
                raise ValueError("Declare the channel's real context and output capacities")
            if self.max_output_tokens > self.context_tokens:
                raise ValueError("Output capacity cannot exceed the context window")
        elif self.thinking:
            raise ValueError("Dedicated operations do not use chat thinking parameters")
        return self


class ModelProfileInput(ModelProfileParameters):
    connection_id: UUID
    enabled: bool = False
    allow_private_material: bool = False
    roles: list[ModelRole] = Field(min_length=1)

    @model_validator(mode="after")
    def role_protocol(self) -> Self:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("Duplicate roles")
        allowed = set(CHAT_ROLES) if self.operation == "chat" else {self.operation}
        if not set(self.roles) <= allowed:
            raise ValueError("Role and model operation do not match")
        return self


class ModelProfilePatch(ModelProfileInput):
    expected_revision: int = Field(ge=1)


class ModelProfile(ModelProfileInput):
    id: UUID
    revision: int
    created_at: datetime


class ModelRoleMapping(Contract):
    role: ModelRole
    profile_id: UUID
    revision: int


class ModelRoleAssignmentInput(Contract):
    profile_id: UUID
    expected_profile_revision: int = Field(ge=1)
    expected_mapping_revision: int = Field(ge=0)


ModelPresetId = Literal["deepseek", "qwen"]
ModelProviderGroup = Literal["teaching", "material"]


class ModelPresetModel(Contract):
    model: str
    label: str
    operation: ModelOperation
    context_tokens: int = 0
    max_output_tokens: int = 0


class ModelProviderPreset(Contract):
    id: ModelPresetId
    label: str
    base_url: str
    region: str
    models: list[str]
    api_key_url: str = ""
    model_details: list[ModelPresetModel] = Field(default_factory=list)


class ModelPresetInput(Contract):
    api_key: SecretStr = Field(repr=False, exclude=True, min_length=1, max_length=16384)
    allow_private_material: Literal[True]
    connection_id: UUID | None = None
    expected_connection_revision: int | None = Field(default=None, ge=1)
    expected_mapping_revisions: dict[ModelRole, int] = Field(default_factory=dict)
    models: list[str] | None = Field(default=None, min_length=1, max_length=16)
    group: ModelProviderGroup | None = None

    @field_validator("api_key")
    @classmethod
    def clean_secret(cls, value):
        return ModelConnectionInput.clean_secret(value)

    @field_validator("expected_mapping_revisions")
    @classmethod
    def nonnegative_revisions(cls, value):
        if any(revision < 0 for revision in value.values()):
            raise ValueError("Mapping revisions cannot be negative")
        return value

    @model_validator(mode="after")
    def connection_revision(self) -> Self:
        if (self.connection_id is None) != (self.expected_connection_revision is None):
            raise ValueError("An existing connection requires its exact revision")
        return self


class ModelProfileRevision(Contract):
    profile_id: UUID
    expected_revision: int = Field(ge=1)


class ModelConnectionUseInput(Contract):
    expected_connection_revision: int = Field(ge=1)
    group: ModelProviderGroup
    profiles: list[ModelProfileRevision] = Field(min_length=1, max_length=4)
    expected_mapping_revisions: dict[ModelRole, int] = Field(default_factory=dict)

    @field_validator("expected_mapping_revisions")
    @classmethod
    def nonnegative_revisions(cls, value):
        return ModelPresetInput.nonnegative_revisions(value)


class ModelCustomProviderInput(Contract):
    group: ModelProviderGroup
    connection: ModelConnectionInput
    profile: ModelProfileParameters
    allow_private_material: Literal[True]
    expected_mapping_revisions: dict[ModelRole, int] = Field(default_factory=dict)

    @field_validator("expected_mapping_revisions")
    @classmethod
    def nonnegative_revisions(cls, value):
        return ModelPresetInput.nonnegative_revisions(value)

    @model_validator(mode="after")
    def group_operation(self) -> Self:
        if not self.connection.enabled:
            raise ValueError("Enable the provider connection")
        if (self.profile.operation == "chat") != (self.group == "teaching"):
            raise ValueError("Choose a model for this provider group")
        return self


class ModelConfiguration(Contract):
    connections: list[ModelConnection]
    profiles: list[ModelProfile]
    mappings: list[ModelRoleMapping]
    credential_storage: Literal["available", "waiting_config"]
    configuration_scope: Literal["user", "development"]
    capabilities: list[
        Literal[
            "explicit-role-assignment.v1", "provider-presets.v1",
            "provider-presets.v2", "provider-presets.v3",
            "material-web-search.v1",
        ]
    ] = Field(default_factory=list)
    presets: list[ModelProviderPreset] = Field(default_factory=list)


class ModelConnectionTestInput(Contract):
    expected_connection_revision: int = Field(ge=1)
    profile_id: UUID
    allow_billable: Literal[True]


class ModelConnectionTest(Contract):
    id: UUID
    connection_id: UUID
    profile_id: UUID
    status: Literal["queued", "dispatching", "succeeded", "failed", "unknown", "cancelled"]
    result: dict | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
