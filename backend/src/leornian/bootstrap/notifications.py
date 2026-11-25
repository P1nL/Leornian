from leornian.delivery.notifications import Notifications
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore


class NotificationsWorkflow:
    def __init__(self, database):
        self.database = database

    def list(self, token, before=None, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Notifications(connection).list(actor, before, max(1, min(limit, 100)))

    def read(self, token, notification_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return Notifications(connection).read(actor, notification_id)
