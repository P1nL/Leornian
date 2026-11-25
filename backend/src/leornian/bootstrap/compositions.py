"""Named preparation coordinator inside the existing checked Tutor delivery."""

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_consumers import manifest_citations, read_citations_in
from leornian.bootstrap.teaching_context import TeachingContext
from leornian.modules.assessment.assistance import PracticeAssistance
from leornian.modules.assessment.choices import Choices
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.program_contracts import ProgramPracticeSubmission
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.assessment.python_contracts import PythonPracticeSubmission
from leornian.modules.assessment.responses import Responses
from leornian.modules.item_bank.contracts import ResponseSubmission
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import ChoiceInput
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.knowledge.materials import Materials
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionComponentView,
    CompositionHintBinding,
    CompositionOwnerBinding,
    CompositionSourceView,
    PreparedComposition,
    PreparedHintComposition,
    SubmittedCodeReviewBinding,
)
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2
from leornian.modules.tutor.compositions import Compositions
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.demos import demo_bindings
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.learning_artifact_contracts import LearningCandidateOption
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.shared_kernel.errors import BusinessError

BINDING_FIELDS = ("plan_binding", "sources", "material_bindings", "lesson_ids", "receipt_ids")
# Enabling more components requires the actual renderer and owner path, not just a schema.
LOCAL_COMPONENTS = {
    "Explanation", "SourceReference", "AlgorithmPlayer", "AlgorithmGraph", "AlgorithmContainer",
    "DataTable", "KeyValueList", "CodeBlock", "CodeEditor", "CodeDiff",
    "IsolatedPreview", "TreeView", "RelationGraph", "SequenceDiagram",
    "AlgorithmSequence", "AlgorithmGrid", "AlgorithmRecursion", "AlgorithmIntervals",
    "AlgorithmBits", "AlgorithmGeometry", "ParameterControl", "StepPlayer",
    "ArtifactAction", "ActionGroup",
}


