"""Record review acknowledgement with the original artifact action transaction."""

from psycopg.types.json import Jsonb

from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.modules.tutor.review_contracts import ReviewActionReceipt
from leornian.modules.tutor.reviews import ReviewReports
from leornian.shared_kernel.errors import BusinessError


class ReviewCompletionWorkflow:
    @staticmethod
    def action_in(connection, actor, artifact, data):
        if artifact["kind"] != "learning_composition" or artifact["state"] != "ready":
            raise BusinessError("precondition_failed", "No ready submitted-code review.")
        presentation, _definition, _manifest = LearningArtifactWorkflow.current(
            connection, actor, artifact["conversation_id"], artifact,
        )
        binding = next((
            item for item in presentation["review_bindings"]
            if item["component_id"] == data.component_id
            and item["profile_version"] == "submitted-code-review.v2"
        ), None)
        if binding is None:
            raise BusinessError("not_found", "No reading-report binding at this component.")
        completion = ReviewReports(connection).complete(artifact, presentation, binding)
        current = connection.execute(
            "UPDATE tutor.learning_artifacts SET revision=revision+1,state='completed' "
            "WHERE id=%s RETURNING revision,state",
            (artifact["id"],),
        ).fetchone()
        receipt = ReviewActionReceipt(
            client_action_id=data.client_action_id, artifact_id=artifact["id"],
            artifact_revision=current["revision"], state=current["state"],
            component_id=data.component_id, result_id=completion.id,
        )
        connection.execute(
            "INSERT INTO tutor.learning_artifact_actions"
            "(actor_id,client_action_id,artifact_id,request,result) VALUES(%s,%s,%s,%s,%s)",
            (
                actor.id, data.client_action_id, artifact["id"],
                Jsonb(data.model_dump(mode="json")), Jsonb(receipt.model_dump(mode="json")),
            ),
        )
        LearningArtifactWorkflow.event(
            connection, actor, artifact["id"], artifact["conversation_id"],
        )
        return receipt
