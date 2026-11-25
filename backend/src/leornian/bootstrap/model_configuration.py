from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


def configuration_scope(settings):
    if settings.model_configuration_mode not in {"user", "development"}:
        raise BusinessError("model_unavailable", "Unknown model configuration scope.")
    return "user" if settings.model_configuration_mode == "user" else "legacy_development"


def require_model_admission(settings):
    # BYOK requests persist and wait for configuration; no shared-key fallback.
    if configuration_scope(settings) == "legacy_development":
        ChatCompletionsGateway(settings).require_ready()


class ModelConfigurationWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def configuration(self, token):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return UserModels(connection, self.settings).configuration(actor)

    def tavily_configuration(self, token):
        from leornian.platform.material_search_configuration import MaterialSearchConfiguration

        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return MaterialSearchConfiguration(connection, self.settings).get(actor)

    def save_tavily(self, token, data):
        from leornian.platform.material_search_configuration import MaterialSearchConfiguration

        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return MaterialSearchConfiguration(connection, self.settings).save(actor, data)

    def create_connection(self, token, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).create_connection(actor, key, data)

    def apply_preset(self, token, key, preset_id, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).apply_preset(actor, key, preset_id, data)

    def use_connection(self, token, key, connection_id, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).use_connection(
                actor, key, connection_id, data
            )

    def create_custom_provider(self, token, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).create_custom_provider(actor, key, data)

    def patch_connection(self, token, connection_id, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).patch_connection(
                actor, connection_id, data
            )

    def delete_connection(self, token, connection_id, revision):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).delete_connection(
                actor, connection_id, revision
            )

    def save_profile(self, token, key, data, profile_id=None, *, assign_roles=True):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).save_profile(
                actor, key, data, profile_id, assign_roles=assign_roles
            )

    def assign_role(self, token, role, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return UserModels(connection, self.settings).assign_role(actor, role, data)

    def availability(self, token):
        from leornian.agent_runtime.contracts import ModelAvailability

        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            if configuration_scope(self.settings) == "legacy_development":
                return ChatCompletionsGateway(self.settings).availability()
            store = UserModels(connection, self.settings)
            try:
                store.binding(actor, "tutor.v1")
                store.binding(actor, "delivery_review.v1")
                ready = store.vault.available()
            except BusinessError:
                ready = False
            return ModelAvailability(ready=ready, reason="ready" if ready else "not_configured")
