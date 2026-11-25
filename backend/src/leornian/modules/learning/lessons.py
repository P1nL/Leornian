from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.knowledge.contracts import Material
from leornian.modules.learning.contracts import (
    GeneratedLesson,
    LessonDocument,
    LessonRequest,
    LessonRequestInput,
    PlanNode,
)
from leornian.modules.learning.material_contracts import (
    MaterialCitation,
    citation_key,
    material_content_key,
)
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError

REQUEST_COLUMNS = "id, plan_id, plan_revision, node_key, instruction"
DOCUMENT_COLUMNS = (
    "d.id, r.plan_id, r.plan_revision, r.node_key, d.document, d.sources, d.created_at "
    "FROM learning.lesson_documents d JOIN learning.lesson_requests r ON r.id = d.request_id "
)


class Lessons:
    def __init__(self, connection: Connection):
        self.connection = connection

    def request(
        self,
        actor: Actor,
        plan_id: UUID,
        key: str,
        data: LessonRequestInput,
    ) -> tuple[LessonRequest, bool]:
        row = self.connection.execute(
            f"SELECT {REQUEST_COLUMNS} FROM learning.lesson_requests "
            "WHERE actor_id = %s AND idempotency_key = %s",
            (actor.id, key),
        ).fetchone()
        if row:
            if any(
                row[field] != value
                for field, value in {
                    "plan_id": plan_id,
                    "plan_revision": data.expected_plan_revision,
                    "node_key": data.node_key,
                    "instruction": data.instruction,
                }.items()
            ):
                raise BusinessError(
                    "idempotency_conflict", "Lesson request key has different content."
                )
            return LessonRequest(**row), False
        request = LessonRequest(
            id=uuid4(),
            plan_id=plan_id,
            plan_revision=data.expected_plan_revision,
            node_key=data.node_key,
            instruction=data.instruction,
        )
        self.current(actor, request)
        self.connection.execute(
            "INSERT INTO learning.lesson_requests(id, actor_id, plan_id, plan_revision, node_key, "
            "idempotency_key, instruction) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                request.id,
                actor.id,
                plan_id,
                request.plan_revision,
                request.node_key,
                key,
                request.instruction,
            ),
        )
        return request, True

    def get_request(self, actor: Actor, request_id: UUID) -> LessonRequest:
        row = self.connection.execute(
            f"SELECT {REQUEST_COLUMNS} FROM learning.lesson_requests "
            "WHERE id = %s AND actor_id = %s",
            (request_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Lesson request not found.")
        return LessonRequest(**row)

    def current(self, actor: Actor, request: LessonRequest, *, lock: bool = False) -> PlanNode:
        # Plan confirmation and generation application serialize on this same head.
        plan = Plans(self.connection).get(actor, request.plan_id, lock=lock)
        if not plan.active or plan.active.revision != request.plan_revision:
            raise BusinessError("stale_version", "Lesson must use the currently confirmed plan.")
        node = next(
            (item for item in plan.active.document.nodes if item.key == request.node_key), None
        )
        if node is None:
            raise BusinessError("not_found", "Node not found in the confirmed plan.")
        if not node.source_refs and not node.material_citations:
            raise BusinessError(
                "source_not_current", "Add admitted sources before generating this lesson."
            )
        return node

    def record(
        self,
        actor: Actor,
        request: LessonRequest,
        run_id: UUID,
        document: LessonDocument,
        materials: list[Material],
        material_citations: list[MaterialCitation] | None = None,
    ) -> GeneratedLesson:
        node = self.current(actor, request, lock=True)
        allowed = {(ref.source_id, ref.revision) for ref in node.source_refs}
        actual = {(material.source_id, material.revision) for material in materials}
        if actual != allowed:
            raise BusinessError(
                "source_not_current", "Lesson sources must match the confirmed node."
            )
        supplied = material_citations or []
        if (
            {material_content_key(c.ref) for c in supplied}
            != {material_content_key(c.ref) for c in node.material_citations}
            or any(c.purpose != "lesson" for c in supplied)
        ):
            raise BusinessError(
                "source_not_current", "Lesson materials must match the confirmed node."
            )
        allowed_citations = {citation_key(c) for c in supplied}
        for section in document.sections:
            refs = [(ref.source_id, ref.revision) for ref in section.source_refs]
            if (
                not set(refs) <= allowed or len(set(refs)) != len(refs)
                or not {citation_key(c) for c in section.material_citations} <= allowed_citations
            ):
                raise BusinessError(
                    "invalid_lesson_output", "Lesson section cites an unbound source."
                )
        lesson_id = uuid4()
        self.connection.execute(
            "INSERT INTO learning.lesson_documents"
            "(id, request_id, produced_by_run, document, sources) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                lesson_id,
                request.id,
                run_id,
                Jsonb(document.model_dump(mode="json")),
                Jsonb([material.model_dump(mode="json") for material in materials]),
            ),
        )
        return self.get(actor, lesson_id)

    def get(self, actor: Actor, lesson_id: UUID) -> GeneratedLesson:
        row = self.connection.execute(
            "SELECT " + DOCUMENT_COLUMNS + "WHERE d.id = %s AND r.actor_id = %s",
            (lesson_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Lesson document not found.")
        return GeneratedLesson(**row)

    def for_run(self, actor, run_id):
        row = self.connection.execute(
            "SELECT " + DOCUMENT_COLUMNS + "WHERE r.actor_id=%s AND d.produced_by_run=%s",
            (actor.id, run_id),
        ).fetchone()
        return GeneratedLesson(**row) if row else None

    def latest_for_plan(
        self,
        actor: Actor,
        plan_id: UUID,
        revision: int,
    ) -> GeneratedLesson | None:
        row = self.connection.execute(
            "SELECT "
            + DOCUMENT_COLUMNS
            + "WHERE r.actor_id = %s AND r.plan_id = %s AND r.plan_revision = %s "
            "ORDER BY d.created_at DESC, d.id DESC LIMIT 1",
            (actor.id, plan_id, revision),
        ).fetchone()
        return GeneratedLesson(**row) if row else None

    def for_node(self, actor, plan_id, revision, node_key):
        row = self.connection.execute(
            "SELECT "
            + DOCUMENT_COLUMNS
            + "WHERE r.actor_id=%s AND r.plan_id=%s AND r.plan_revision=%s AND r.node_key=%s "
            "ORDER BY d.created_at DESC,d.id DESC LIMIT 1",
            (actor.id, plan_id, revision, node_key),
        ).fetchone()
        return GeneratedLesson(**row) if row else None

    def gate_context(self, actor):
        rows = self.connection.execute(
            "SELECT " + DOCUMENT_COLUMNS + "WHERE r.actor_id=%s ORDER BY d.created_at,d.id",
            (actor.id,),
        ).fetchall()
        return [GeneratedLesson(**row).model_dump(mode="json") for row in rows]

    def list(self, actor: Actor) -> list[GeneratedLesson]:
        return [
            GeneratedLesson(**row)
            for row in self.connection.execute(
                "SELECT "
                + DOCUMENT_COLUMNS
                + "WHERE r.actor_id = %s ORDER BY d.created_at DESC, d.id "
                "LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]
