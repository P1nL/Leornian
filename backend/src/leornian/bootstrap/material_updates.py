from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.delivery.notifications import Notifications
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.material_contracts import MaterialRef
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.knowledge.updates import MaterialUpdates, ref_key
from leornian.modules.learning.material_update_contracts import MaterialUpdateDecisionInput
from leornian.modules.learning.material_updates import MaterialUpdateDecisions
from leornian.modules.learning.materials import MaterialBindings
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


class MaterialUpdateWorkflow:
    def __init__(self, database, settings=None):
        self.database, self.settings = database, settings or Settings()

    @staticmethod
    def current(connection, actor, check_id, expected_revision=None):
        report, review = MaterialUpdates(connection).review(actor, check_id)
        bindings = MaterialBindings(connection)
        binding = bindings.get(actor, report.binding_id, lock=True)
        if binding.revision != report.binding_revision or (
            expected_revision is not None and binding.revision != expected_revision
        ):
            raise BusinessError("stale_version", "Update baseline binding changed.")
        bindings.require_scope(actor, binding)
        Materials(connection).read_refs(
            actor, binding.goal_id, binding.purpose, binding.refs
        )
        return report, review, binding

    def get_preparation(self, token, check_id):
        from leornian.modules.knowledge.changes import MaterialChanges

        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            MaterialChanges(connection).get(actor, check_id)
            updates = MaterialUpdates(connection)
            row = updates.preparation(actor, check_id)
            return updates.preparation_view(row) if row else None

    @staticmethod
    def offer_in(connection, actor, offer_id):
        updates = MaterialUpdates(connection)
        row = updates.offer_row(actor, offer_id)
        binding = MaterialBindings(connection).get(
            actor, row["binding_id"], row["binding_revision"]
        )
        return updates.offer(actor, offer_id, binding)

    def get(self, token, offer_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return self.offer_in(connection, actor, offer_id)

    @staticmethod
    def publish_in(connection, actor, row, binding, report, selection_id):
        updates = MaterialUpdates(connection)
        refs = updates.candidate_refs(actor, binding, report, selection_id)
        impact = MaterialUpdateDecisions(connection).impact(actor, binding, report.document_id)
        offer_id = updates.save_offer(
            actor, row, binding, report, selection_id, refs, impact
        )
        offer = updates.offer(actor, offer_id, binding)
        Notifications(connection).offer(actor, offer)
        return offer

    def prepare(self, token, check_id, key, data):
        request = {"check_id": str(check_id), **data.model_dump(mode="json")}
        with self.database.transaction() as connection:
            auth = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = auth.authenticate(token)
            updates = MaterialUpdates(connection)
            previous = updates.replay(actor, key, request)
            if previous:
                return self.offer_in(connection, actor, previous)
            report, review, binding = self.current(
                connection, actor, check_id, data.expected_binding_revision
            )
            updates.ensure(actor.id, auth.digest(token), review.id, check_id)
            row = updates.preparation(actor, check_id, lock=True)
            offer = (
                self.offer_in(connection, actor, row["offer_id"]) if row["offer_id"]
                else self.publish_in(
                    connection, actor, row, binding, report, data.candidate_selection_id
                )
            )
            updates.remember(actor, key, request, offer.id)
            return offer

    @staticmethod
    def demand_input(connection, actor, binding, document_id):
        origin = MaterialUpdates(connection).origin_demand(actor, binding, document_id)
        fields = {
            "goal_id": binding.goal_id, "purpose": binding.purpose,
            "plan_id": binding.plan_id, "plan_revision": binding.plan_revision,
            "node_key": binding.node_key,
        }
        if origin:
            return MaterialDemandInput(
                **origin.model_dump(include=set(MaterialDemandInput.model_fields) - set(fields)),
                **fields,
            )
        # A direct binding has exact ranges, not a teaching requirement inferred from its title.
        return MaterialDemandInput(**fields, scope_mode="whole_source")

    def repair_inferred_scope(self, token, check_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            updates = MaterialUpdates(connection)
            report, _review, binding = self.current(connection, actor, check_id)
            row = updates.preparation(actor, check_id, lock=True)
            if (
                not row or row["status"] != "waiting_dependency"
                or not row["demand_id"] or not row["job_id"]
                or row["search_id"] or row["offer_id"]
                or updates.origin_demand(actor, binding, report.document_id) is not None
            ):
                raise BusinessError(
                    "precondition_failed", "No unresolved inferred update scope to replace."
                )
            intake = MaterialIntake(connection)
            old = intake.demand(actor, row["demand_id"])
            if old.scope_mode != "facets" or old.consumer_ref != (
                "material-update:" + str(row["id"])
            ):
                raise BusinessError(
                    "precondition_failed", "Explicit material requirements cannot be replaced."
                )
            job = intake.job(actor, row["job_id"])
            if job.state != "waiting_dependency" or not job.issues or not (
                set(job.issues) <= set(old.required_facets)
            ):
                raise BusinessError(
                    "precondition_failed", "The preparation has no inferred-facet coverage failure."
                )
            jobs = connection.execute(
                "SELECT id,phase,state FROM knowledge.material_jobs WHERE root_id=%s "
                "AND actor_id=%s FOR UPDATE", (job.root_id, actor.id),
            ).fetchall()
            if any(child["state"] == "processing" for child in jobs):
                raise BusinessError("precondition_failed", "Wait for the original preparation.")
            operations = connection.execute(
                "SELECT c.status FROM knowledge.material_operations o "
                "LEFT JOIN runtime.external_calls c ON c.operation_ref=o.id "
                "WHERE o.job_id=ANY(%s)", ([child["id"] for child in jobs],),
            ).fetchall()
            if any(op["status"] not in {"result_recorded", "failed_known", "not_sent"}
                   for op in operations):
                raise BusinessError(
                    "unknown_unresolved", "Reconcile original material operations first."
                )
            for child in jobs:
                if child["state"] != "cancelled":
                    intake.transition(
                        child["id"], "cancelled", child["phase"],
                        reason="inferred_scope_replaced", discard_input=True,
                    )
            demand = intake.ensure_consumer_demand(
                actor, "material-update:" + str(row["id"]) + ":exact-source.v1",
                self.demand_input(connection, actor, binding, report.document_id),
            )
            replacement = intake.prepare_revision(
                actor, Identity.digest(token), demand.id,
                report.document_id, report.candidate_revision,
            )
            updates.transition(
                row["id"], "queued", "candidate_preparation_pending",
                demand_id=demand.id, job_id=replacement.id,
            )
            return updates.preparation_view(updates.preparation(actor, check_id))

    def execute(self, preparation_id):
        search_input = None
        session_digest = None
        try:
            with self.database.transaction() as connection:
                updates = MaterialUpdates(connection)
                seed = updates.seed(preparation_id)
                if not seed:
                    return
                auth = Identity(PgIdentityStore(connection, serialize_actor=True))
                actor = auth.authenticate_digest(seed["session_digest"])
                row = updates.preparation(actor, seed["check_id"], lock=True)
                if row["status"] in {"ready", "cancelled"}:
                    return
                report, _review, binding = self.current(connection, actor, seed["check_id"])
                required_refs = updates.required_candidate_refs(binding, report)
                intake = MaterialIntake(connection)
                if not row["job_id"]:
                    demand = intake.ensure_consumer_demand(
                        actor, "material-update:" + str(preparation_id),
                        self.demand_input(connection, actor, binding, report.document_id),
                    )
                    MaterialIntakeWorkflow.require_scope(connection, actor, demand)
                    job = intake.prepare_revision(
                        actor, seed["session_digest"], demand.id,
                        report.document_id, report.candidate_revision,
                    )
                    updates.transition(
                        preparation_id, "queued", "candidate_preparation_pending",
                        demand_id=demand.id, job_id=job.id,
                    )
                    return
                job = intake.job(actor, row["job_id"])
                if job.state != "ready":
                    status = (
                        job.state if job.state in {"waiting_config", "blocked_unknown"}
                        else "cancelled" if job.state == "cancelled"
                        else "waiting_dependency" if job.issues
                        else "queued"
                    )
                    updates.transition(
                        preparation_id, status, job.reason_code or "candidate_preparation_pending"
                    )
                    return
                if not row["search_id"]:
                    demand = intake.demand(actor, row["demand_id"])
                    search_input = MaterialSearchInput(
                        demand_id=demand.id, expected_demand_revision=demand.revision,
                        query="complete exact candidate ranges", mode="lexical",
                        document_id=report.document_id, document_revision=report.candidate_revision,
                        required_refs=required_refs,
                    )
                    session_digest = seed["session_digest"]
                else:
                    search = MaterialSearchWorkflow(
                        self.database, self.settings
                    ).get_in(connection, actor, row["search_id"])
                    if search.status != "ready":
                        status = (
                            search.status if search.status in {
                                "waiting_config", "waiting_dependency",
                                "blocked_unknown", "cancelled",
                            } else "queued"
                        )
                        updates.transition(
                            preparation_id, status,
                            search.error_code or "candidate_selection_pending",
                        )
                        return
                    self.publish_in(
                        connection, actor, row, binding, report, search.selection_id
                    )
            if search_input:
                search = MaterialSearchWorkflow(self.database, self.settings).submit_digest(
                    session_digest, "material-update:" + str(preparation_id), search_input
                )
                with self.database.transaction() as connection:
                    actor = Identity(
                        PgIdentityStore(connection, serialize_actor=True)
                    ).authenticate_digest(session_digest)
                    updates = MaterialUpdates(connection)
                    seed = updates.seed(preparation_id)
                    row = updates.preparation(actor, seed["check_id"], lock=True)
                    self.current(connection, actor, seed["check_id"])
                    if row["status"] not in {"ready", "cancelled"}:
                        updates.transition(
                            preparation_id, "queued", "candidate_selection_pending",
                            search_id=search.id,
                        )
        except BusinessError as error:
            with self.database.transaction() as connection:
                updates = MaterialUpdates(connection)
                seed = updates.seed(preparation_id)
                if not seed:
                    return
                # The transition preserves the original child operation and UNKNOWN fact.
                status = (
                    "cancelled" if error.code in {
                        "stale_version", "source_not_current", "unauthenticated", "session_expired",
                    } else "waiting_config" if error.code == "model_unavailable"
                    else "blocked_unknown" if error.code == "external_result_unknown"
                    else "waiting_dependency"
                )
                row = updates.status(preparation_id)
                if row and row["status"] not in {"ready", "cancelled"}:
                    updates.transition(preparation_id, status, error.code)

    def decide(self, token, offer_id, key, data: MaterialUpdateDecisionInput):
        with self.database.transaction() as connection:
            actor = Identity(
                PgIdentityStore(connection, serialize_actor=True)
            ).authenticate(token)
            offer = self.offer_in(connection, actor, offer_id)
            decisions = MaterialUpdateDecisions(connection)
            previous = decisions.replay(actor, offer_id, key, data)
            if previous:
                return previous
            report, _review, binding = self.current(
                connection, actor, offer.check_id, data.expected_binding_revision
            )
            updates = MaterialUpdates(connection)
            row = updates.offer_row(actor, offer_id)
            refs = [MaterialRef(**r) for r in row["successor_refs"]]
            if data.decision == "accept_update":
                candidate = updates.candidate_refs(
                    actor, binding, report, offer.candidate_selection_id
                )
                if [ref_key(r) for r in candidate] != [ref_key(r) for r in offer.candidate_refs]:
                    raise BusinessError("stale_version", "Prepared candidate scope changed.")
                Materials(connection).read_refs(actor, binding.goal_id, binding.purpose, refs)
            decision = decisions.decide(actor, offer, binding, key, data, refs)
            if data.decision == "accept_update":
                from leornian.modules.learning.material_repreparations import (
                    LearningMaterialRepreparations,
                )

                LearningMaterialRepreparations(connection).enqueue(
                    actor, decision.id, Identity.digest(token)
                )
            Notifications(connection).decision(actor, offer.id, data.decision)
            Events(connection).append(
                actor.id, "learning.material_update_decided", decision.id,
                EventPayload(
                    goal_id=binding.goal_id, material_update_offer_id=offer.id,
                    material_update_decision_id=decision.id,
                ),
            )
            return decision

    def decision_receipt(self, token, offer_id, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return MaterialUpdateDecisions(connection).get(actor, offer_id, key)
