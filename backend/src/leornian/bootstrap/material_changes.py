from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.change_reviews import MaterialChangeReviews
from leornian.modules.knowledge.changes import MaterialChanges
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.updates import MaterialUpdates
from leornian.modules.learning.materials import MaterialBindings
from leornian.shared_kernel.errors import BusinessError


class MaterialChangeWorkflow:
    def __init__(self, database):
        self.database = database

    def compare(self, token, key, data):
        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate(token)
            return self.compare_in(connection, actor, identity.digest(token), key, data)

    @staticmethod
    def compare_in(connection, actor, session_digest, key, data):
        changes = MaterialChanges(connection)
        previous = changes.replay(actor, key, data)
        if previous:
            return previous
        bindings = MaterialBindings(connection)
        binding = bindings.get(actor, data.binding_id, lock=True)
        if binding.revision != data.expected_binding_revision:
            raise BusinessError("stale_version", "Material binding changed.")
        bindings.require_scope(actor, binding)
        Materials(connection).read_refs(actor, binding.goal_id, binding.purpose, binding.refs)
        report = changes.compare(
            actor, key, data, goal_id=binding.goal_id, purpose=binding.purpose, refs=binding.refs,
        )
        review = MaterialChangeReviews(connection).ensure(actor, session_digest, report)
        if (
            review and review.status == "reviewed" and review.result
            and review.result.classification == "semantic_change"
        ):
            MaterialUpdates(connection).ensure(actor.id, session_digest, review.id, report.id)
        return report

    def get(self, token, check_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            return MaterialChanges(connection).get(actor, check_id)
