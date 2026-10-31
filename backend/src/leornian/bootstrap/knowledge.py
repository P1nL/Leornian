from uuid import UUID

from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.knowledge.contracts import AdmitSource, Source, SourceInput, SourceRevision
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.platform.database import Database


class KnowledgeWorkflow:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _event(connection, actor_id, source: Source, action: str):
        Events(connection).append(
            actor_id,
            "knowledge." + action,
            source.id,
            EventPayload(source_id=source.id, goal_id=source.goal_id),
        )

    def create(self, token: str, goal_id: UUID, key: str, data: SourceInput) -> Source:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
            source, created = Knowledge(connection).create(actor, goal_id, key, data)
            if created:
                self._event(connection, actor.id, source, "created")
            return source

    def revise(self, token: str, source_id: UUID, data: SourceRevision) -> Source:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            source, changed = Knowledge(connection).revise(actor, source_id, data)
            if changed:
                self._event(connection, actor.id, source, "revised")
            return source

    def admit(self, token: str, source_id: UUID, data: AdmitSource) -> Source:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            source, changed = Knowledge(connection).admit(
                actor,
                source_id,
                data.expected_revision,
                data.valid_until,
            )
            if changed:
                self._event(connection, actor.id, source, "admitted")
            return source

    def revoke(self, token: str, source_id: UUID, revision: int) -> Source:
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            source, changed = Knowledge(connection).revoke(actor, source_id, revision)
            if changed:
                self._event(connection, actor.id, source, "revoked")
            return source
