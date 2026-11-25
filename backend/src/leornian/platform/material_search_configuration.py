from uuid import uuid4

from pydantic import Field, SecretStr, field_validator

from leornian.platform.credentials import CredentialVault
from leornian.shared_kernel.contracts import Contract
from leornian.shared_kernel.errors import BusinessError


class TavilyConfiguration(Contract):
    revision: int = 0
    enabled: bool = False
    credential_present: bool = False


class TavilyConfigurationInput(Contract):
    expected_revision: int = Field(ge=0)
    enabled: bool
    api_key: SecretStr | None = Field(
        default=None, repr=False, exclude=True, min_length=1, max_length=16384,
    )

    @field_validator("api_key")
    @classmethod
    def valid_secret(cls, value):
        if value is not None and (
            not value.get_secret_value().strip()
            or any(character.isspace() for character in value.get_secret_value())
        ):
            raise ValueError("Tavily key cannot be blank or contain whitespace")
        return value


class MaterialSearchConfiguration:
    def __init__(self, connection, settings):
        self.connection = connection
        self.vault = CredentialVault(settings.credential_master_file)

    def row(self, actor):
        return self.connection.execute(
            "SELECT * FROM platform.material_search_configuration WHERE actor_id=%s",
            (actor.id,),
        ).fetchone()

    def get(self, actor):
        row = self.row(actor)
        return TavilyConfiguration(
            revision=row["revision"] if row else 0,
            enabled=bool(row and row["enabled"]),
            credential_present=bool(row and row["ciphertext"]),
        )

    def save(self, actor, data):
        previous = self.row(actor)
        revision = previous["revision"] if previous else 0
        if revision != data.expected_revision:
            raise BusinessError("stale_version", "Tavily 配置已改变，请重新打开后保存。")
        if not previous and data.api_key is None:
            raise BusinessError("precondition_failed", "请填写 Tavily API Key。")
        connection_id = previous["id"] if previous else uuid4()
        version = previous["credential_version"] if previous else 0
        if data.api_key is not None:
            version += 1
            scheme, ciphertext = self.vault.seal(
                actor.id, connection_id, version, data.api_key.get_secret_value(),
            )
        else:
            scheme, ciphertext = previous["scheme"], previous["ciphertext"]
        self.connection.execute(
            "INSERT INTO platform.material_search_configuration"
            "(actor_id,id,revision,credential_version,enabled,scheme,ciphertext) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(actor_id) DO UPDATE SET "
            "revision=EXCLUDED.revision,credential_version=EXCLUDED.credential_version,"
            "enabled=EXCLUDED.enabled,scheme=EXCLUDED.scheme,ciphertext=EXCLUDED.ciphertext,"
            "updated_at=now()",
            (actor.id, connection_id, revision + 1, version, data.enabled, scheme, ciphertext),
        )
        return self.get(actor)

    def binding(self, actor):
        row = self.row(actor)
        if not row or not row["enabled"] or not row["ciphertext"]:
            raise BusinessError("tavily_not_configured", "请在材料处理设置中配置并启用 Tavily。")
        return {key: str(row[key]) if key == "id" else row[key] for key in (
            "id", "revision", "credential_version",
        )}

    def secret(self, actor, binding):
        row = self.row(actor)
        if self.binding(actor) != binding:
            raise BusinessError("tavily_configuration_changed", "Tavily 配置已改变。")
        return self.vault.open(
            actor.id, row["id"], row["credential_version"], row["scheme"], row["ciphertext"],
        )
