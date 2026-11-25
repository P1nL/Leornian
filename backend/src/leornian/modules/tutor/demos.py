"""Bounded demo ports and durable reports owned by Tutor, not a new scorer."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.tutor.demo_contracts import DemoBinding, DemoCompletion, DemoHistory, DemoView
from leornian.shared_kernel.errors import BusinessError


def demo_bindings(definition, component_ids):
    nodes = {node.id: node for node in definition.components}
    if len(set(component_ids)) != len(component_ids):
        raise BusinessError("precondition_failed", "Demonstration targets must be distinct.")
    bindings = []
    for key in component_ids:
        node = nodes.get(key)
        if not node or node.component not in {
            "AlgorithmPlayer", "StepPlayer", "SequenceDiagram", "IsolatedPreview",
        }:
            raise BusinessError("precondition_failed", "No bounded demonstration event port.")
        bindings.append(DemoBinding(
            component_id=key,
            event="preview_snapshot" if node.component == "IsolatedPreview" else "timeline_end",
        ))
    return bindings


def demonstration_input(definition, component_id, values):
    node = next(node for node in definition.components if node.id == component_id)
    keys = []
    if node.component == "AlgorithmPlayer":
        source = definition.inputs[node.props.input]
        if source.type == "binary_search":
            keys = [source.target_state]
    elif node.component == "IsolatedPreview":
        keys = [key for key in (node.props.html_state, node.props.css_state) if key]
    if set(keys) != values.keys():
        raise BusinessError("precondition_failed", "Use only this demonstration's exact inputs.")
    for key in keys:
        state = definition.states[key]
        value = values[key]
        if state.type == "number":
            controls = [
                n.props for n in definition.components
                if n.component == "ParameterControl" and n.props.state == key
            ]
            if isinstance(value, bool) or not isinstance(value, int | float) or (
                not controls and value != state.value
            ) or any(not c.minimum <= value <= c.maximum for c in controls):
                raise BusinessError("precondition_failed", "Demo parameter is outside its control.")
        elif (
            not isinstance(value, str) or len(value) > 20000
            or state.read_only and value != state.value
        ):
            raise BusinessError("precondition_failed", "Preview input differs from its code port.")
    if node.component == "IsolatedPreview":
        return None
    if node.component in {"StepPlayer", "SequenceDiagram"}:
        return len(node.props.items if node.component == "StepPlayer" else node.props.steps) - 1
    return algorithm_last_step(source, values)


def algorithm_last_step(source, values):
    """Validate trace endpoints; rendering and explanatory frames remain client-owned."""
    kind = source.type
    if kind == "binary_search":
        left, right, count = 0, len(source.values) - 1, 1
        while left <= right:
            mid = (left + right) // 2
            count += 2
            if source.values[mid] == values[source.target_state]:
                return count - 1
            if source.values[mid] < values[source.target_state]:
                left = mid + 1
            else:
                right = mid - 1
        return count
    if kind == "brackets":
        stack, count = [], 1
        pairs = {")": "(", "]": "[", "}": "{"}
        for char in source.text:
            count += 2
            if char in "([{":
                stack.append(char)
            elif not stack or stack.pop() != pairs[char]:
                return count - 1
        return count
    if kind == "bfs":
        queue, seen, count = [source.start], {source.start}, 1
        for current in queue:
            count += 1
            for edge in source.edges:
                if edge.source != current:
                    continue
                count += 1
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append(edge.target)
        return count
    if kind == "grid_paths":
        return source.rows * source.columns + 1
    if kind == "combination_sum":
        def visit(start, total):
            if total >= source.target:
                return 2
            return 1 + sum(
                visit(i + 1, total + source.values[i]) + 1
                for i in range(start, len(source.values))
            )

        return visit(0, 0)
    if kind == "interval_scan":
        return len(source.intervals) * 2 + 1
    return 2  # The closed remaining inputs are bitwise and three-point orientation.


class DemoReports:
    def __init__(self, connection):
        self.connection = connection

    def assign(self, artifact_id, bindings):
        for binding in bindings:
            self.connection.execute(
                "INSERT INTO tutor.demo_observations(artifact_id,component_id) VALUES(%s,%s)",
                (artifact_id, binding["component_id"]),
            )

    def row(self, artifact_id, component_id):
        row = self.connection.execute(
            "SELECT * FROM tutor.demo_observations WHERE artifact_id=%s AND component_id=%s",
            (artifact_id, component_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "No delivered demonstration binding.")
        return row

    def views(self, artifact, bindings):
        views = []
        enabled = artifact["state"] in {"ready", "completed"}
        for binding in bindings:
            row = self.row(artifact["id"], binding["component_id"])
            history = self.history(artifact["id"], binding["component_id"], limit=5)
            count = self.connection.execute(
                "SELECT count(*) AS n FROM tutor.demo_completions "
                "WHERE artifact_id=%s AND component_id=%s",
                (artifact["id"], binding["component_id"]),
            ).fetchone()["n"]
            actions = ["start_demo"]
            if row["state"] == "started":
                actions.append("acknowledge_demo_event")
            if row["state"] == "acknowledged":
                actions.append("complete_demo")
            views.append(DemoView(
                **binding,
                **{key: row[key] for key in (
                    "state", "generation", "nonce", "sequence", "inputs", "last_step",
                )},
                allowed_actions=actions if enabled else [],
                completions=history.items, completion_count=count,
                next_completion_before=history.next_before,
            ))
        return views

    def history(self, artifact_id, component_id, before=None, limit=20):
        self.row(artifact_id, component_id)
        rows = self.connection.execute(
            "SELECT * FROM tutor.demo_completions WHERE artifact_id=%s AND component_id=%s "
            "AND (%s::integer IS NULL OR generation<%s) ORDER BY generation DESC LIMIT %s",
            (artifact_id, component_id, before, before, limit + 1),
        ).fetchall()
        return DemoHistory(
            items=[DemoCompletion(**item) for item in rows[:limit]],
            next_before=rows[limit - 1]["generation"] if len(rows) > limit else None,
        )

    def start(self, artifact_id, component_id, inputs, last_step):
        self.connection.execute(
            "UPDATE tutor.demo_observations SET generation=generation+1,nonce=%s,state='started',"
            "inputs=%s,last_step=%s,sequence=0 WHERE artifact_id=%s AND component_id=%s",
            (uuid4(), Jsonb(inputs), last_step, artifact_id, component_id),
        )

    def acknowledge(self, artifact_id, data, binding):
        row = self.row(artifact_id, data.component_id)
        self.require_sequence(row, data, 0)
        if row["state"] != "started" or data.event != binding["event"] or (
            data.step_index != row["last_step"]
        ):
            raise BusinessError("precondition_failed", "Report the exact published demo event.")
        self.connection.execute(
            "UPDATE tutor.demo_observations SET state='acknowledged',sequence=1 "
            "WHERE artifact_id=%s AND component_id=%s",
            (artifact_id, data.component_id),
        )

    @staticmethod
    def require_sequence(row, data, previous):
        if (
            row["generation"] != data.generation or row["nonce"] != data.nonce
            or row["sequence"] != previous or data.sequence != previous + 1
        ):
            raise BusinessError("stale_version", "Demo generation, nonce or sequence changed.")

    def complete(self, artifact, data, binding):
        row = self.row(artifact["id"], data.component_id)
        self.require_sequence(row, data, 1)
        if row["state"] != "acknowledged":
            raise BusinessError("precondition_failed", "Acknowledge the expected event first.")
        completion_id = uuid4()
        self.connection.execute(
            "INSERT INTO tutor.demo_completions"
            "(id,artifact_id,component_id,generation,presentation_id,content_identity,inputs,event,"
            "last_step) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                completion_id, artifact["id"], data.component_id, row["generation"],
                artifact["presentation_id"], artifact["public_identity"], Jsonb(row["inputs"]),
                binding["event"], row["last_step"],
            ),
        )
        self.connection.execute(
            "UPDATE tutor.demo_observations SET state='completed',sequence=2 "
            "WHERE artifact_id=%s AND component_id=%s",
            (artifact["id"], data.component_id),
        )
        return completion_id
