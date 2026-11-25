import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.item_supply import ItemSupply
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.choices import Choices
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.assessment.python_contracts import PythonTraining
from leornian.modules.assessment.responses import Responses
from leornian.modules.assessment.transfers import Transfers
from leornian.modules.execution.example_contracts import example_surface
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import ChoiceInput
from leornian.modules.knowledge.materials import digest
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.interaction_contracts import (
    ArtifactInteraction,
    LearningReply,
    NoInteraction,
    PacedLearningReply,
)
from leornian.modules.tutor.learning_artifact_contracts import (
    LearningArtifactView,
    LearningCandidate,
    LearningContentRef,
)
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.modules.tutor.program_interaction_contracts import ProgramCandidateOption
from leornian.modules.tutor.response_interaction_contracts import ResponseCandidateOption
from leornian.shared_kernel.errors import BusinessError


class UnsupportedPresentation(BusinessError):
    def __init__(self, message):
        super().__init__("precondition_failed", message)


class LearningArtifactWorkflow:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def event(connection, actor, artifact_id, conversation_id):
        Events(connection).append(
            actor.id,
            "tutor.learning_artifact_updated",
            artifact_id,
            EventPayload(learning_artifact_id=artifact_id, conversation_id=conversation_id),
        )

    @staticmethod
    def content(connection, actor, conversation_id, pack_id, slot):
        conversation = Tutor(PgTutorStore(connection)).get(actor, conversation_id)
        Gates(connection).require_no_exam(actor)
        Transfers(connection).require_regular_practice(actor, pack_id, slot)
        pack = Packs(connection).row(actor, pack_id)
        plan, _node, _materials = ItemSupply.current(connection, actor, pack)
        if plan.goal_id != conversation.goal_id or slot not in {"practice_1", "practice_2"}:
            raise BusinessError("not_found", "No practice candidate in this conversation.")
        item = next(
            i for i in Packs(connection).published_document(actor, pack_id).items if i.slot == slot
        )
        public = item.public()
        return pack, public, item

    @staticmethod
    def identity(public):
        return digest(public.model_dump_json())

    def candidate(self, token, conversation_id, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            kind = Packs(connection).row(actor, data.pack_id)["kind"]
            if kind not in {"choice", "python_io"}:
                raise BusinessError(
                    "precondition_failed",
                    "Use response-capable composition tools." if kind == "response"
                    else "Use the matching explicitly supported program composition tools.",
                )
            return self.candidate_in(connection, actor, conversation_id, data.pack_id, data.slot)

    @staticmethod
    def candidate_in(connection, actor, conversation_id, pack_id, slot, *, programs=False):
        supported = (
            {"sql_query", "python_project", "project_stdio", "web_project", "http_project"}
            if programs else {"choice", "python_io", "response"}
        )
        if Packs(connection).row(actor, pack_id)["kind"] not in supported:
            raise BusinessError(
                "precondition_failed", "This reader has no matching program action capability.",
            )
        pack, public, _item = LearningArtifactWorkflow.content(
            connection, actor, conversation_id, pack_id, slot
        )
        if LearningArtifactWorkflow.existing_result(connection, actor, pack, slot):
            raise BusinessError("precondition_failed", "This exact practice is already locked.")
        focus = TeachingFocus(
            kind="node", plan_id=pack["plan_id"],
            expected_plan_revision=pack["plan_revision"], node_key=pack["node_key"],
        )
        kind = {
            "python_io": "code_workspace", "choice": "knowledge_check",
            "response": "knowledge_response", "sql_query": "sql_workspace",
            "python_project": "project_workspace",
            "project_stdio": "project_workspace", "web_project": "project_workspace",
            "http_project": "project_workspace",
        }[pack["kind"]]
        identity = LearningArtifactWorkflow.identity(public)
        connection.execute(
            "INSERT INTO tutor.learning_candidates"
            "(id,actor_id,conversation_id,pack_id,slot,kind,focus,public_identity) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (uuid4(), actor.id, conversation_id, pack_id, slot, kind,
             Jsonb(focus.model_dump(mode="json")), identity),
        )
        row = connection.execute(
            "SELECT id FROM tutor.learning_candidates WHERE actor_id=%s AND conversation_id=%s "
            "AND pack_id=%s AND slot=%s AND public_identity=%s",
            (actor.id, conversation_id, pack_id, slot, identity),
        ).fetchone()
        values = dict(
            id=row["id"], conversation_id=conversation_id, kind=kind, focus=focus,
            title=public.title if hasattr(public, "title") else public.prompt,
            content_ref=LearningContentRef(
                id=pack_id, revision=pack["revision"], slot=slot, public_identity=identity
            ),
        )
        if programs:
            return ProgramCandidateOption(**values, presentation={"task": public})
        return (
            ResponseCandidateOption(**values, presentation={"question": public})
            if pack["kind"] == "response" else LearningCandidate(**values)
        )

    @staticmethod
    def candidates_in(
        connection, actor, conversation_id, focus, before=None, limit=20, *,
        responses=False, programs=False,
    ):
        if focus.kind != "node":
            return {"status": "completed", "items": [], "next_before": None}
        packs = Packs(connection).published_for_node(
            actor, focus.plan_id, focus.expected_plan_revision, focus.node_key, before, limit
        )
        items = []
        for pack in packs:
            supported = (
                {"sql_query", "python_project", "project_stdio", "web_project", "http_project"}
                if programs else
                {"response"} if responses else {"choice", "python_io"}
            )
            if pack["kind"] not in supported:
                continue
            for slot in ("practice_1", "practice_2"):
                try:
                    candidate = LearningArtifactWorkflow.candidate_in(
                        connection, actor, conversation_id, pack["id"], slot, programs=programs,
                    )
                except BusinessError as error:
                    if error.code not in {
                        "stale_version", "source_not_current", "precondition_failed", "not_found"
                    }:
                        raise
                    continue
                if LearningArtifacts(connection).delivered(actor, candidate.id):
                    continue
                if programs:
                    items.append(candidate.model_dump(mode="json"))
                    continue
                _, public, _ = LearningArtifactWorkflow.content(
                    connection, actor, conversation_id, pack["id"], slot
                )
                items.append({
                    **candidate.model_dump(mode="json"),
                    "presentation": {
                        "type": candidate.kind,
                        "task" if candidate.kind == "code_workspace" else "question":
                            public.model_dump(mode="json"),
                    },
                })
        return {
            "status": "completed", "items": items,
            "next_before": str(packs[-1]["id"]) if len(packs) == limit else None,
        }

    @staticmethod
    def existing_result(connection, actor, pack, slot):
        if pack["kind"] in {
            "sql_query", "python_project", "project_stdio", "web_project", "http_project",
        }:
            return ProgramAssessment(connection).latest(actor, pack["id"], slot)
        if pack["kind"] == "response":
            return next(
                (r for r in Responses(connection).for_pack(actor, pack["id"]) if r.slot == slot),
                None,
            )
        if pack["kind"] == "python_io":
            return next(
                (
                    r
                    for r in PythonAssessment(connection).for_pack(actor, pack["id"], "training")
                    if r["slot"] == slot
                ),
                None,
            )
        return next(
            (r for r in Choices(connection).for_pack(actor, pack["id"]) if r.slot == slot), None
        )

    @staticmethod
    def current(
        connection, actor, conversation_id, candidate, *,
        require_unanswered=True, prepared_run_id=None, allow_programs=False,
    ):
        if candidate["kind"] == "learning_composition":
            from leornian.bootstrap.compositions import CompositionWorkflow

            return CompositionWorkflow.current(
                connection, actor, conversation_id, candidate, prepared_run_id=prepared_run_id
            )
        if candidate["kind"] in {"sql_workspace", "project_workspace"} and not allow_programs:
            raise BusinessError(
                "precondition_failed", "Program candidates require a program-capable composition.",
            )
        pack, public, item = LearningArtifactWorkflow.content(
            connection, actor, conversation_id, candidate["pack_id"], candidate["slot"]
        )
        if LearningArtifactWorkflow.identity(public) != candidate["public_identity"]:
            raise BusinessError("stale_version", "Candidate public content changed.")
        if require_unanswered and LearningArtifactWorkflow.existing_result(
            connection, actor, pack, candidate["slot"]
        ):
            raise BusinessError("precondition_failed", "This practice is already locked.")
        return pack, public, item

    @staticmethod
    def bind_in(connection, actor, conversation_id, turn, candidate_id, focus, *, created):
        artifacts = LearningArtifacts(connection)
        previous = artifacts.for_turn(actor, conversation_id, turn.id)
        if not created:
            client = previous if previous and previous["selection_origin"] == "client" else None
            if (client["id"] if client else None) != candidate_id:
                raise BusinessError("idempotency_conflict", "Turn candidate changed.")
            return
        if candidate_id is None:
            return
        candidate = artifacts.candidate(actor, conversation_id, candidate_id)
        if candidate["kind"] == "knowledge_response":
            raise BusinessError(
                "precondition_failed", "Response candidates require a checked composition."
            )
        LearningArtifactWorkflow.current(connection, actor, conversation_id, candidate)
        if TeachingFocus(**candidate["focus"]) != focus:
            raise BusinessError("stale_version", "Candidate needs its exact teaching focus.")
        if artifacts.delivered(actor, candidate_id):
            raise BusinessError("precondition_failed", "Candidate was already delivered.")
        revision = connection.execute(
            "SELECT teaching_revision FROM tutor.conversations WHERE id=%s",
            (conversation_id,),
        ).fetchone()["teaching_revision"]
        connection.execute(
            "INSERT INTO tutor.learning_turn_candidates"
            "(turn_id,candidate_id,expected_teaching_revision) VALUES (%s,%s,%s)",
            (turn.id, candidate_id, revision),
        )

    @staticmethod
    def context_in(connection, actor, conversation_id, turn_id):
        candidate = LearningArtifacts(connection).for_turn(actor, conversation_id, turn_id)
        if not candidate:
            return None
        _pack, public, _item = LearningArtifactWorkflow.current(
            connection, actor, conversation_id, candidate
        )
        return {
            "exact_handle": str(candidate["id"]),
            "kind": candidate["kind"],
            "intent": "introduce_only",
            "public_content": public.model_dump(mode="json"),
            "execution_and_grading": "only_after_explicit_learner_action",
        }

    @staticmethod
    def reply(content, *, paced=False):
        if paced:
            return PacedLearningReply.model_validate_json(content, strict=True)
        try:
            data = json.loads(content)
        except (TypeError, ValueError):
            return None
        return LearningReply.model_validate_json(content, strict=True) if (
            isinstance(data, dict) and "interaction" in data
        ) else None

    @staticmethod
    def pending_workspace_work(connection, row):
        runs = Runs(connection)
        for name in ("request_learning_program_supply", "request_learning_practice_supply",
                     "get_learning_program_supply", "get_learning_practice_supply"):
            if name in row["tool_contracts"] and any(
                result.get("task_id") and (
                    result.get("status") == "accepted" or result.get("supply_status")
                    in {"running", "waiting"} and result.get("pack_status") != "published"
                ) for result in runs.tool_outputs(row["id"], name)
            ):
                return True
        if "request_execution_environment" in row["tool_contracts"]:
            for result in runs.tool_outputs(row["id"], "request_execution_environment"):
                demand = result.get("demand") or {}
                if result.get("status") == "accepted" and demand.get("status") in {
                    "waiting_authorization", "waiting_engine", "queued", "preparing", "verifying",
                } and demand.get("decision") not in {"defer", "decline", "revoke"}:
                    return True
        return False

    @staticmethod
    def validate_reply_in(connection, actor, row, task, content):
        reply = LearningArtifactWorkflow.reply(
            content, paced=task["context_manifest"].get("node_pacing"),
        )
        if reply is not None and task["context_manifest"].get("node_turn_contract") == 1:
            reply = reply.model_copy(update={"text": json.loads(content)["text"]})
        if isinstance(reply, PacedLearningReply) and (
            task["context_manifest"].get("teaching_intent", {}).get("window_phase") == "opening"
            and reply.pacing.next_step not in {"can_continue", "wrap_up"}
        ):
            raise ModelProtocolError("opening_requires_explanation")
        if isinstance(reply, PacedLearningReply):
            manifest = task["context_manifest"]
            choice = reply.pacing.practice_choice
            if choice:
                turn = PgTutorStore(connection).get_turn(row["scope_id"], row["input_ref"])
                if turn.teaching_intent_id or choice.quote not in turn.user_text:
                    raise ModelProtocolError("practice_choice_needs_learner_quote")
            deferred = choice.choice == "defer" if choice else manifest.get("practice_deferred")
            if deferred and (reply.pacing.check_topic or (
                manifest.get("teaching_intent") and reply.pacing.next_step == "wait_for_action"
            )):
                raise ModelProtocolError("practice_is_deferred")
        if isinstance(reply, PacedLearningReply) and reply.pacing.check_topic and (
            reply.pacing.check_topic.casefold() in {
                topic.casefold() for topic in task["context_manifest"].get("checked_topics", [])
            }
        ):
            raise ModelProtocolError("repeated_comprehension_check")
        if isinstance(reply, PacedLearningReply) and reply.pacing.next_step == "wait_for_action":
            session = manifest.get("teaching_session") or {}
            if (
                reply.interaction.type == "none" and (
                    manifest.get("learning_composition_contract") == 2
                    or manifest.get("node_turn_contract") == 1
                )
                and (not session.get("anchor_artifact_id") or session.get("anchor_unavailable"))
                and not LearningArtifactWorkflow.pending_workspace_work(connection, row)
            ):
                raise ModelProtocolError("missing_teaching_action_surface")
        if reply is None:
            if task["context_manifest"].get("node_turn_contract") and LearningArtifacts(
                connection,
            ).for_turn(actor, row["scope_id"], row["input_ref"]):
                raise ModelProtocolError("learning_reply_selection_required")
            if task["context_manifest"].get("learning_interaction_contract") == 1 and any(
                result.get("status") == "completed"
                and isinstance(result.get("candidate"), dict)
                and result["candidate"].get("id")
                for name in row["tool_contracts"]
                if name.startswith("prepare_learning_")
                for result in Runs(connection).tool_outputs(row["id"], name)
            ):
                raise ModelProtocolError("learning_reply_selection_required")
            return None
        if (
            row["tool_contracts"].get("list_learning_artifact_candidates") != 1
            or task["context_manifest"].get("learning_interaction_contract") != 1
        ):
            raise ModelProtocolError("learning_interaction_not_permitted")
        existing = LearningArtifacts(connection).for_turn(actor, row["scope_id"], row["input_ref"])
        selection = reply.interaction
        if selection.type == "artifact" and PgTutorStore(connection).get_turn(
            row["scope_id"], row["input_ref"],
        ).teaching_branch_id:
            raise ModelProtocolError("question_branch_cannot_replace_anchor")
        if selection.type != "artifact":
            if existing:
                raise ModelProtocolError("explicit_learning_candidate_required")
            return reply
        if existing:
            if existing["id"] != selection.exact_handle:
                raise ModelProtocolError("explicit_learning_candidate_changed")
        else:
            listed = {
                option["id"]
                for result in Runs(connection).tool_outputs(
                    row["id"], "list_learning_artifact_candidates"
                )
                if result.get("status") == "completed"
                for option in result["items"]
            }
            if (
                row["tool_contracts"].get("prepare_learning_composition") == 1
                and task["context_manifest"].get("learning_composition_contract") == 2
            ):
                for tool in ("prepare_learning_composition", "prepare_learning_template"):
                    if row["tool_contracts"].get(tool) != 1:
                        continue
                    listed.update(
                        result["candidate"]["id"]
                        for result in Runs(connection).tool_outputs(row["id"], tool)
                        if result.get("status") == "completed"
                    )
            if (
                row["tool_contracts"].get("prepare_learning_practice_composition") == 1
                and task["context_manifest"].get("learning_practice_composition_contract") == 1
            ):
                listed.update(
                    result["candidate"]["id"]
                    for result in Runs(connection).tool_outputs(
                        row["id"], "prepare_learning_practice_composition"
                    )
                    if result.get("status") == "completed"
                )
            if (
                row["tool_contracts"].get("prepare_learning_response_composition") == 1
                and task["context_manifest"].get("learning_response_composition_contract") == 1
            ):
                listed.update(
                    result["candidate"]["id"]
                    for result in Runs(connection).tool_outputs(
                        row["id"], "prepare_learning_response_composition"
                    ) if result.get("status") == "completed"
                )
            if (
                row["tool_contracts"].get("prepare_learning_code_review_composition") == 1
                and task["context_manifest"].get("learning_code_review_contract") == 1
            ):
                listed.update(
                    result["candidate"]["id"]
                    for result in Runs(connection).tool_outputs(
                        row["id"], "prepare_learning_code_review_composition"
                    ) if result.get("status") == "completed"
                )
            if (
                row["tool_contracts"].get("prepare_learning_code_review_composition_v2") == 1
                and task["context_manifest"].get("learning_code_review_contract") == 2
            ):
                listed.update(
                    result["candidate"]["id"]
                    for result in Runs(connection).tool_outputs(
                        row["id"], "prepare_learning_code_review_composition_v2"
                    ) if result.get("status") == "completed"
                )
            if (
                row["tool_contracts"].get("prepare_learning_program_composition") == 1
                and task["context_manifest"].get("learning_program_composition_contract") == 1
            ):
                listed.update(
                    result["candidate"]["id"]
                    for result in Runs(connection).tool_outputs(
                        row["id"], "prepare_learning_program_composition"
                    ) if result.get("status") == "completed"
                )
            if (
                row["tool_contracts"].get("prepare_learning_assisted_composition") == 1
                and task["context_manifest"].get("learning_direct_answer_contract") == 1
            ):
                listed.update(
                    result["candidate"]["id"]
                    for result in Runs(connection).tool_outputs(
                        row["id"], "prepare_learning_assisted_composition",
                    ) if result.get("status") == "completed"
                )
            if (
                row["tool_contracts"].get("prepare_learning_hint_composition") == 1
                and task["context_manifest"].get("learning_hint_contract") == 1
            ):
                listed.update(
                    result["candidate"]["id"]
                    for result in Runs(connection).tool_outputs(
                        row["id"], "prepare_learning_hint_composition",
                    ) if result.get("status") == "completed"
                )
            if str(selection.exact_handle) not in listed:
                if (
                    row["tool_contracts"].get("prepare_learning_demo_composition") == 1
                    and task["context_manifest"].get("learning_demo_contract") == 1
                ):
                    listed.update(
                        result["candidate"]["id"]
                        for result in Runs(connection).tool_outputs(
                            row["id"], "prepare_learning_demo_composition",
                        ) if result.get("status") == "completed"
                    )
            if str(selection.exact_handle) not in listed:
                raise ModelProtocolError("learning_candidate_not_listed")
        candidate = LearningArtifacts(connection).candidate(
            actor, row["scope_id"], selection.exact_handle
        )
        # Candidate authority is node-scoped; the Turn's exact lesson remains
        # independently frozen and revalidated by the delivery context.
        expected_focus = (
            task["focus"] if candidate["kind"] == "learning_composition"
            else {**task["focus"], "lesson_id": None}
        )
        if candidate["focus"] != expected_focus:
            raise BusinessError("stale_version", "Candidate needs its exact teaching focus.")
        prepared, _, _ = LearningArtifactWorkflow.current(
            connection, actor, row["scope_id"], candidate, prepared_run_id=row["id"]
        )
        if candidate["kind"] == "learning_composition" and any(
            hint["text"].strip() in reply.text
            for binding in prepared["hint_bindings"] for hint in binding["hints"]
        ):
            raise ModelProtocolError("locked_hint_in_reply")
        if LearningArtifacts(connection).delivered(actor, candidate["id"]):
            raise BusinessError("stale_version", "Candidate was already delivered.")
        return reply

    @staticmethod
    def accept_reply_in(connection, actor, row, task, content):
        if not task or task["context_manifest"].get("learning_interaction_contract") != 1:
            LearningArtifactWorkflow.publish_in(
                connection, actor, row["scope_id"], row["input_ref"]
            )
            return content.strip()
        reply = LearningArtifactWorkflow.validate_reply_in(connection, actor, row, task, content)
        artifacts = LearningArtifacts(connection)
        existing = artifacts.for_turn(actor, row["scope_id"], row["input_ref"])
        selection = reply.interaction if reply else (
            ArtifactInteraction(
                type="artifact", exact_handle=existing["id"], intent="introduce_only"
            ) if existing else NoInteraction()
        )
        if selection.type == "artifact":
            chosen = artifacts.candidate(actor, row["scope_id"], selection.exact_handle)
            if chosen["kind"] == "learning_composition":
                from leornian.modules.tutor.compositions import Compositions

                Compositions(connection).accept(actor, chosen, row["id"])
            if not existing:
                artifacts.choose(
                    actor, row["scope_id"], row["input_ref"], selection.exact_handle,
                    task["context_manifest"]["teaching_revision"],
                )
            LearningArtifactWorkflow.publish_in(
                connection, actor, row["scope_id"], row["input_ref"]
            )
        else:
            artifacts.advance(
                actor, row["scope_id"], task["context_manifest"]["teaching_revision"]
            )
        PgTutorStore(connection).bind_interaction(
            row["input_ref"], selection,
            reply.pacing if isinstance(reply, PacedLearningReply) else None,
        )
        return reply.text if reply else content.strip()

    @staticmethod
    def publish_in(connection, actor, conversation_id, turn_id):
        artifacts = LearningArtifacts(connection)
        candidate = artifacts.for_turn(actor, conversation_id, turn_id)
        if candidate is None:
            return None
        _pack, _public, item = LearningArtifactWorkflow.current(
            connection, actor, conversation_id, candidate
        )
        row = artifacts.publish(actor, conversation_id, turn_id, candidate)
        if item is not None:
            Exposures(connection).record(actor, candidate["pack_id"], item)
        if candidate["kind"] == "learning_composition":
            from leornian.bootstrap.compositions import CompositionWorkflow

            CompositionWorkflow.publish_owners(connection, actor, row)
        LearningArtifactWorkflow.event(connection, actor, row["id"], conversation_id)
        return row

    @staticmethod
    def owner_result(
        connection, actor, pack_id, slot, kind, result_id, state, *, new_attempt=False,
    ):
        from leornian.modules.tutor.compositions import Compositions

        rows = (
            LearningArtifacts(connection).owner_result(
                actor, pack_id, slot, kind, result_id, state
            ) if kind in {"choice", "python"} else []
        ) + Compositions(connection).owner_result(
            actor, pack_id, slot, kind, result_id, state, new_attempt=new_attempt
        )
        for row in rows:
            LearningArtifactWorkflow.event(connection, actor, row["id"], row["conversation_id"])
            if state == "completed":
                from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow

                TeachingContinuationWorkflow.capture_in(
                    connection, actor, row["conversation_id"], row["id"],
                    "artifact_action" if kind in {"choice", "response"} else "expected_result",
                    f"{kind}:{result_id}",
                )

    @staticmethod
    def practice_only(connection, actor, artifact, components=None):
        if artifact["state"] in {"cancelled", "superseded"}:
            return False
        if LearningArtifacts(connection).node_ended(artifact):
            return True
        if artifact["state"] != "completed":
            return False
        if artifact["kind"] == "learning_composition":
            from leornian.bootstrap.compositions import CompositionWorkflow

            if components is None:
                components = CompositionWorkflow.component_views(connection, actor, artifact)
            return not any(
                getattr(binding.result, "status", None) in {"not_passed", "error"}
                for binding in components
            )
        return True

    def view_in(
        self, connection, actor, conversation_id, artifact_id, *,
        allow_compositions=False, response_capability=None, code_review_capability=None,
        program_capability=None, direct_answer_capability=None, hint_capability=None,
        demo_capability=None, example_capability=None,
    ):
        row = LearningArtifacts(connection).row(actor, conversation_id, artifact_id)
        if row["kind"] == "learning_composition":
            if not allow_compositions:
                raise UnsupportedPresentation("Use the v2 presentation endpoint.")
            from leornian.bootstrap.compositions import CompositionWorkflow
            from leornian.modules.tutor.composition_delivery_contracts import (
                CompositionArtifactView,
            )
            from leornian.modules.tutor.compositions import Compositions
            from leornian.modules.tutor.demos import DemoReports
            from leornian.modules.tutor.reviews import ReviewReports

            presentation = Compositions(connection).get(actor, row["presentation_id"])
            if presentation["demo_bindings"] and demo_capability != "learning_demo_events.v1":
                raise UnsupportedPresentation("This composition requires learning_demo_events.v1.")
            if presentation["review_bindings"]:
                required_review = "learning_code_review.v2" if any(
                    binding["profile_version"] == "submitted-code-review.v2"
                    for binding in presentation["review_bindings"]
                ) else "learning_code_review.v1"
                if code_review_capability not in {required_review, "learning_code_review.v2"}:
                    raise UnsupportedPresentation(
                        f"This composition requires {required_review} reader support.",
                    )
            if response_capability != "learning_responses.v1" and any(
                binding["source"]["kind"] == "knowledge_response"
                for binding in presentation["owner_bindings"]
            ):
                raise UnsupportedPresentation(
                    "This composition requires learning_responses.v1 reader support.",
                )
            if direct_answer_capability != "learning_direct_answers.v1" and any(
                binding.get("assistance_profile")
                for binding in presentation["owner_bindings"]
            ):
                raise UnsupportedPresentation(
                    "This composition requires learning_direct_answers.v1 reader support.",
                )
            if hint_capability != "learning_hints.v1" and any(
                binding.get("hint_profile") for binding in presentation["owner_bindings"]
            ):
                raise UnsupportedPresentation(
                    "This composition requires learning_hints.v1 reader support.",
                )
            if program_capability not in {"learning_programs.v1", "learning_programs.v2"} and any(
                binding["source"]["kind"] in {"sql_workspace", "project_workspace"}
                for binding in presentation["owner_bindings"]
            ):
                raise UnsupportedPresentation(
                    "This composition requires learning_programs.v1 reader support.",
                )
            if program_capability != "learning_programs.v2" and any(
                binding["source"]["kind"] == "project_workspace"
                and binding["source"]["presentation"]["task"]["language"] == "http_project"
                for binding in presentation["owner_bindings"]
            ):
                raise UnsupportedPresentation(
                    "This HTTP project requires learning_programs.v2 reader support.",
                )
            self.current(connection, actor, conversation_id, row)
            option = Compositions(connection).option(actor, row)
            components = CompositionWorkflow.component_views(connection, actor, row)
            review_reports = ReviewReports(connection).views(row, presentation["review_bindings"])
            demos = DemoReports(connection).views(row, presentation["demo_bindings"])
            practice_only = self.practice_only(connection, actor, row, components)
            if practice_only:
                components = [
                    item.model_copy(update={"allowed_actions": [], "next_hint_level": None})
                    for item in components
                ]
                demos = [item.model_copy(update={"allowed_actions": []}) for item in demos]
                review_reports = [item.model_copy(update={"allowed_actions": []})
                                  for item in review_reports]
            example_runners = {}
            if example_capability and (row["state"] == "ready" or practice_only):
                from leornian.bootstrap.example_runs import ExampleRuns

                example_runners = ExampleRuns.controls_in(
                    connection, actor, row["focus"], presentation,
                    workspace=option.presentation.example_workspace,
                )
            return CompositionArtifactView(
                **{k: row[k] for k in CompositionArtifactView.model_fields if k in row},
                title=option.title, content_ref=option.content_ref,
                presentation=option.presentation, component_bindings=components,
                review_bindings=option.review_bindings,
                demo_bindings=demos, practice_only=practice_only,
                review_reports=review_reports, example_runners=example_runners,
                example_run_surface=(
                    example_surface(example_capability) if example_runners else None
                ),
                allowed_actions=[],
            )
        pack = Packs(connection).row(actor, row["pack_id"])
        public = next(
            i.public()
            for i in Packs(connection).published_document(actor, pack["id"]).items
            if i.slot == row["slot"]
        )
        actions = []
        practice_only = self.practice_only(connection, actor, row)
        if practice_only:
            self.current(connection, actor, conversation_id, row, require_unanswered=False)
        elif row["state"] == "ready":
            try:
                self.current(connection, actor, conversation_id, row)
                actions = ["run" if row["kind"] == "code_workspace" else "respond"]
            except BusinessError:
                pass
        result = (
            Choices(connection).get(actor, row["choice_result_id"])
            if row["choice_result_id"]
            else PythonAssessment(connection).public(
                PythonAssessment(connection).row(actor, row["python_attempt_id"])
            )
            if row["python_attempt_id"]
            else None
        )
        return LearningArtifactView(
            **{k: row[k] for k in LearningArtifactView.model_fields if k in row and k != "focus"},
            title=public.title if hasattr(public, "title") else public.prompt,
            focus=TeachingFocus(**row["focus"]),
            content_ref=LearningContentRef(
                id=row["pack_id"],
                revision=pack["revision"],
                slot=row["slot"],
                public_identity=row["public_identity"],
            ),
            presentation={
                "type": row["kind"],
                "task" if row["kind"] == "code_workspace" else "question": public,
            },
            allowed_actions=actions, practice_only=practice_only,
            result=result,
            commentary_status="pending_or_available" if result else "not_requested",
        )

    def get(self, token, conversation_id, artifact_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return self.view_in(connection, actor, conversation_id, artifact_id)

    def get_v2(
        self, token, conversation_id, artifact_id, *,
        response_capability=None, code_review_capability=None, program_capability=None,
        direct_answer_capability=None, hint_capability=None,
        demo_capability=None, example_capability=None,
    ):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return self.view_in(
                connection, actor, conversation_id, artifact_id, allow_compositions=True,
                response_capability=response_capability,
                code_review_capability=code_review_capability,
                program_capability=program_capability,
                direct_answer_capability=direct_answer_capability,
                hint_capability=hint_capability,
                demo_capability=demo_capability, example_capability=example_capability,
            )

    def composition_source(self, token, conversation_id, artifact_id, component_id):
        from leornian.bootstrap.compositions import CompositionWorkflow

        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = LearningArtifacts(connection).row(actor, conversation_id, artifact_id)
            if row["kind"] != "learning_composition":
                raise BusinessError("not_found", "No composition source.")
            return CompositionWorkflow.source_in(
                connection, actor, conversation_id, row, component_id
            )

    def demo_history(self, token, conversation_id, artifact_id, component_id, before, limit):
        from leornian.modules.tutor.demos import DemoReports

        # Current-use permission checks retain the same share locks as artifact detail reads.
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = LearningArtifacts(connection).row(actor, conversation_id, artifact_id)
            if row["kind"] != "learning_composition":
                raise BusinessError("not_found", "No demonstration history.")
            self.current(connection, actor, conversation_id, row)
            return DemoReports(connection).history(artifact_id, component_id, before, limit)

    def action_receipt(self, token, conversation_id, artifact_id, action_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return LearningArtifacts(connection).action_receipt(
                actor, conversation_id, artifact_id, action_id
            )

    def list(self, token, conversation_id, before=None, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return LearningArtifacts(connection).list(
                actor, conversation_id, before=before, limit=limit
            )

    def list_v2(self, token, conversation_id, before=None, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Tutor(PgTutorStore(connection)).get(actor, conversation_id)
            return LearningArtifacts(connection).list(
                actor, conversation_id, before=before, limit=limit, include_compositions=True
            )

    def action(self, token, conversation_id, artifact_id, data):
        from leornian.bootstrap.python_execution import PythonWorkflow

        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            tutor = Tutor(PgTutorStore(connection))
            tutor.get(actor, conversation_id)
            artifacts = LearningArtifacts(connection)
            artifacts.row(actor, conversation_id, artifact_id)
            previous = artifacts.replay(actor, artifact_id, data)
            if previous:
                return previous
            from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow

            TeachingContinuationWorkflow.preempt_in(connection, actor, conversation_id)
            tutor.get(actor, conversation_id, lock=True)
            row = artifacts.row(actor, conversation_id, artifact_id, lock=True)
            if row["revision"] != data.expected_artifact_revision:
                raise BusinessError("stale_version", "Learning artifact changed.")
            if self.practice_only(connection, actor, row):
                raise BusinessError("precondition_failed", "已进入自由练习，不再提交学习记录。")
            if data.action == "complete_review":
                from leornian.bootstrap.review_completion import ReviewCompletionWorkflow

                return ReviewCompletionWorkflow.action_in(connection, actor, row, data)
            if data.action in {"start_demo", "acknowledge_demo_event", "complete_demo"}:
                from leornian.bootstrap.demo_interactions import DemoInteractions

                return DemoInteractions.action_in(connection, actor, row, data)
            if data.action in {
                "run_component", "respond_component", "cancel_component_run", "answer_component",
                "run_program_component",
                "request_direct_answer", "request_hint",
            }:
                if row["kind"] != "learning_composition":
                    raise BusinessError("precondition_failed", "A composition owner is required.")
                from leornian.bootstrap.compositions import CompositionWorkflow

                return CompositionWorkflow.action_in(
                    connection, actor, row, data, Identity.digest(token)
                )
            if row["state"] != "ready" and not (
                row["kind"] == "learning_composition" and data.action == "cancel"
                and row["state"] in {"running", "completed"}
            ):
                raise BusinessError("precondition_failed", "This interaction is no longer ready.")
            if data.action != "cancel" or row["kind"] != "learning_composition":
                self.current(connection, actor, conversation_id, row)
            if data.action == "cancel":
                connection.execute(
                    "UPDATE tutor.learning_artifacts SET state='cancelled',revision=revision+1 "
                    "WHERE id=%s",
                    (artifact_id,),
                )
                if row["kind"] == "learning_composition":
                    from leornian.bootstrap.compositions import CompositionWorkflow

                    CompositionWorkflow.cancel_in(connection, actor, row, Identity.digest(token))
                self.event(connection, actor, artifact_id, conversation_id)
            elif data.action == "respond" and row["kind"] == "knowledge_check":
                ItemSupply.answer_in(
                    connection,
                    actor,
                    row["pack_id"],
                    str(data.client_action_id),
                    ChoiceInput(slot=row["slot"], selected_key=data.payload.selected_key),
                )
            elif data.action == "run" and row["kind"] == "code_workspace":
                PythonWorkflow.submit_training_in(
                    connection,
                    actor,
                    Identity.digest(token),
                    row["pack_id"],
                    str(data.client_action_id),
                    PythonTraining(slot=row["slot"], code=data.payload.code),
                )
            else:
                raise BusinessError("precondition_failed", "Action does not match this artifact.")
            return artifacts.remember(
                actor, artifacts.row(actor, conversation_id, artifact_id), data
            )
