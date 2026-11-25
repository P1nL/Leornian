from uuid import UUID

from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.materials import Materials
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.material_contracts import BoundMaterialPage
from leornian.modules.learning.materials import MaterialBindings
from leornian.platform.config import Settings
from leornian.platform.database import Database
from leornian.shared_kernel.errors import BusinessError


class MaterialWorkflow:
    def __init__(self, database: Database, settings: Settings | None = None):
        self.database = database
        self.settings = settings or Settings()
        if (
            min(
                self.settings.material_check_days,
                self.settings.material_review_days,
                self.settings.material_completion_grace_days,
            )
            < 1
        ):
            raise ValueError("Material scheduling intervals must be positive")

    def import_text(self, token, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, data.goal_id)
            return Materials(connection, check_days=self.settings.material_check_days).import_text(
                actor, key, data
            )

    def import_legacy(self, token, source_id, revision):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return Materials(
                connection, check_days=self.settings.material_check_days
            ).import_legacy(actor, source_id, revision)

    def version(self, token, document_id, revision):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Materials(connection).version(actor, document_id, revision)

    def blocks(self, token, document_id, revision, purpose, after=-1, limit=20):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            return Materials(connection).blocks(
                actor, document_id, revision, purpose, after=after, limit=limit
            )

    def revoke(self, token, document_id, revision, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            version = Materials(connection).revoke(
                actor, document_id, revision, data.expected_revision
            )
            if version.permission.revision != data.expected_revision:
                Events(connection).append(
                    actor.id, "knowledge.material_permission_changed", document_id,
                    EventPayload(
                        document_id=document_id, document_revision=revision,
                        goal_id=version.goal_id,
                    ),
                )
            return version

    def revoke_receipt(self, token, document_id, revision):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            version = Materials(connection).version(actor, document_id, revision)
            if version.permission.status != "revoked":
                raise BusinessError("not_found", "Material revocation has not occurred.")
            return version

    def bind(self, token, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, data.goal_id)
            bindings = MaterialBindings(
                connection,
                review_days=self.settings.material_review_days,
                grace_days=self.settings.material_completion_grace_days,
            )
            previous = bindings.replay(actor, key, data)
            if previous:
                return previous
            Materials(connection).read_refs(actor, data.goal_id, data.purpose, data.refs)
            return bindings.bind(actor, key, data)

    def binding(self, token, binding_id: UUID, revision=None):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return MaterialBindings(connection).get(actor, binding_id, revision)

    def bound_blocks(self, token, binding_id, expected_revision, offset=0, limit=20):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            bindings = MaterialBindings(connection)
            binding = bindings.get(actor, binding_id)
            if binding.revision != expected_revision:
                raise BusinessError("stale_version", "Material binding changed.")
            bindings.require_scope(actor, binding)
            refs = binding.refs[offset : offset + limit]
            blocks = Materials(connection).read_refs(actor, binding.goal_id, binding.purpose, refs)
            return BoundMaterialPage(
                binding=binding,
                blocks=blocks,
                next_offset=offset + limit if offset + limit < len(binding.refs) else None,
            )
