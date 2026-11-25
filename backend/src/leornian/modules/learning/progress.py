from leornian.modules.assessment.contracts import (
    ConceptCompletion,
    ProgramCompletion,
    PythonCompletion,
)
from leornian.modules.learning.contracts import NodeProgress
from leornian.modules.learning.execution_contracts import ExecutionProgress
from leornian.modules.learning.reviews import Reviews
from leornian.shared_kernel.errors import BusinessError


class Progress:
    def __init__(self, connection):
        self.connection = connection

    def require_prerequisites(self, actor, plan_id, revision, node):
        completed = {
            row["node_key"]
            for row in self.connection.execute(
                "SELECT node_key FROM learning.node_progress WHERE actor_id=%s AND plan_id=%s "
                "AND plan_revision=%s",
                (actor.id, plan_id, revision),
            ).fetchall()
        }
        if not set(node.prerequisite_keys) <= completed:
            raise BusinessError("precondition_failed", "Complete prerequisite concept Gates first.")

    def apply(self, actor, completion: ConceptCompletion):
        inserted = self.connection.execute(
            "INSERT INTO learning.concept_evidence(gate_id,actor_id,plan_id,plan_revision,node_key,"
            "policy_version,passed_items,total_items) VALUES(%s,%s,%s,%s,%s,%s,2,2) "
            "ON CONFLICT DO NOTHING RETURNING gate_id",
            (
                completion.gate_id,
                actor.id,
                completion.plan_id,
                completion.plan_revision,
                completion.node_key,
                completion.policy_version,
            ),
        ).fetchone()
        if not inserted:
            return False
        changed = (
            self.connection.execute(
                "INSERT INTO learning.node_progress(actor_id,plan_id,plan_revision,node_key,"
                "evidence_gate_id) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING "
                "RETURNING node_key",
                (
                    actor.id,
                    completion.plan_id,
                    completion.plan_revision,
                    completion.node_key,
                    completion.gate_id,
                ),
            ).fetchone()
            is not None
        )
        if changed:
            Reviews(self.connection).schedule_node_completed(
                actor, completion.plan_id, completion.plan_revision, completion.node_key,
                completion.gate_id,
            )
        return changed

    def list(self, actor):
        return [
            NodeProgress(**row)
            for row in self.connection.execute(
                "SELECT plan_id,plan_revision,node_key,evidence_gate_id,completed_at "
                "FROM learning.node_progress WHERE actor_id=%s "
                "ORDER BY completed_at DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def apply_python(self, actor, completion: PythonCompletion):
        return self._apply_execution(actor, completion)

    def apply_program(self, actor, completion: ProgramCompletion):
        return self._apply_execution(actor, completion)

    def _apply_execution(self, actor, completion):
        changed = (
            self.connection.execute(
                "INSERT INTO learning.execution_evidence"
                "(gate_id,actor_id,plan_id,plan_revision,node_key,policy_version) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING gate_id",
                (
                    completion.gate_id,
                    actor.id,
                    completion.plan_id,
                    completion.plan_revision,
                    completion.node_key,
                    completion.policy_version,
                ),
            ).fetchone()
            is not None
        )
        if changed:
            Reviews(self.connection).schedule_node_completed(
                actor, completion.plan_id, completion.plan_revision, completion.node_key,
                completion.gate_id,
            )
        return changed

    def python_list(self, actor):
        return [
            ExecutionProgress(**row)
            for row in self.connection.execute(
                "SELECT gate_id,plan_id,plan_revision,node_key,policy_version,completed_at "
                "FROM learning.execution_evidence WHERE actor_id=%s "
                "ORDER BY completed_at DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]
