from datetime import UTC, datetime

from leornian.agent_runtime.repository import Runs
from leornian.modules.assessment.gates import Gates
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.learning.review_activities import ReviewActivities
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.proactive import ProactivePreferences
from leornian.modules.tutor.proactive_contracts import within_window
from leornian.modules.tutor.teaching_intents import TeachingIntents
from leornian.modules.tutor.teaching_sessions import TeachingSessions
from leornian.shared_kernel.errors import BusinessError


class ProactiveTeachingWorkflow:
    """Due facts use the existing intent queue and conversation admission lock."""

    def __init__(self, database):
        self.database = database

    def preference(self, token, conversation_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return ProactivePreferences(connection).get(actor, conversation_id)

    def set_preference(self, token, conversation_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id, lock=True)
            result = ProactivePreferences(connection).set(
                actor, conversation_id, Identity.digest(token), key, data,
            )
            if not result.enabled:
                for row in TeachingIntents(connection).page(actor, conversation_id, limit=100):
                    if row["state"] == "pending":
                        TeachingIntents(connection).state(
                            row["id"], "cancelled", "proactive_disabled",
                        )
            return result

    def preference_receipt(self, token, conversation_id, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return ProactivePreferences(connection).receipt(actor, conversation_id, key)

    def scan_due_once(self, limit=100):
        from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow

        with self.database.transaction() as connection:
            ReviewActivities(connection).ensure_due()
            candidates = ProactivePreferences(connection).enabled(limit)
        captured = 0
        for preference in candidates:
            with self.database.transaction() as connection:
                try:
                    actor = Identity(PgIdentityStore(
                        connection, serialize_actor=True,
                    )).authenticate_digest(preference["session_digest"])
                except BusinessError:
                    continue
                conversation = Tutor(PgTutorStore(connection)).get(
                    actor, preference["conversation_id"], lock=True,
                )
                current = ProactivePreferences(connection).get(actor, conversation.id)
                session = TeachingSessions(connection).get(conversation.id)
                if not current or not current.enabled or not session or session.mode != "guided":
                    continue
                activities = ReviewActivities(connection).due_for_goal(actor, conversation.goal_id)
                for activity in activities:
                    if not ReviewActivities(connection).matches_focus(
                        actor, activity, session.focus,
                    ):
                        continue
                    intent = TeachingIntents(connection).create_review(
                        actor, session, activity, preference["session_digest"],
                    )
                    if intent:
                        TeachingContinuationWorkflow.event(connection, actor, intent)
                        captured += 1
        return captured

    @staticmethod
    def window_reason_in(connection, actor, conversation_id):
        preference = ProactivePreferences(connection).get(actor, conversation_id)
        if preference:
            if not preference.enabled:
                return "proactive_disabled"
            if not within_window(preference, datetime.now(UTC)):
                return "outside_teaching_window"
        return None

    @staticmethod
    def dispatch_review_in(connection, candidate):
        from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow

        intents = TeachingIntents(connection)
        try:
            actor = Identity(PgIdentityStore(
                connection, serialize_actor=True,
            )).authenticate_digest(candidate["session_digest"])
        except BusinessError:
            intents.state(candidate["id"], "superseded", "unauthorized")
            return False
        Tutor(PgTutorStore(connection)).get(actor, candidate["conversation_id"], lock=True)
        intent = intents.row(
            actor, candidate["conversation_id"], candidate["id"], lock=True,
        )
        if intent["state"] != "pending":
            return False
        session = TeachingSessions(connection).get(intent["conversation_id"])
        try:
            if not session or session.mode != "guided" or (
                session.continuation_generation != intent["generation"]
                or session.focus.model_dump(mode="json") != intent["focus"]
            ):
                raise BusinessError("stale_version", "Teaching scope changed.")
            preference = ProactivePreferences(connection).get(actor, intent["conversation_id"])
            if not preference or not preference.enabled:
                raise BusinessError("precondition_failed", "Proactive teaching was disabled.")
            activity = ReviewActivities(connection).lock_for_schedule(
                actor, intent["review_activity_id"],
            )
            ReviewActivities(connection).require_current(actor, activity)
            if not ReviewActivities(connection).matches_focus(actor, activity, session.focus):
                raise BusinessError("stale_version", "Review belongs to another teaching topic.")
            first = intents.first(intent["conversation_id"])
            reason = (
                "paused" if session.paused else "question_branch"
                if session.active_branch_id else "foreground"
                if Runs(connection).active(intent["conversation_id"]) else "higher_priority_intent"
                if first and first["id"] != intent["id"] else
                ProactiveTeachingWorkflow.window_reason_in(
                    connection, actor, intent["conversation_id"],
                )
            )
            if not reason:
                try:
                    Gates(connection).require_no_exam(actor)
                except BusinessError:
                    reason = "active_exam"
            if reason:
                intents.wait(intent["id"], reason)
                return False
            ReviewActivities(connection).present(actor, activity, intent["conversation_id"])
            intents.state(intent["id"], "dispatched")
            TeachingContinuationWorkflow.event(
                connection, actor, intents.row(actor, intent["conversation_id"], intent["id"]),
            )
            return True
        except BusinessError as error:
            intents.state(intent["id"], "superseded", error.code)
            TeachingContinuationWorkflow.event(connection, actor, intent)
            return False
