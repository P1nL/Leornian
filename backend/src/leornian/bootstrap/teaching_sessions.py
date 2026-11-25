from leornian.agent_runtime.repository import Runs
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.gates import Gates
from leornian.modules.execution.application import Execution
from leornian.modules.execution.example_contracts import example_capability
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.compositions import Compositions
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.modules.tutor.teaching_session_contracts import ArtifactQuestionFeedback
from leornian.modules.tutor.teaching_sessions import TeachingSessions
from leornian.shared_kernel.errors import BusinessError


class TeachingSessionWorkflow:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def event(connection, actor, conversation_id):
        Events(connection).append(
            actor.id, "tutor.teaching_session_updated", conversation_id,
            EventPayload(conversation_id=conversation_id),
        )

    def get(self, token, conversation_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return TeachingSessions(connection).get(conversation_id)

    def branches(self, token, conversation_id, before=None, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return TeachingSessions(connection).branches(actor, conversation_id, before, limit)

    def receipt(self, token, conversation_id, action_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return TeachingSessions(connection).command_receipt(conversation_id, action_id)

    def command(self, token, conversation_id, command):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            tutor = Tutor(PgTutorStore(connection))
            conversation = tutor.get(actor, conversation_id)
            sessions = TeachingSessions(connection)
            receipt = sessions.receipt(conversation_id, command)
            if receipt:
                return receipt
            from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
            from leornian.modules.tutor.teaching_intents import TeachingIntents

            TeachingContinuationWorkflow.preempt_in(connection, actor, conversation_id)
            conversation = tutor.get(actor, conversation_id, lock=True)
            if Runs(connection).active(conversation_id):
                raise BusinessError(
                    "run_active", "Finish or explicitly cancel the foreground Turn."
                )
            advance_to = None
            if command.action in {"open", "set_topic", "finish_node"}:
                from leornian.bootstrap.teaching_context import TeachingContext

                Gates(connection).require_no_exam(actor)
                TeachingContext.build(connection, actor, conversation, command.focus)
                if command.action == "finish_node" and command.focus.kind == "node":
                    from leornian.modules.learning.planning import Plans

                    plan = Plans(connection).get(actor, command.focus.plan_id)
                    nodes = plan.active.document.nodes
                    index = [node.key for node in nodes].index(command.focus.node_key)
                    if index + 1 < len(nodes):
                        advance_to = command.focus.model_copy(update={
                            "node_key": nodes[index + 1].key, "lesson_id": None,
                        })
            result = sessions.control(conversation_id, command, advance_to=advance_to)
            if TeachingIntents(connection).invalidate(
                conversation_id, result.continuation_generation,
            ):
                Events(connection).append(
                    actor.id, "tutor.teaching_intent_updated", conversation_id,
                    EventPayload(conversation_id=conversation_id),
                )
            TeachingIntents(connection).wake(conversation_id)
            sessions.record(command, result)
            self.event(connection, actor, conversation_id)
            return result

    @staticmethod
    def context_in(connection, actor, turn_id, manifest=None, *, node_turn=False):
        sessions = TeachingSessions(connection)
        binding = sessions.require_current(turn_id)
        if not binding:
            return None
        session = sessions.get(binding["conversation_id"])
        result = {
            "generation": session.generation, "mode": session.mode, "paused": session.paused,
            "branch_id": binding["teaching_branch_id"],
        }
        if binding["request_payload"].get("node_pacing"):
            result["node_pacing"] = True
        if not binding["teaching_branch_id"]:
            return result
        branch = sessions.branch(session.conversation_id, binding["teaching_branch_id"])
        artifact = LearningArtifacts(connection).row(
            actor, session.conversation_id, branch["anchor_artifact_id"], lock=True,
        )
        if artifact["state"] in {"cancelled", "superseded"} or (
            artifact["public_identity"] != branch["content_identity"]
        ):
            raise BusinessError("stale_version", "Question anchor is no longer current.")
        from leornian.bootstrap.learning_artifacts import (
            LearningArtifactWorkflow,
            UnsupportedPresentation,
        )

        capabilities = binding["request_payload"].get("presentation_capabilities", {})
        actions = capabilities.get("actions", [])

        def reader(*versions, legacy=None):
            if not node_turn:
                return legacy or versions[0]
            return next((item for item in versions if item in actions), None)

        if manifest and manifest.get("anchor_revision") != artifact["revision"]:
            raise BusinessError("stale_version", "Question anchor changed during this Turn.")
        try:
            view = LearningArtifactWorkflow(None).view_in(
                connection, actor, session.conversation_id, artifact["id"],
                allow_compositions=not node_turn or
                "learning_composition.v2" in capabilities.get("versions", []),
                response_capability=reader("learning_responses.v1"),
                code_review_capability=reader("learning_code_review.v2", "learning_code_review.v1",
                                              legacy="learning_code_review.v1"),
                program_capability=reader("learning_programs.v2", "learning_programs.v1"),
                direct_answer_capability=reader("learning_direct_answers.v1"),
                hint_capability=reader("learning_hints.v1"),
                demo_capability=reader("learning_demo_events.v1"),
                example_capability=example_capability(actions),
            )
            public_anchor = view.model_dump(mode="json")
        except UnsupportedPresentation:
            if not node_turn:
                raise
            LearningArtifactWorkflow.current(connection, actor, session.conversation_id, artifact)
            public_anchor = {
                "id": str(artifact["id"]), "revision": artifact["revision"],
                "kind": artifact["kind"], "renderer_available": False, "allowed_actions": [],
            }
            result["anchor_unavailable"] = True
        if node_turn and example_capability(actions):
            outcomes = Execution(connection).reported_example_outcomes(
                actor, session.conversation_id, artifact["id"], artifact["revision"],
                binding["turn_started_at"],
            )
            public_anchor["reported_example_outcomes"] = outcomes
        elif public_anchor.get("example_runners"):
            receipt = Execution(connection).latest_reported_example(
                actor, session.conversation_id, artifact["id"], artifact["revision"],
                binding["turn_started_at"],
            )
            if receipt:
                public_anchor["last_reported_example"] = receipt
        result.update({
            "anchor_artifact_id": str(artifact["id"]),
            "anchor_revision": artifact["revision"],
            "content_identity": artifact["public_identity"],
            "public_anchor": public_anchor,
        })
        result["branch_id"] = str(binding["teaching_branch_id"])
        return result

    @staticmethod
    def publish_in(connection, actor, turn_id, text):
        sessions = TeachingSessions(connection)
        binding = sessions.require_current(turn_id)
        if not binding or not binding["teaching_branch_id"]:
            return
        branch = sessions.branch(binding["conversation_id"], binding["teaching_branch_id"])
        artifact = LearningArtifacts(connection).row(
            actor, binding["conversation_id"], branch["anchor_artifact_id"],
        )
        targets = []
        if artifact["kind"] == "learning_composition":
            presentation = Compositions(connection).get(actor, artifact["presentation_id"])
            targets += [
                (owner["source"]["content_ref"]["id"], owner["source"]["content_ref"]["slot"],
                 owner["component_id"]) for owner in presentation["owner_bindings"]
            ]
            targets += [
                (review["attempt"]["pack_id"], review["attempt"]["slot"], review["component_id"])
                for review in presentation["review_bindings"]
            ]
        else:
            targets.append((artifact["pack_id"], artifact["slot"], "root"))
        feedback = ArtifactQuestionFeedback(turn_id=turn_id, artifact_id=artifact["id"], text=text)
        for pack_id, slot, component in targets:
            pack = Packs(connection).row(actor, pack_id)
            item = next(item for item in Packs.document(pack).items if item.slot == slot)
            Exposures(connection).record(
                actor, pack_id, item, feedback,
                receipt_ref=f"artifact-question:{turn_id}:{component}",
            )
