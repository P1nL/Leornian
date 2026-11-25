"""Submitted-code teaching uses the original public receipt, never a new scorer."""

from leornian.bootstrap.evaluation import EvaluationWorkflow
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.tutor.composition_catalog import CodeState
from leornian.modules.tutor.composition_delivery_contracts import SubmittedCodeReviewBinding
from leornian.modules.tutor.evaluations import Evaluations
from leornian.shared_kernel.errors import BusinessError


class SubmittedCodeReviews:
    @staticmethod
    def source_in(connection, actor, focus):
        if focus.kind != "attempt" or focus.assessment_receipt_id is None:
            raise BusinessError(
                "precondition_failed", "Code review needs an exact already-public attempt focus."
            )
        feedback = Evaluations(connection).receipt_context(actor, focus.assessment_receipt_id)
        if feedback["source_kind"] != "python":
            raise BusinessError("precondition_failed", "This receipt is not submitted Python code.")
        assessment = PythonAssessment(connection)
        row = assessment.row(actor, focus.assessment_receipt_id)
        if row["purpose"] != "training" or row["status"] == "queued" or not row["completed_at"]:
            raise BusinessError(
                "precondition_failed",
                "Only completed, public ordinary submissions can be reviewed.",
            )
        attempt = assessment.practice_public(row)
        pack = Packs(connection).row(actor, feedback["pack_id"])
        if (pack["plan_id"], pack["plan_revision"], pack["node_key"]) != (
            focus.plan_id, focus.expected_plan_revision, focus.node_key
        ) or attempt.pack_id != feedback["pack_id"]:
            raise BusinessError("stale_version", "Code review belongs to another node or version.")
        EvaluationWorkflow.current(connection, actor, feedback)
        receipt = feedback["context_data"]["receipt"]
        if (
            receipt["code"] != attempt.code
            or receipt["correct"] != (attempt.status == "passed")
            or receipt["passed_cases"] != attempt.passed_cases
        ):
            raise BusinessError(
                "stale_version", "The public receipt no longer matches its attempt."
            )
        return feedback, attempt

    @staticmethod
    def validate_definition(definition, binding):
        node = next(
            (n for n in definition.components if n.id == binding.component_id), None
        )
        if node is None or node.component != "CodeBlock":
            raise BusinessError("precondition_failed", "Code review needs a read-only CodeBlock.")
        code = definition.states[node.props.state]
        if code.type != "code" or not code.read_only or code.value != binding.attempt.code:
            raise BusinessError(
                "stale_version", "Code review cannot follow a different code draft."
            )
        references = [
            n for n in definition.components if n.component == "ReviewFinding"
        ]
        if not references or any(
            n.props.for_component != binding.component_id for n in references
        ):
            raise BusinessError(
                "precondition_failed", "Review findings must target this exact submitted code."
            )
        lines = binding.attempt.code.split("\n")
        if any(
            finding.line > len(lines)
            or finding.source_line != lines[finding.line - 1].removesuffix("\r")
            for finding in binding.findings
        ):
            raise BusinessError(
                "precondition_failed", "Every finding must quote its exact submitted source line."
            )

    @staticmethod
    def prepare_in(connection, actor, focus, definition, args, *, review_reports=False):
        feedback, attempt = SubmittedCodeReviews.source_in(connection, actor, focus)
        node = next((n for n in definition.components if n.id == args.code_component_id), None)
        if node is None or node.component != "CodeBlock":
            raise BusinessError("precondition_failed", "Code review needs a CodeBlock target.")
        code = definition.states[node.props.state]
        if code.type != "code" or code.value not in {"", attempt.code}:
            raise BusinessError(
                "precondition_failed", "Leave submitted code empty; the original owner fills it."
            )
        definition = definition.model_copy(update={"states": {
            **definition.states,
            node.props.state: CodeState(type="code", value=attempt.code, read_only=True),
        }})
        binding = SubmittedCodeReviewBinding(
            profile_version=(
                "submitted-code-review.v2" if review_reports else "submitted-code-review.v1"
            ),
            component_id=node.id, evaluation_id=feedback["id"], attempt=attempt,
            task=feedback["context_data"]["question"],
            recorded_correct=feedback["context_data"]["receipt"]["correct"],
            findings=args.findings,
        )
        SubmittedCodeReviews.validate_definition(definition, binding)
        return definition, binding

    @staticmethod
    def current_in(connection, actor, focus, definition, bindings):
        if len(bindings) != 1:
            raise BusinessError(
                "precondition_failed", "One exact receipt anchors this code review."
            )
        binding = bindings[0]
        feedback, attempt = SubmittedCodeReviews.source_in(connection, actor, focus)
        if (
            binding.evaluation_id != feedback["id"] or binding.attempt != attempt
            or binding.task.model_dump(mode="json") != feedback["context_data"]["question"]
            or binding.recorded_correct != feedback["context_data"]["receipt"]["correct"]
        ):
            raise BusinessError("stale_version", "Submitted-code review source changed.")
        SubmittedCodeReviews.validate_definition(definition, binding)

    @staticmethod
    def publish_in(connection, actor, presentation_id, binding):
        pack = Packs(connection).row(actor, binding.attempt.pack_id)
        item = next(i for i in Packs.document(pack).items if i.slot == binding.attempt.slot)
        Exposures(connection).record(
            actor, pack["id"], item, binding,
            receipt_ref=f"code-review:{presentation_id}:{binding.component_id}",
        )
