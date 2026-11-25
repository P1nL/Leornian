import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.change_reviews import MaterialChangeReviews
from leornian.modules.knowledge.changes import MaterialChanges
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.material_contracts import MaterialSpan
from leornian.modules.knowledge.materials import Materials, digest
from leornian.modules.knowledge.retrieval import Retrieval, coverage
from leornian.modules.knowledge.update_contracts import (
    MaterialUpdateOffer,
    MaterialUpdatePreparation,
)
from leornian.shared_kernel.errors import BusinessError


def ref_key(ref):
    return (
        ref.document_id, ref.document_revision, ref.block_id,
        ref.span.start, ref.span.end, ref.content_digest,
    )


def scope_key(value):
    return value.goal_id, value.purpose, value.plan_id, value.plan_revision, value.node_key


class MaterialUpdates:
    """Knowledge owns prepared candidate versions and immutable update offers."""

    def __init__(self, connection):
        self.connection = connection

    def ensure(self, actor_id, session_digest, review_id, check_id):
        self.connection.execute(
            "INSERT INTO knowledge.material_update_preparations"
            "(id,actor_id,session_digest,review_id,check_id) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (check_id) DO NOTHING",
            (uuid4(), actor_id, session_digest, review_id, check_id),
        )

    def purge_retained(self):
        rows = self.connection.execute(
            "UPDATE knowledge.material_update_preparations p SET status='cancelled',"
            "error_code='material_retention_expired',lease_token=NULL,lease_until=NULL "
            "FROM knowledge.material_change_checks c WHERE c.id=p.check_id "
            "AND p.error_code IS DISTINCT FROM 'material_retention_expired' AND EXISTS ("
            "SELECT 1 FROM knowledge.document_permissions d WHERE d.document_id=c.document_id "
            "AND d.document_revision IN (c.baseline_revision,c.candidate_revision) "
            "AND d.retain_until<now()) RETURNING p.id,p.actor_id,p.demand_id,p.job_id,p.search_id",
        ).fetchall()
        operations = []
        for row in rows:
            searches = self.connection.execute(
                "SELECT search_id FROM knowledge.material_search_commands WHERE actor_id=%s "
                "AND command_key=%s", (row["actor_id"], "material-update:" + str(row["id"])),
            ).fetchall()
            search_ids = list({
                *(r["search_id"] for r in searches),
                *([row["search_id"]] if row["search_id"] else []),
            })
            if search_ids:
                self.connection.execute(
                    "UPDATE knowledge.material_searches SET request=jsonb_set(request,"
                    "'{query}','null'::jsonb),status='cancelled',"
                    "error_code='material_retention_expired',lease_token=NULL,lease_until=NULL "
                    "WHERE id=ANY(%s)", (search_ids,),
                )
                operations.extend(self.connection.execute(
                    "SELECT id FROM knowledge.material_search_operations WHERE search_id=ANY(%s)",
                    (search_ids,),
                ).fetchall())
            if row["demand_id"]:
                self.connection.execute(
                    "UPDATE knowledge.material_demands SET status='cancelled',"
                    "specification=specification||"
                    "'{\"required_facets\":[],\"optional_facets\":[]}'::jsonb WHERE id=%s",
                    (row["demand_id"],),
                )
                self.connection.execute(
                    "UPDATE knowledge.material_selections SET query=NULL,facets='[]'::jsonb,"
                    "coverage=%s WHERE demand_id=%s",
                    (
                        Jsonb({
                            "status": "unavailable", "basis": "lexical-evidence.v1",
                            "required": [], "missing_facets": [],
                            "semantic_quality": "not_certified", "excluded_for_capacity": 0,
                        }),
                        row["demand_id"],
                    ),
                )
            if row["job_id"]:
                jobs = self.connection.execute(
                    "SELECT id,phase FROM knowledge.material_jobs WHERE id=%s "
                    "AND state<>'cancelled' FOR UPDATE", (row["job_id"],),
                ).fetchall()
                for job in jobs:
                    MaterialIntake(self.connection).transition(
                        job["id"], "cancelled", job["phase"],
                        reason="material_retention_expired", discard_input=True,
                    )
                operations.extend(self.connection.execute(
                    "SELECT id FROM knowledge.material_operations WHERE job_id=%s",
                    (row["job_id"],),
                ).fetchall())
        return [operation["id"] for operation in operations]

    def preparation(self, actor, check_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_update_preparations "
            "WHERE actor_id=%s AND check_id=%s" + (" FOR UPDATE" if lock else ""),
            (actor.id, check_id),
        ).fetchone()
        return row

    @staticmethod
    def preparation_view(row):
        return MaterialUpdatePreparation(
            **{key: row[key] for key in MaterialUpdatePreparation.model_fields}
        )

    def seed(self, preparation_id):
        return self.connection.execute(
            "SELECT id,actor_id,session_digest,check_id "
            "FROM knowledge.material_update_preparations WHERE id=%s", (preparation_id,),
        ).fetchone()

    def status(self, preparation_id):
        return self.connection.execute(
            "SELECT status FROM knowledge.material_update_preparations "
            "WHERE id=%s FOR UPDATE", (preparation_id,),
        ).fetchone()

    def transition(self, preparation_id, status, error=None, **links):
        allowed = {"demand_id", "job_id", "search_id", "offer_id"}
        if not set(links) <= allowed:
            raise ValueError("Unknown preparation link")
        assignments = "".join(f",{key}=%s" for key in links)
        self.connection.execute(
            "UPDATE knowledge.material_update_preparations SET status=%s,error_code=%s,"
            "lease_token=NULL,lease_until=NULL,next_run_at=now()+interval '30 seconds'"
            + assignments + " WHERE id=%s",
            (status, error, *links.values(), preparation_id),
        )

    def review(self, actor, check_id):
        report = MaterialChanges(self.connection).get(actor, check_id)
        review = MaterialChangeReviews(self.connection).for_check(actor, check_id)
        if (
            not review or review.status != "reviewed" or not review.result
            or review.result.classification != "semantic_change"
        ):
            raise BusinessError(
                "material_review_required", "A complete semantic-change review is required."
            )
        return report, review

    def origin_demand(self, actor, binding, document_id=None):
        refs = [r for r in binding.refs if document_id is None or r.document_id == document_id]
        ids = {r.selection_id for r in refs if r.selection_id is not None}
        rows = self.connection.execute(
            "SELECT DISTINCT j.demand_id FROM knowledge.material_jobs j "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "WHERE j.actor_id=%s AND j.state='ready' AND d.status<>'cancelled' "
            "AND d.revision=j.demand_revision AND EXISTS (SELECT 1 FROM "
            "jsonb_to_recordset(%s::jsonb) AS r(document_id uuid,document_revision integer) "
            "WHERE r.document_id=j.document_id AND r.document_revision=j.document_revision)",
            (actor.id, Jsonb([r.model_dump(mode="json") for r in refs])),
        ).fetchall()
        if ids:
            rows.extend(self.connection.execute(
                "SELECT DISTINCT demand_id FROM knowledge.material_selections "
                "WHERE id=ANY(%s) AND actor_id=%s", (list(ids), actor.id),
            ).fetchall())
        demands = {
            r["demand_id"]: MaterialIntake(self.connection).demand(actor, r["demand_id"])
            for r in rows
        }
        demands = [
            d for d in demands.values()
            if d.status != "cancelled" and scope_key(d) == scope_key(binding)
        ]
        if not demands:
            return None
        first = demands[0]
        facets = list(dict.fromkeys(f for d in demands for f in d.required_facets))
        if len(facets) > 100:
            raise BusinessError(
                "candidate_capacity_exceeded", "Source facets need a smaller scope."
            )
        return first.model_copy(update={"required_facets": facets})

    def ready_selection(self, actor, binding, report, selection_id):
        retrieval = Retrieval(self.connection)
        selected = retrieval.selection(actor, selection_id)
        demand = MaterialIntake(self.connection).demand(actor, selected.demand_id)
        if scope_key(demand) != scope_key(binding) or demand.status == "cancelled":
            raise BusinessError("source_not_current", "Candidate selection scope changed.")
        ready = self.connection.execute(
            "SELECT 1 FROM knowledge.material_jobs WHERE actor_id=%s AND demand_id=%s "
            "AND demand_revision=%s AND document_id=%s AND document_revision=%s AND state='ready'",
            (actor.id, demand.id, demand.revision, report.document_id, report.candidate_revision),
        ).fetchone()
        if not ready:
            raise BusinessError("candidate_not_ready", "The exact candidate is not prepared.")
        if selected.coverage.status != "sufficient" or selected.coverage.excluded_for_capacity:
            raise BusinessError("candidate_coverage_gap", "Candidate selection is incomplete.")
        candidate = [
            e for e in selected.evidence if (
                e.ref.document_id, e.ref.document_revision
            ) == (report.document_id, report.candidate_revision)
        ]
        if not candidate:
            raise BusinessError("candidate_coverage_gap", "Candidate evidence is missing.")
        return demand, candidate

    @staticmethod
    def required_candidate_refs(binding, report):
        baseline = [r for r in binding.refs if r.document_id == report.document_id]
        for changed in report.removed_or_changed_blocks:
            intervals = sorted(
                (r.span.start, r.span.end) for r in baseline
                if r.block_id == changed.block_id
            )
            cursor = changed.span.start
            for start, end in intervals:
                if start <= cursor:
                    cursor = max(cursor, end)
            if cursor < changed.span.end:
                raise BusinessError(
                    "change_scope_incomplete", "Changed source ranges need complete exact binding."
                )
        desired = [m.candidate for m in report.relocated_refs] + report.added_or_changed_blocks
        if not desired:
            raise BusinessError("candidate_coverage_gap", "No successor material remains.")
        return desired

    def candidate_refs(self, actor, binding, report, selection_id):
        desired = self.required_candidate_refs(binding, report)
        demand, evidence = self.ready_selection(actor, binding, report, selection_id)
        refs, clipped_evidence = {}, []
        for wanted in desired:
            matches = sorted(
                (e for e in evidence if e.ref.block_id == wanted.block_id),
                key=lambda e: e.ref.span.start,
            )
            cursor = wanted.span.start
            for item in matches:
                start = max(cursor, wanted.span.start, item.ref.span.start)
                end = min(wanted.span.end, item.ref.span.end)
                if end <= start:
                    continue
                if start > cursor:
                    break
                text = item.text[start - item.ref.span.start:end - item.ref.span.start]
                exact = start == item.ref.span.start and end == item.ref.span.end
                ref = item.ref.model_copy(update={
                    "span": MaterialSpan(start=start, end=end),
                    "content_digest": digest(text),
                    "selection_id": item.ref.selection_id if exact else None,
                })
                refs[ref_key(ref)] = ref
                clipped_evidence.append(item.model_copy(update={"ref": ref, "text": text}))
                cursor = end
                if cursor == wanted.span.end:
                    break
            if cursor != wanted.span.end:
                raise BusinessError(
                    "candidate_coverage_gap", "Candidate evidence does not cover every exact range."
                )
        if coverage(demand.required_facets, clipped_evidence).status != "sufficient":
            raise BusinessError("candidate_coverage_gap", "Successor scope has missing facets.")
        result = list(refs.values())
        if len(result) > 2000:
            raise BusinessError(
                "candidate_capacity_exceeded", "Split the candidate material scope."
            )
        Materials(self.connection).read_refs(actor, binding.goal_id, binding.purpose, result)
        return result

    def replay(self, actor, key, request):
        row = self.connection.execute(
            "SELECT request,offer_id FROM knowledge.material_update_offer_commands "
            "WHERE actor_id=%s AND command_key=%s", (actor.id, key),
        ).fetchone()
        if row and row["request"] != request:
            raise BusinessError("idempotency_conflict", "Update offer key changed.")
        return row["offer_id"] if row else None

    def remember(self, actor, key, request, offer_id):
        self.connection.execute(
            "INSERT INTO knowledge.material_update_offer_commands"
            "(actor_id,command_key,request,offer_id) VALUES (%s,%s,%s,%s)",
            (actor.id, key, Jsonb(request), offer_id),
        )

    def save_offer(self, actor, row, binding, report, selection_id, candidate_refs, impact):
        old_other = [r for r in binding.refs if r.document_id != report.document_id]
        successor = [*old_other, *candidate_refs]
        if not successor or len(successor) > 2000:
            raise BusinessError("candidate_capacity_exceeded", "Successor binding is too large.")
        version = Materials(self.connection).require_use(
            actor, report.document_id, report.candidate_revision, binding.purpose,
            goal_id=binding.goal_id,
        )
        identity = digest(json.dumps({
            "document_id": str(report.document_id),
            "candidate_content": version.content_digest,
        }, sort_keys=True))
        offer_id = uuid4()
        self.connection.execute(
            "INSERT INTO knowledge.material_update_offers"
            "(id,actor_id,preparation_id,check_id,binding_id,binding_revision,"
            "candidate_selection_id,candidate_refs,successor_refs,substantive_identity,impact) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (
                offer_id, actor.id, row["id"], report.id, binding.id, binding.revision,
                selection_id, Jsonb([r.model_dump(mode="json") for r in candidate_refs]),
                Jsonb([r.model_dump(mode="json") for r in successor]), identity,
                Jsonb(impact.model_dump(mode="json")),
            ),
        )
        stored = self.connection.execute(
            "SELECT id FROM knowledge.material_update_offers WHERE actor_id=%s "
            "AND binding_id=%s AND binding_revision=%s AND substantive_identity=%s",
            (actor.id, binding.id, binding.revision, identity),
        ).fetchone()
        self.transition(row["id"], "ready", offer_id=stored["id"])
        return stored["id"]

    def offer_row(self, actor, offer_id):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_update_offers WHERE id=%s AND actor_id=%s",
            (offer_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material update offer not found.")
        return row

    def offer(self, actor, offer_id, binding):
        row = self.offer_row(actor, offer_id)
        report, review = self.review(actor, row["check_id"])
        Materials(self.connection).read_refs(
            actor, binding.goal_id, binding.purpose, binding.refs
        )
        from leornian.modules.knowledge.material_contracts import MaterialRef

        refs = [MaterialRef(**r) for r in row["candidate_refs"]]
        Materials(self.connection).read_refs(actor, report.goal_id, report.purpose, refs)
        dependencies = row["impact"]["dependencies"]
        return MaterialUpdateOffer(
            **{key: row[key] for key in (
                "id", "revision", "check_id", "preparation_id", "binding_id",
                "binding_revision", "candidate_selection_id", "created_at",
            )},
            goal_id=binding.goal_id, plan_id=binding.plan_id, plan_revision=binding.plan_revision,
            node_key=binding.node_key, purpose=binding.purpose,
            document_id=report.document_id, baseline_revision=report.baseline_revision,
            candidate_revision=report.candidate_revision, candidate_refs=refs,
            summary=review.result.summary, impact=row["impact"],
            migration_cost=(
                "dependent_content_requires_reprepare" if dependencies else "binding_only"
            ),
        )
