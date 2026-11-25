"""Tutor admission for committed results and visible node windows."""

from leornian.agent_runtime.contracts import TurnAccepted
from leornian.agent_runtime.repository import Runs
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.gates import Gates
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.modules.tutor.teaching_intent_contracts import TeachingIntent
from leornian.modules.tutor.teaching_intents import TeachingIntents
from leornian.modules.tutor.teaching_sessions import TeachingSessions
from leornian.shared_kernel.errors import BusinessError


class TeachingContinuationWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def continue_node(self, token, conversation_id, command):
        from leornian.bootstrap.tutor import TutorWorkflow

        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate(token)
            store = PgTutorStore(connection)
            Tutor(store).get(actor, conversation_id, lock=True)
            anchor = command.after_turn_id or "opening"
            key = f"node-window:{command.expected_session_revision}:{anchor}"
            prior = store.requested_turn(conversation_id, key)
            runs, intents = Runs(connection), TeachingIntents(connection)
            if prior:
                origin = intents.for_turn(prior.id)
                if prior.context_focus != command.focus or not (
                    origin and origin["trigger_kind"] == "node_window"
                ):
                    raise BusinessError("idempotency_conflict", "Node window binding changed.")
                run = runs.for_turn(actor.id, prior.id)
                task = Deliveries(connection).for_run(run.id)
                return TurnAccepted(run_id=run.id, turn_id=prior.id, delivery_task_id=task["id"])
            session = TeachingSessions(connection).get(conversation_id)
            if not session or session.revision != command.expected_session_revision or (
                session.focus != command.focus or session.mode != "guided" or session.paused
                or session.active_branch_id or not session.node_window
                or session.node_window.after_turn_id != command.after_turn_id
                or session.node_window.next_step not in {"opening", "can_continue"}
            ):
                raise BusinessError("stale_version", "本次续讲窗口已关闭。")
            if runs.active(conversation_id):
                raise BusinessError("run_active", "当前教学任务尚未结束。")
            intent = intents.create_window(actor, session, key)
            data = TurnInput(
                text=(
                    "Open this node with one useful explanation in the learner's language."
                    if command.after_turn_id is None else
                    "Continue from the last delivered explanation and its unfinished objective."
                ),
                focus=session.focus, teaching_session_revision=session.revision, node_pacing=True,
                presentation_capabilities=command.presentation_capabilities,
            )
            accepted = TutorWorkflow(self.database, self.settings)._submit_in(
                connection, actor, identity.digest(token), conversation_id, key, data,
                "teaching", None, intent=intent,
            )
            intents.state(intent["id"], "dispatched", run_id=accepted.run_id)
            self.event(connection, actor, {**intent, "run_id": accepted.run_id})
            return accepted

    @staticmethod
    def event(connection, actor, intent):
        Events(connection).append(
            actor.id, "tutor.teaching_intent_updated", intent["id"],
            EventPayload(
                conversation_id=intent["conversation_id"], teaching_intent_id=intent["id"],
                run_id=intent.get("run_id"),
            ),
        )

    @staticmethod
    def view_in(connection, actor, intent):
        values = {key: intent[key] for key in TeachingIntent.model_fields if key != "run_status"}
        values["run_status"] = (
            Runs(connection).get(actor.id, intent["run_id"]).status if intent["run_id"] else None
        )
        return TeachingIntent(**values)

    @staticmethod
    def capture_in(connection, actor, conversation_id, artifact_id, kind, reference):
        """Called only by original committed owner-result/demo producers in their transaction."""
        session = TeachingSessions(connection).get(conversation_id)
        if not session or session.mode != "guided" or (
            session.continuation_policy != "after_result.v1"
        ):
            return
        from leornian.modules.tutor.proactive import ProactivePreferences

        preference = ProactivePreferences(connection).get(actor, conversation_id)
        if preference and not preference.enabled:
            return
        artifact = LearningArtifacts(connection).row(actor, conversation_id, artifact_id)
        turn = Tutor(PgTutorStore(connection)).get_turn(conversation_id, artifact["source_turn_id"])
        if turn.teaching_branch_id or turn.context_focus != session.focus or (
            artifact["state"] in {"cancelled", "superseded"}
        ):
            return
        run = Runs(connection).for_turn(actor.id, turn.id)
        task = Deliveries(connection).for_run(run.id)
        if not task or task["status"] != "accepted":
            return
        row = TeachingIntents(connection).create(
            actor, session, artifact, run.id, kind, reference,
        )
        if row:
            TeachingContinuationWorkflow.event(connection, actor, row)

    @staticmethod
    def preempt_in(connection, actor, conversation_id):
        """A new explicit command outranks an automatic foreground, never a user's Run."""
        from leornian.bootstrap.tutor import TutorWorkflow

        runs, intents = Runs(connection), TeachingIntents(connection)
        foreground = runs.foreground(actor.id, conversation_id)
        intent = intents.for_turn(foreground.turn_id) if foreground else None
        if intent and intent["state"] == "dispatched":
            cancelled = TutorWorkflow.cancel_in(connection, actor, foreground.id)
            if cancelled.status == "cancelled":
                intents.state(intent["id"], "superseded", "explicit_user_input")
                TeachingContinuationWorkflow.event(connection, actor, intent)

    def list(self, token, conversation_id, before=None, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return [
                self.view_in(connection, actor, row)
                for row in TeachingIntents(connection).page(actor, conversation_id, before, limit)
            ]

    def cancel_receipt(self, token, conversation_id, intent_id, action_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            store = TeachingIntents(connection)
            store.row(actor, conversation_id, intent_id)
            receipt = store.cancellation(intent_id, action_id)
            if receipt is None:
                raise BusinessError("not_found", "No committed intent cancellation.")
            return TeachingIntent(**receipt)

    def cancel(self, token, conversation_id, intent_id, command):
        from leornian.bootstrap.tutor import TutorWorkflow

        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            tutor = Tutor(PgTutorStore(connection))
            tutor.get(actor, conversation_id)
            store = TeachingIntents(connection)
            intent = store.row(actor, conversation_id, intent_id, lock=True)
            receipt = store.cancellation(intent_id, command.client_action_id)
            if receipt is not None:
                return TeachingIntent(**receipt)
            if intent["state"] == "pending":
                store.state(intent_id, "cancelled", "explicit_cancel")
            elif intent["state"] == "dispatched" and intent["trigger_kind"] == "review_due":
                from leornian.modules.learning.review_activities import ReviewActivities

                activities = ReviewActivities(connection)
                activity = activities.row(actor, intent["review_activity_id"], lock=True)
                if activity["state"] in {"due", "presented"}:
                    activities.cancel(actor, activity)
                    store.state(intent_id, "cancelled", "explicit_cancel")
            elif intent["state"] == "dispatched" and Runs(connection).get(
                actor.id, intent["run_id"]
            ).status in {"queued", "running", "blocked_unknown"}:
                cancelled = TutorWorkflow.cancel_in(connection, actor, intent["run_id"])
                if cancelled.status == "cancelled":
                    store.state(intent_id, "cancelled", "explicit_cancel")
            tutor.get(actor, conversation_id, lock=True)
            current = store.row(actor, conversation_id, intent_id)
            result = self.view_in(connection, actor, current)
            store.remember_cancel(intent_id, command.client_action_id, result)
            if intent["state"] != current["state"]:
                self.event(connection, actor, current)
            return result

    @staticmethod
    def source_in(connection, actor, intent):
        from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

        conversation_id = intent["conversation_id"]
        session = TeachingSessions(connection).get(conversation_id)
        if not session or (
            session.continuation_generation != intent["generation"]
            or session.focus != TeachingFocus(**intent["focus"])
            or session.mode != "guided" or session.continuation_policy != "after_result.v1"
        ):
            raise BusinessError("stale_version", "Continuation session changed.")
        artifacts = LearningArtifacts(connection)
        artifact = artifacts.row(actor, conversation_id, intent["artifact_id"])
        if artifact["public_identity"] != intent["content_identity"] or (
            artifact["state"] in {"cancelled", "superseded"}
        ) or TeachingIntents(connection).latest_mainline(
            actor, conversation_id, session.focus,
        ) != artifact["id"]:
            raise BusinessError("stale_version", "Continuation source was replaced or cancelled.")
        LearningArtifactWorkflow.current(
            connection, actor, conversation_id, artifact, require_unanswered=False,
        )
        view = LearningArtifactWorkflow(None).view_in(
            connection, actor, conversation_id, artifact["id"], allow_compositions=True,
            response_capability="learning_responses.v1",
            code_review_capability="learning_code_review.v1",
            program_capability="learning_programs.v2",
            direct_answer_capability="learning_direct_answers.v1",
            hint_capability="learning_hints.v1", demo_capability="learning_demo_events.v1",
        )
        kind, _, result_id = intent["trigger_ref"].partition(":")
        result_refs = []
        if kind == "demo":
            result_refs = [
                str(demo.completions[0].id) for demo in view.demo_bindings
                if demo.state == "completed" and demo.completions
                and demo.completions[0].generation == demo.generation
            ]
        elif artifact["kind"] == "learning_composition":
            result_refs = [
                str(component.result.id) for component in view.component_bindings
                if component.result and component.state == "completed"
            ]
        elif view.result:
            result_refs = [str(view.result.id)]
        if result_id not in result_refs:
            raise BusinessError("stale_version", "The triggering result is no longer current.")
        return session, artifact, view

    @staticmethod
    def context_in(connection, actor, turn_id, manifest=None):
        intent = TeachingIntents(connection).for_turn(turn_id)
        if not intent:
            return None
        if intent["state"] != "dispatched":
            raise BusinessError("stale_version", "Continuation was cancelled or superseded.")
        if intent["trigger_kind"] == "node_window":
            session = TeachingSessions(connection).get(intent["conversation_id"])
            if not session or session.mode != "guided" or session.paused or (
                session.active_branch_id or session.continuation_generation != intent["generation"]
                or session.focus != TeachingFocus(**intent["focus"])
                or not session.node_window or session.node_window.after_turn_id != turn_id
            ):
                raise BusinessError("stale_version", "Node window is no longer current.")
            return {"id": str(intent["id"]), "trigger_kind": "node_window",
                    "trigger_ref": intent["trigger_ref"],
                    "window_phase": "opening" if intent["trigger_ref"].endswith(":opening")
                    else "continuation"}
        session, artifact, view = TeachingContinuationWorkflow.source_in(connection, actor, intent)
        if session.paused or session.active_branch_id:
            raise BusinessError("stale_version", "Continuation no longer has the mainline.")
        current = {
            "id": str(intent["id"]), "generation": intent["generation"],
            "trigger_kind": intent["trigger_kind"], "trigger_ref": intent["trigger_ref"],
            "source_artifact_id": str(artifact["id"]), "source_revision": artifact["revision"],
            "content_identity": artifact["public_identity"],
        }
        if manifest and current != manifest:
            raise BusinessError("stale_version", "Continuation result changed during generation.")
        return {**current, "public_result": view.model_dump(mode="json")}

    def reconcile_once(self, limit=20):
        from leornian.bootstrap.tutor import TutorWorkflow

        with self.database.transaction(snapshot=True) as connection:
            candidates = TeachingIntents(connection).pending(limit)
        dispatched = 0
        for candidate in candidates:
            with self.database.transaction() as connection:
                if candidate["trigger_kind"] == "review_due":
                    from leornian.bootstrap.proactive_teaching import ProactiveTeachingWorkflow

                    dispatched += int(
                        ProactiveTeachingWorkflow.dispatch_review_in(connection, candidate),
                    )
                    continue
                runs = Runs(connection)
                source = runs.admission_snapshot(candidate["actor_id"], candidate["source_run_id"])
                try:
                    actor = Identity(PgIdentityStore(
                        connection, serialize_actor=True,
                    )).authenticate_digest(source["session_digest"])
                except BusinessError:
                    # No new session or development credential is substituted.
                    store = TeachingIntents(connection)
                    actor = Identity(PgIdentityStore(connection)).get_actor(candidate["actor_id"])
                    Tutor(PgTutorStore(connection)).get(
                        actor, candidate["conversation_id"], lock=True,
                    )
                    intent = store.row(
                        actor, candidate["conversation_id"], candidate["id"], lock=True,
                    )
                    if intent["state"] == "pending":
                        store.state(intent["id"], "superseded", "unauthorized")
                        self.event(connection, actor, intent)
                    continue
                Tutor(PgTutorStore(connection)).get(actor, candidate["conversation_id"], lock=True)
                store = TeachingIntents(connection)
                intent = store.row(actor, candidate["conversation_id"], candidate["id"], lock=True)
                if intent["state"] != "pending":
                    continue
                try:
                    session = TeachingSessions(connection).get(intent["conversation_id"])
                    if not session or session.continuation_generation != intent["generation"]:
                        raise BusinessError("stale_version", "Continuation generation changed.")
                    reason = (
                        "paused" if session.paused else "question_branch"
                        if session.active_branch_id else "foreground"
                        if runs.active(intent["conversation_id"]) else "higher_priority_intent"
                        if store.first(intent["conversation_id"])["id"] != intent["id"] else None
                    )
                    if not reason:
                        from leornian.bootstrap.proactive_teaching import ProactiveTeachingWorkflow

                        reason = ProactiveTeachingWorkflow.window_reason_in(
                            connection, actor, intent["conversation_id"],
                        )
                    if not reason:
                        try:
                            Gates(connection).require_no_exam(actor)
                        except BusinessError:
                            reason = "active_exam"
                    if reason:
                        store.wait(intent["id"], reason)
                        if reason != intent["wait_reason"]:
                            self.event(connection, actor, intent)
                        continue
                    with connection.transaction():
                        session, _, _ = self.source_in(connection, actor, intent)
                        binding = TeachingSessions(connection).binding(source["input_ref"])
                        data = TurnInput(
                            text="Continue the guided lesson from this committed result.",
                            focus=session.focus, teaching_session_revision=session.revision,
                            node_pacing=bool(
                                binding and binding["request_payload"].get("node_pacing")
                            ),
                        )
                        accepted = TutorWorkflow(self.database, self.settings)._submit_in(
                            connection, actor, source["session_digest"], intent["conversation_id"],
                            f"teaching-intent:{intent['id']}", data, "teaching", None,
                            intent=intent, source_run=source,
                        )
                    store.state(intent["id"], "dispatched", run_id=accepted.run_id)
                    current = store.row(actor, intent["conversation_id"], intent["id"])
                    self.event(connection, actor, current)
                    dispatched += 1
                except BusinessError as error:
                    if error.code == "model_unavailable":
                        store.wait(intent["id"], error.code)
                        if intent["wait_reason"] != error.code:
                            self.event(connection, actor, intent)
                    else:
                        store.state(intent["id"], "superseded", error.code)
                        self.event(connection, actor, intent)
        return dispatched
