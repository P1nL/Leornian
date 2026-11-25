"""Demo reports use the original artifact transaction and current-scope checks."""

from psycopg.types.json import Jsonb

from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.modules.tutor.demo_contracts import DemoActionReceipt
from leornian.modules.tutor.demos import DemoReports, demonstration_input
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.shared_kernel.errors import BusinessError


class DemoInteractions:
    @staticmethod
    def action_in(connection, actor, artifact, data):
        if artifact["kind"] != "learning_composition" or artifact["state"] not in {
            "ready", "completed",
        }:
            raise BusinessError("precondition_failed", "No ready demonstration interaction.")
        presentation, definition, _ = LearningArtifactWorkflow.current(
            connection, actor, artifact["conversation_id"], artifact,
        )
        binding = next(
            (item for item in presentation["demo_bindings"]
             if item["component_id"] == data.component_id), None,
        )
        if binding is None:
            raise BusinessError("not_found", "No checked demonstration event binding.")
        reports = DemoReports(connection)
        completion_id = None
        if data.action == "start_demo":
            last_step = demonstration_input(definition, data.component_id, data.inputs)
            reports.start(artifact["id"], data.component_id, data.inputs, last_step)
        elif data.action == "acknowledge_demo_event":
            reports.acknowledge(artifact["id"], data, binding)
        else:
            completion_id = reports.complete(artifact, data, binding)
        connection.execute(
            "UPDATE tutor.learning_artifacts a SET revision=revision+1,state=CASE "
            "WHEN EXISTS(SELECT 1 FROM tutor.learning_component_bindings b "
            "WHERE b.artifact_id=a.id AND b.state='running') THEN 'running' "
            "WHEN EXISTS(SELECT 1 FROM tutor.learning_component_bindings b "
            "WHERE b.artifact_id=a.id AND b.state='ready') OR "
            "EXISTS(SELECT 1 FROM tutor.demo_observations d "
            "WHERE d.artifact_id=a.id AND d.state<>'completed') THEN 'ready' "
            "ELSE 'completed' END WHERE a.id=%s",
            (artifact["id"],),
        )
        current = LearningArtifacts(connection).row(
            actor, artifact["conversation_id"], artifact["id"],
        )
        observation = reports.row(artifact["id"], data.component_id)
        receipt = DemoActionReceipt(
            client_action_id=data.client_action_id, artifact_id=artifact["id"],
            artifact_revision=current["revision"], state=current["state"],
            component_id=data.component_id,
            generation=observation["generation"], nonce=observation["nonce"],
            sequence=observation["sequence"],
            result_owner="tutor" if completion_id else None, result_id=completion_id,
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
        if completion_id:
            from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow

            TeachingContinuationWorkflow.capture_in(
                connection, actor, artifact["conversation_id"], artifact["id"],
                "interaction_event", f"demo:{completion_id}",
            )
        return receipt
