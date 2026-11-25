from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.gates import Gates
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.learning.review_activities import ReviewActivities
from leornian.modules.learning.reviews import Reviews
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError


class ReviewsWorkflow:
    def __init__(self, database):
        self.database = database

    def list(self, token, conversation_id=None):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            if conversation_id:
                Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            activities = ReviewActivities(connection)
            activities.ensure_due(actor)
            return activities.list(actor, conversation_id)

    def get(self, token, activity_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            store = ReviewActivities(connection)
            return store.view(actor, store.row(actor, activity_id))

    def logs(self, token, card_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return ReviewActivities(connection).logs(actor, card_id)

    def receipt(self, token, activity_id, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return ReviewActivities(connection).receipt(actor, activity_id, key)

    def present(self, token, activity_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            store = ReviewActivities(connection)
            request = {"action": "present", **data.model_dump(mode="json")}
            receipt = store.receipt(actor, activity_id, key, request)
            if receipt:
                return receipt
            conversation = Tutor(PgTutorStore(connection)).get(
                actor, data.conversation_id, lock=True,
            )
            row = store.lock_for_schedule(actor, activity_id)
            card = store.require_current(actor, row)
            if card.revision != data.expected_card_revision:
                raise BusinessError("stale_version", "Review card changed.")
            if store.view(actor, row).goal_id != conversation.goal_id:
                raise BusinessError("precondition_failed", "Review belongs to a different goal.")
            Gates(connection).require_no_exam(actor)
            result = store.present(actor, row, conversation.id)
            store.remember(actor, activity_id, key, request, result)
            return result

    def respond(self, token, activity_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            store = ReviewActivities(connection)
            request = {"action": "respond", **data.model_dump(mode="json")}
            receipt = store.receipt(actor, activity_id, key, request)
            if receipt:
                return receipt
            row = store.lock_for_schedule(actor, activity_id)
            if row["state"] != "presented":
                raise BusinessError("precondition_failed", "Present this review in a conversation.")
            Gates(connection).require_no_exam(actor)
            card, _ = Reviews(connection).respond(actor, row["card_id"], key, data)
            result = store.view(actor, store.row(actor, activity_id))
            store.remember(actor, activity_id, key, request, result)
            Events(connection).append(
                actor.id, "learning.review_recorded", card.track_id or card.id,
                EventPayload(track_id=card.track_id),
            )
            return result

    def cancel(self, token, activity_id, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            store = ReviewActivities(connection)
            request = {"action": "cancel"}
            receipt = store.receipt(actor, activity_id, key, request)
            if receipt:
                return receipt
            row = store.row(actor, activity_id, lock=True)
            result = store.cancel(actor, row)
            store.remember(actor, activity_id, key, request, result)
            return result