class CompositionWorkflow:
    @staticmethod
    def binding(manifest):
        return {key: manifest.get(key) for key in BINDING_FIELDS}

    @staticmethod
    def prepare_in(
        connection, actor, row, args, *, practice=False, responses=False, code_review=False,
        programs=False, assisted=False, hints=False, demos=False, review_reports=False,
        template=False,
    ):
        tool = (
            "prepare_learning_template" if template else
            "prepare_learning_demo_composition" if demos else
            "prepare_learning_hint_composition" if hints else
            "prepare_learning_assisted_composition" if assisted else
            "prepare_learning_program_composition" if programs else
            "prepare_learning_code_review_composition_v2" if review_reports else
            "prepare_learning_code_review_composition" if code_review else
            "prepare_learning_response_composition" if responses else
            "prepare_learning_practice_composition" if practice else "prepare_learning_composition"
        )
        if row["tool_contracts"].get(tool) != 1:
            raise BusinessError("precondition_failed", "Run has no composition capability.")
        programs = programs or assisted or hints or demos
        if demos:
            practice = bool(args.owner_bindings)
        task = Deliveries(connection).for_run(row["id"])
        if not task or task["kind"] != "teaching":
            raise BusinessError(
                "precondition_failed", "Only checked teaching prepares compositions."
            )
        direct_enabled = assisted or (
            (hints or demos)
            and row["tool_contracts"].get("prepare_learning_assisted_composition") == 1
            and task["context_manifest"].get("learning_direct_answer_contract") == 1
        )
        hint_bindings = args.hint_bindings if hints or demos else []
        if demos and hint_bindings and (
            row["tool_contracts"].get("prepare_learning_hint_composition") != 1
            or task["context_manifest"].get("learning_hint_contract") != 1
        ):
            raise BusinessError("precondition_failed", "Hints require their frozen capability.")
        demonstration_bindings = demo_bindings(
            args.definition, args.demo_components
        ) if demos else []
        if demos and task["context_manifest"].get("learning_demo_contract") != 1:
            raise BusinessError("precondition_failed", "Run has no demonstration contract.")
        hint_components = {binding.component_id for binding in hint_bindings}
        definition, example_workspace = args.expand() if template else (args.definition, None)
        CompositionWorkflow.validate_file_scope(
            definition, programs=programs and (not demos or practice),
        )
        response_components = responses or programs and row["tool_contracts"].get(
            "prepare_learning_response_composition"
        ) == 1
        components = LOCAL_COMPONENTS | (
            {"ChoiceAnswer", "AnswerFeedback", "ResultFeedback"} if practice else set()
        ) | ({"TextAnswer", "OrderingAnswer", "LineRangeAnswer", "ReviewFinding"}
             if response_components else set()) | ({"ReviewFinding"} if code_review else set())
        if template:
            components |= {"ChoiceAnswer", "TextAnswer", "OrderingAnswer", "LineRangeAnswer"}
        unsupported = {n.component for n in definition.components} - components
        business_events = [
            n.props.event for n in definition.components
            if n.component == "ArtifactAction" and n.props.event not in (
                {"preview", "submit_answer", "check_code"}
                | ({"submit_review"} if response_components else set())
                if practice else {"preview"}
            )
        ]
        if unsupported or business_events:
            raise BusinessError(
                "precondition_failed",
                "These owner/renderer paths are not enabled yet: "
                + ", ".join(sorted(unsupported | set(business_events))),
            )
        conversation = Tutor(PgTutorStore(connection)).get(actor, row["scope_id"])
        Gates(connection).require_no_exam(actor)
        _context, manifest = TeachingContext.build(
            connection, actor, conversation, TeachingFocus(**task["focus"])
        )
        frozen = CompositionWorkflow.binding(task["context_manifest"])
        if CompositionWorkflow.binding(manifest) != frozen:
            raise BusinessError("stale_version", "Composition teaching binding changed.")
        allowed_materials = {
            c.model_dump_json() for c in manifest_citations(manifest, "teaching")
        }
        allowed_legacy = {
            (ref["source_id"], ref["revision"]) for ref in manifest.get("sources", [])
        }
        for node in definition.components:
            if node.component != "SourceReference":
                continue
            citation = node.props.citation
            allowed = (
                citation.model_dump_json() in allowed_materials
                if hasattr(citation, "binding_id")
                else (str(citation.source_id), citation.revision) in allowed_legacy
            )
            if not allowed:
                raise BusinessError("source_not_current", "Composition cites unsupplied material.")
        reviews = []
        if code_review:
            from leornian.bootstrap.code_reviews import SubmittedCodeReviews

            if task["context_manifest"].get("learning_code_review_contract") != (
                2 if review_reports else 1
            ):
                raise BusinessError("precondition_failed", "Run has no submitted-review contract.")
            definition, review = SubmittedCodeReviews.prepare_in(
                connection, actor, TeachingFocus(**task["focus"]), definition, args,
                review_reports=review_reports,
            )
            reviews.append(review)
        owners = []
        if practice:
            manifest_key = (
                "learning_demo_contract" if demos else
                "learning_hint_contract" if hints else
                "learning_direct_answer_contract" if assisted else
                "learning_program_composition_contract" if programs else
                "learning_response_composition_contract" if responses
                else "learning_practice_composition_contract"
            )
            if task["context_manifest"].get(manifest_key) != 1:
                raise BusinessError("precondition_failed", "Run has no practice action contract.")
            listed = {
                item["id"]
                for name in (
                    (
                        "list_learning_artifact_candidates", "list_learning_response_candidates",
                        "list_learning_program_candidates",
                    ) if programs else
                    ("list_learning_artifact_candidates", "list_learning_response_candidates")
                    if responses else ("list_learning_artifact_candidates",)
                )
                for result in Runs(connection).tool_outputs(row["id"], name)
                if row["tool_contracts"].get(name) == 1 and result.get("status") == "completed"
                for item in result["items"]
            }
            from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

            for proposal in args.owner_bindings:
                if str(proposal.candidate_id) not in listed:
                    raise BusinessError("precondition_failed", "Practice candidate was not listed.")
                candidate = LearningArtifacts(connection).candidate(
                    actor, conversation.id, proposal.candidate_id
                )
                is_program = candidate["kind"] in {"sql_workspace", "project_workspace"}
                if is_program and not programs:
                    raise BusinessError("precondition_failed", "Program capability is required.")
                if programs:
                    required = (
                        "prepare_learning_program_composition" if is_program else
                        "prepare_learning_response_composition"
                        if candidate["kind"] == "knowledge_response"
                        else "prepare_learning_practice_composition"
                    )
                    if row["tool_contracts"].get(required) != 1:
                        raise BusinessError(
                            "precondition_failed", "Every mixed owner needs its own capability.",
                        )
                _, public, _ = LearningArtifactWorkflow.current(
                    connection, actor, conversation.id, candidate, allow_programs=is_program,
                )
                option = LearningArtifactWorkflow.candidate_in(
                    connection, actor, conversation.id, candidate["pack_id"], candidate["slot"],
                    programs=is_program,
                )
                if responses and option.kind != "knowledge_response" and row["tool_contracts"].get(
                    "prepare_learning_practice_composition"
                ) != 1:
                    raise BusinessError(
                        "precondition_failed", "Original practice needs its separate capability."
                    )
                source = option if option.kind in {
                    "knowledge_response", "sql_workspace", "project_workspace"
                } else LearningCandidateOption(
                    **option.model_dump(),
                    presentation={
                        "type": option.kind,
                        "task" if option.kind == "code_workspace" else "question": public,
                    },
                )
                owners.append(CompositionOwnerBinding(
                    component_id=proposal.component_id, source=source,
                    assistance_profile="practice-direct-answer.v1" if direct_enabled else None,
                    hint_profile=(
                        "practice-hints.v1" if proposal.component_id in hint_components else None
                    ),
                ))
            has_program = any(
                owner.source.kind in {"sql_workspace", "project_workspace"} for owner in owners
            )
            if programs and not assisted and not hints and not demos and not has_program:
                raise BusinessError(
                    "precondition_failed", "Program preparation requires an actual program owner.",
                )
            if (assisted or hints or demos) and not has_program:
                CompositionWorkflow.validate_file_scope(definition, programs=False)
            CompositionWorkflow.validate_owners(
                connection, actor, conversation.id, definition, owners, task["focus"]
            )
        CompositionWorkflow.validate_hints(definition, owners, hint_bindings)
        candidate = Compositions(connection).prepare(
            actor, conversation.id, row["id"], TeachingFocus(**task["focus"]),
            args.command_key, definition, frozen, owners, reviews, hint_bindings,
            demonstration_bindings, example_workspace=example_workspace,
        )
        receipt = (
            PreparedHintComposition(candidate=candidate, hint_bindings=hint_bindings)
            if hints or demos else PreparedComposition(candidate=candidate)
        ).model_dump(mode="json")
        if task["context_manifest"].get("node_turn_contract") == 1:
            from leornian.bootstrap.example_runs import ExampleRuns

            surface = receipt["candidate"]
            receipt["example_runners"] = ExampleRuns.controls_in(
                connection, actor, task["focus"], {
                    **surface["presentation"], "owner_bindings": surface.get("owner_bindings", []),
                    "review_bindings": surface.get("review_bindings", []),
                }, workspace=example_workspace,
            ) if task["context_manifest"].get("example_runs") else {}
        return receipt

    @staticmethod
    def validate_hints(definition, owners, bindings):
        expected = {owner.component_id for owner in owners if owner.hint_profile}
        if len({binding.component_id for binding in bindings}) != len(bindings) or {
            binding.component_id for binding in bindings
        } != expected:
            raise BusinessError("precondition_failed", "Hints need their exact original owners.")

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)

        visible = tuple(strings(definition.model_dump(mode="json")))
        if any(
            hint.text.strip() in text for binding in bindings for hint in binding.hints
            for text in visible
        ):
            raise BusinessError(
                "precondition_failed", "Locked hints cannot appear in the public presentation."
            )

    @staticmethod
    def validate_file_scope(definition, *, programs):
        if not programs and any(
            len(file.content) > 20000 for state in definition.states.values()
            if state.type == "files" for file in state.files
        ):
            raise BusinessError(
                "precondition_failed", "Legacy file displays keep their 20,000-character limit.",
            )

    @staticmethod
    def validate_owners(
        connection, actor, conversation_id, definition, owners, focus, *, published=False,
    ):
        from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

        nodes = {node.id: node for node in definition.components}
        bindings = {binding.component_id: binding for binding in owners}
        if len(bindings) != len(owners) or len({b.source.id for b in owners}) != len(owners):
            raise BusinessError("precondition_failed", "Practice bindings must be distinct.")
        states = set()
        for binding in owners:
            node = nodes.get(binding.component_id)
            source = binding.source
            if source.focus.model_dump(mode="json") != {**focus, "lesson_id": None}:
                raise BusinessError("stale_version", "Practice binding needs the exact node.")
            candidate = LearningArtifacts(connection).candidate(actor, conversation_id, source.id)
            _, public, _ = LearningArtifactWorkflow.current(
                connection, actor, conversation_id, candidate, require_unanswered=not published,
                allow_programs=source.kind in {"sql_workspace", "project_workspace"},
            )
            if not published and LearningArtifacts(connection).delivered(actor, source.id):
                raise BusinessError("precondition_failed", "Practice candidate already delivered.")
            if source.content_ref.public_identity != LearningArtifactWorkflow.identity(public):
                raise BusinessError("stale_version", "Published practice content changed.")
            if (
                source.kind == "knowledge_check" and node and node.component == "ChoiceAnswer"
                and not node.props.multiple
                and [(item.id, item.text) for item in node.props.options]
                == [(item.key, item.text) for item in public.options]
            ):
                pass
            elif source.kind == "knowledge_response" and node:
                CompositionWorkflow.validate_response_node(definition, node, public)
            elif (
                source.kind == "code_workspace" and node
                and node.component in {"CodeEditor", "CodeDiff"}
                and definition.states[node.props.state].type == "code"
                and not definition.states[node.props.state].read_only
                and definition.states[node.props.state].value == public.starter_code
                and (node.component != "CodeDiff" or node.props.before == public.starter_code)
            ):
                pass
            elif source.kind in {"sql_workspace", "project_workspace"} and node:
                CompositionWorkflow.validate_program_node(definition, node, public)
            else:
                raise BusinessError(
                    "precondition_failed", "Component differs from published practice."
                )
            if node.props.state in states:
                raise BusinessError(
                    "precondition_failed", "Distinct practice cannot share a response."
                )
            states.add(node.props.state)
        for node in definition.components:
            if node.component in {
                "ChoiceAnswer", "TextAnswer", "OrderingAnswer", "LineRangeAnswer"
            } and node.id not in bindings:
                raise BusinessError("precondition_failed", "Response has no original owner.")
            if node.component in {"AnswerFeedback", "ResultFeedback", "ReviewFinding"} or (
                node.component == "ArtifactAction"
                and node.props.event in {"submit_answer", "submit_review", "check_code"}
            ):
                binding = bindings.get(node.props.for_component)
                target = nodes.get(node.props.for_component)
                allowed = (
                    {"knowledge_check", "knowledge_response"} if node.component == "AnswerFeedback"
                    or node.component == "ArtifactAction" and node.props.event == "submit_answer"
                    else {"knowledge_response"} if node.component == "ReviewFinding"
                    or node.component == "ArtifactAction" and node.props.event == "submit_review"
                    else {"code_workspace", "sql_workspace", "project_workspace"}
                )
                if binding is None or binding.source.kind not in allowed or (
                    node.component == "ReviewFinding" and target.component != "LineRangeAnswer"
                ):
                    raise BusinessError(
                        "precondition_failed", "Action/feedback lacks its exact owner."
                    )

    @staticmethod
    def validate_program_node(definition, node, public):
        state = definition.states.get(node.props.state) if hasattr(node.props, "state") else None
        if public.language == "sql_query":
            valid = (
                node.component in {"CodeEditor", "CodeDiff"} and state and state.type == "code"
                and not state.read_only and state.value == public.starter_query
                and (node.component != "CodeDiff" or node.props.before == public.starter_query)
            )
        else:
            valid = (
                node.component == "CodeEditor" and state and state.type == "files"
                and [file.model_dump() for file in state.files]
                == [file.model_dump() for file in public.files]
            )
        if not valid:
            raise BusinessError(
                "precondition_failed", "Program editor differs from the fixed public task.",
            )

    @staticmethod
    def validate_response_node(definition, node, public):
        matches = False
        if public.response_type == "multiple" and node.component == "ChoiceAnswer":
            matches = node.props.multiple and [
                (o.id, o.text) for o in node.props.options
            ] == [(o.id, o.text) for o in public.options]
        elif public.response_type in {"prediction", "short"}:
            matches = node.component == "TextAnswer"
        elif public.response_type == "ordering" and node.component == "OrderingAnswer":
            matches = [
                (o.id, o.text) for o in node.props.items
            ] == [(o.id, o.text) for o in public.items] and (
                definition.states[node.props.state].value == [o.id for o in public.items]
            )
        elif public.response_type == "line_review" and node.component == "LineRangeAnswer":
            code = definition.states[node.props.code_state]
            matches = code.read_only and code.value == public.code
        if not matches:
            raise BusinessError(
                "precondition_failed", "Response component differs from published content."
            )

    @staticmethod
    def current(connection, actor, conversation_id, candidate, *, prepared_run_id=None):
        store = Compositions(connection)
        presentation = store.get(actor, candidate["presentation_id"])
        if presentation["conversation_id"] != conversation_id:
            raise BusinessError("not_found", "Composition is outside this conversation.")
        if presentation["quality_call_id"] is None and (
            prepared_run_id is None or presentation["prepared_run_id"] != prepared_run_id
        ):
            raise BusinessError("precondition_failed", "Composition is not approved for delivery.")
        conversation = Tutor(PgTutorStore(connection)).get(actor, conversation_id)
        Gates(connection).require_no_exam(actor)
        _, manifest, _ = TeachingContext.bound_context(
            connection, actor, conversation, TeachingFocus(**candidate["focus"])
        )
        saved_binding = {key: value for key, value in presentation["context_manifest"].items()
                         if key != "example_workspace"}
        if CompositionWorkflow.binding(manifest) != saved_binding:
            raise BusinessError("stale_version", "Composition content binding changed.")
        definition = LearningCompositionV2.model_validate(presentation["definition"])
        expected_demos = [
            binding.model_dump(mode="json") for binding in demo_bindings(
                definition, [binding["component_id"] for binding in presentation["demo_bindings"]]
            )
        ]
        if expected_demos != presentation["demo_bindings"]:
            raise BusinessError("stale_version", "Demonstration binding changed.")
        owners = [CompositionOwnerBinding.model_validate(b) for b in presentation["owner_bindings"]]
        CompositionWorkflow.validate_hints(definition, owners, [
            CompositionHintBinding.model_validate(binding)
            for binding in presentation["hint_bindings"]
        ])
        if owners:
            CompositionWorkflow.validate_owners(
                connection, actor, conversation_id, definition, owners, candidate["focus"],
                published=store.delivered_artifact(actor, presentation["id"]) is not None,
            )
        if presentation["review_bindings"]:
            from leornian.bootstrap.code_reviews import SubmittedCodeReviews

            SubmittedCodeReviews.current_in(
                connection, actor, TeachingFocus(**candidate["focus"]), definition,
                [
                    SubmittedCodeReviewBinding.model_validate(b)
                    for b in presentation["review_bindings"]
                ],
            )
        return presentation, definition, None

    @staticmethod
    def publish_owners(connection, actor, artifact):
        from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

        store = Compositions(connection)
        store.assign_owners(actor, artifact)
        for component in store.components(actor, artifact["id"]):
            candidate = LearningArtifacts(connection).candidate(
                actor, artifact["conversation_id"], component["source_candidate_id"]
            )
            _, _, item = LearningArtifactWorkflow.current(
                connection, actor, artifact["conversation_id"], candidate,
                allow_programs=candidate["kind"] in {"sql_workspace", "project_workspace"},
            )
            Exposures(connection).record(actor, candidate["pack_id"], item)
        presentation = store.get(actor, artifact["presentation_id"])
        if presentation["review_bindings"]:
            from leornian.bootstrap.code_reviews import SubmittedCodeReviews

            for binding in presentation["review_bindings"]:
                SubmittedCodeReviews.publish_in(
                    connection, actor, presentation["id"],
                    SubmittedCodeReviewBinding.model_validate(binding),
                )

    @staticmethod
    def component_views(connection, actor, artifact):
        store = Compositions(connection)
        presentation = store.get(actor, artifact["presentation_id"])
        frozen = {
            binding["component_id"]: CompositionOwnerBinding.model_validate(binding)
            for binding in presentation["owner_bindings"]
        }
        rows = store.components(actor, artifact["id"])
        if len(frozen) != len(rows):
            raise BusinessError("precondition_failed", "Practice assignment is incomplete.")
        views = []
        for row in rows:
            result, history, actions = None, None, []
            available = artifact["state"] not in {"cancelled", "superseded"}
            if row["kind"] == "knowledge_check":
                if row["choice_result_id"]:
                    result = Choices(connection).get(actor, row["choice_result_id"])
                elif available:
                    actions = ["respond"]
            elif row["kind"] == "knowledge_response":
                if row["response_result_id"]:
                    result = Responses(connection).get(actor, row["response_result_id"])
                elif available:
                    actions = ["respond"]
            elif row["kind"] in {"sql_workspace", "project_workspace"}:
                assessment = ProgramAssessment(connection)
                history = assessment.history(actor, row["pack_id"], row["slot"])
                if row["program_attempt_id"]:
                    result = assessment.public(assessment.row(actor, row["program_attempt_id"]))
                if available:
                    actions = ["cancel_run"] if result and result.status == "queued" else ["run"]
                    if result and result.status == "error":
                        actions.append("retry")
            else:
                assessment = PythonAssessment(connection)
                history = assessment.practice_history(actor, row["pack_id"], row["slot"])
                if row["python_attempt_id"]:
                    result = assessment.practice_public(
                        assessment.row(actor, row["python_attempt_id"])
                    )
                if available:
                    actions = (
                        ["cancel_run"] if result.policy_version == "python-practice.v2" else []
                    ) if result and result.status == "queued" else ["run"]
                    if result and result.status == "error":
                        actions.append("retry")
            frozen_binding = frozen[row["component_id"]]
            assistance = None
            if frozen_binding.assistance_profile:
                assistance = PracticeAssistance(connection).get(
                    actor, row["pack_id"], row["slot"],
                )
                if available and row["state"] != "running" and assistance is None:
                    actions.append("request_direct_answer")
            hints, next_hint = [], None
            if frozen_binding.hint_profile:
                hints = PracticeAssistance(connection).hints(actor, row["pack_id"], row["slot"])
                identity = presentation["public_identity"]
                if any(receipt.hint_identity != identity for receipt in hints):
                    raise BusinessError(
                        "stale_version", "Continue the original checked hint series."
                    )
                if available and row["state"] != "running" and len(hints) < 3:
                    next_hint = len(hints) + 1
                    actions.append("request_hint")
            views.append(CompositionComponentView(
                **frozen[row["component_id"]].model_dump(),
                state=row["state"], action_id=row["last_action_id"], allowed_actions=actions,
                result=result, attempts=history, assistance_receipt=assistance,
                hint_receipts=hints, next_hint_level=next_hint,
            ))
        return views

    @staticmethod
    def action_in(connection, actor, artifact, data, session_digest):
        from leornian.bootstrap.item_supply import ItemSupply
        from leornian.bootstrap.program_execution import ProgramWorkflow
        from leornian.bootstrap.python_execution import PythonWorkflow

        if artifact["state"] in {"cancelled", "superseded"}:
            raise BusinessError("precondition_failed", "This interaction has ended.")
        store = Compositions(connection)
        row = next(
            (
                r for r in store.components(actor, artifact["id"])
                if r["component_id"] == data.component_id
            ),
            None,
        )
        if row is None:
            raise BusinessError("not_found", "No original owner at this component.")
        if data.action != "cancel_component_run":
            CompositionWorkflow.current(connection, actor, artifact["conversation_id"], artifact)
        assistance_id = None
        if data.action == "request_hint":
            presentation = store.get(actor, artifact["presentation_id"])
            binding = next(
                binding for binding in presentation["owner_bindings"]
                if binding["component_id"] == data.component_id
            )
            if binding.get("hint_profile") != "practice-hints.v1" or row["state"] == "running":
                raise BusinessError("precondition_failed", "This owner does not allow hints now.")
            series = next(
                CompositionHintBinding.model_validate(binding)
                for binding in presentation["hint_bindings"]
                if binding["component_id"] == data.component_id
            )
            from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

            candidate = LearningArtifacts(connection).candidate(
                actor, artifact["conversation_id"], row["source_candidate_id"],
            )
            _, _, item = LearningArtifactWorkflow.current(
                connection, actor, artifact["conversation_id"], candidate,
                require_unanswered=False,
                allow_programs=row["kind"] in {"sql_workspace", "project_workspace"},
            )
            reference = binding["source"]["content_ref"]
            receipt = PracticeAssistance(connection).record_hint(
                actor, row["pack_id"], reference["revision"], row["slot"],
                reference["public_identity"], presentation["public_identity"],
                series.hints[data.level - 1],
            )
            Exposures(connection).record(
                actor, row["pack_id"], item, receipt, receipt_ref=f"assistance:{receipt.id}",
            )
            store.assistance_delivered(artifact["id"])
            LearningArtifactWorkflow.event(
                connection, actor, artifact["id"], artifact["conversation_id"],
            )
            assistance_id = receipt.id
        elif data.action == "request_direct_answer":
            presentation = store.get(actor, artifact["presentation_id"])
            binding = next(
                binding for binding in presentation["owner_bindings"]
                if binding["component_id"] == data.component_id
            )
            if (
                binding.get("assistance_profile") != "practice-direct-answer.v1"
                or row["state"] == "running"
            ):
                raise BusinessError(
                    "precondition_failed", "This owner does not allow a direct answer now.",
                )
            item, content = Packs(connection).direct_answer(actor, row["pack_id"], row["slot"])
            reference = binding["source"]["content_ref"]
            receipt = PracticeAssistance(connection).record(
                actor, row["pack_id"], reference["revision"], row["slot"],
                reference["public_identity"], content,
            )
            Exposures(connection).record(
                actor, row["pack_id"], item, receipt, receipt_ref=f"assistance:{receipt.id}",
            )
            store.assistance_delivered(artifact["id"])
            from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

            LearningArtifactWorkflow.event(
                connection, actor, artifact["id"], artifact["conversation_id"],
            )
            assistance_id = receipt.id
        elif data.action == "respond_component" and row["kind"] == "knowledge_check":
            if row["state"] != "ready":
                raise BusinessError("precondition_failed", "This exact response is already locked.")
            ItemSupply.answer_in(
                connection, actor, row["pack_id"], str(data.client_action_id),
                ChoiceInput(slot=row["slot"], selected_key=data.payload.selected_key),
            )
        elif data.action == "answer_component" and row["kind"] == "knowledge_response":
            if row["state"] != "ready":
                raise BusinessError("precondition_failed", "This exact response is already locked.")
            ItemSupply.respond_in(
                connection, actor, row["pack_id"], str(data.client_action_id),
                ResponseSubmission(slot=row["slot"], response=data.payload),
            )
        elif data.action == "run_component" and row["kind"] == "code_workspace":
            if row["python_attempt_id"] != data.payload.previous_attempt_id:
                raise BusinessError("stale_version", "The bound previous attempt changed.")
            PythonWorkflow.submit_practice_in(
                connection, actor, session_digest, row["pack_id"], str(data.client_action_id),
                PythonPracticeSubmission(slot=row["slot"], **data.payload.model_dump()),
            )
        elif data.action == "run_program_component" and row["kind"] in {
            "sql_workspace", "project_workspace",
        }:
            if row["program_attempt_id"] != data.payload.previous_attempt_id:
                raise BusinessError("stale_version", "The bound previous program attempt changed.")
            ProgramWorkflow.submit_practice_in(
                connection, actor, session_digest, row["pack_id"], str(data.client_action_id),
                ProgramPracticeSubmission(slot=row["slot"], **data.payload.model_dump()),
            )
        elif data.action == "cancel_component_run" and row["kind"] == "code_workspace":
            if row["python_attempt_id"] != data.expected_attempt_id or row["state"] != "running":
                raise BusinessError("stale_version", "The exact running practice changed.")
            PythonWorkflow.cancel_practice_in(
                connection, actor, row["python_attempt_id"], session_digest
            )
        elif data.action == "cancel_component_run" and row["kind"] in {
            "sql_workspace", "project_workspace",
        }:
            if row["program_attempt_id"] != data.expected_attempt_id or row["state"] != "running":
                raise BusinessError("stale_version", "The exact running program changed.")
            ProgramWorkflow.cancel_in(connection, actor, row["program_attempt_id"], session_digest)
        else:
            raise BusinessError("precondition_failed", "Action does not match the bound owner.")
        store.action_identity(artifact["id"], row["component_id"], data.client_action_id)
        if assistance_id:
            return LearningArtifacts(connection).remember_component(
                actor, artifact, data, assistance_receipt_id=assistance_id,
            )
        return LearningArtifacts(connection).remember_component(actor, artifact, data)

    @staticmethod
    def cancel_in(connection, actor, artifact, session_digest):
        from leornian.bootstrap.program_execution import ProgramWorkflow
        from leornian.bootstrap.python_execution import PythonWorkflow

        store = Compositions(connection)
        components = store.components(actor, artifact["id"])
        store.cancel_components(artifact["id"])
        for component in components:
            if component["kind"] == "code_workspace" and component["state"] == "running":
                attempt = PythonAssessment(connection).row(actor, component["python_attempt_id"])
                if attempt["policy_version"] == "python-practice.v2":
                    PythonWorkflow.cancel_practice_in(
                        connection, actor, component["python_attempt_id"], session_digest
                    )
            elif component["kind"] in {"sql_workspace", "project_workspace"} and (
                component["state"] == "running"
            ):
                ProgramWorkflow.cancel_in(
                    connection, actor, component["program_attempt_id"], session_digest,
                )

    @staticmethod
    def source_in(connection, actor, conversation_id, candidate, component_id):
        _, definition, _ = CompositionWorkflow.current(
            connection, actor, conversation_id, candidate
        )
        node = next((n for n in definition.components if n.id == component_id), None)
        if node is None or node.component != "SourceReference":
            raise BusinessError("not_found", "No source at this component.")
        conversation = Tutor(PgTutorStore(connection)).get(actor, conversation_id)
        citation = node.props.citation
        if hasattr(citation, "binding_id"):
            block = read_citations_in(
                connection, actor, conversation.goal_id, [citation]
            )[0]
            document = Materials(connection).version(
                actor, citation.ref.document_id, citation.ref.document_revision
            )
            return CompositionSourceView(
                component_id=component_id, citation=citation, title=document.title, block=block,
                location=next(
                    (page for page in document.pages if page.number == block.source_page), None
                ),
                valid_until=min(
                    (d for d in (
                        document.permission.use_until, document.permission.retain_until
                    ) if d is not None), default=None
                ),
            )
        material = Knowledge(connection).current(
            actor, conversation.goal_id, [citation]
        )[0]
        return CompositionSourceView(
            component_id=component_id, citation=citation,
            title=material.title, excerpt=material.excerpt,
            valid_until=material.valid_until,
        )
