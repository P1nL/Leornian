from leornian.modules.execution.environment_contracts import (
    EnvironmentDecisionInput,
    EnvironmentDemandInput,
    RouteEnvironmentManifest,
)
from leornian.modules.execution.environments import Environments
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import Actor
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError


class ExecutionEnvironmentWorkflow:
    def __init__(self, database):
        self.database = database

    def snapshot(self, token):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Environments(connection).snapshot(actor)

    def route_manifest(self, token, plan_id, revision):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            plan = Plans(connection).get(actor, plan_id)
            return self.route_manifest_in(connection, actor, plan, revision)

    @staticmethod
    def route_manifest_in(connection, actor, plan, revision):
        version = next(
            (item for item in (plan.latest, plan.active) if item and item.revision == revision),
            None,
        )
        if version is None:
            raise BusinessError("stale_version", "Read the current route environment list.")
        environments = Environments(connection)
        snapshot = environments.snapshot(actor)
        requirements = environments.route_requirements(
            version.document.environment_recipes, version.document.environment_dependencies,
        )
        automatic = snapshot.automatic_recipe_ids
        demands, consent = [], []
        for requirement in requirements:
            scope = None if requirement.recipe_id in automatic else plan.id
            demand = next(
                (d for d in snapshot.demands if d.plan_id == scope
                 and d.requirement.profile == requirement.profile
                 and d.requirement.language == requirement.language
                 and d.requirement.dialect == requirement.dialect),
                None,
            )
            same = demand and (
                environments.same_requirement(demand.requirement, requirement)
                or requirement.recipe_id in automatic
                and environments.satisfies_base(demand, requirement)
            )
            if demand:
                demands.append(demand)
            if (
                requirement.recipe_id not in automatic and not (same and demand.decision == "allow")
                or demand and demand.decision in {"revoke", "decline", "defer"}
            ):
                consent.append(requirement)
        return RouteEnvironmentManifest(
            plan_id=plan.id,
            plan_revision=revision,
            requirements=requirements,
            automatic_recipe_ids=automatic,
            consent_required=consent,
            demands=demands,
            engine=snapshot.engine,
            gaps=version.document.environment_gaps,
        )

    @classmethod
    def prepare_route_in(cls, connection, actor, plan, approved_requirements=None):
        revision = plan.active.revision
        manifest = cls.route_manifest_in(connection, actor, plan, revision)
        if approved_requirements is not None and approved_requirements != manifest.requirements:
            raise BusinessError(
                "stale_version", "环境清单已变化，请重新查看后再决定安装。",
            )
        environments = Environments(connection)
        snapshot = environments.snapshot(actor)
        for requirement in manifest.requirements:
            automatic = requirement.recipe_id in manifest.automatic_recipe_ids
            scope = None if automatic else plan.id
            previous = next(
                (d for d in snapshot.demands if d.plan_id == scope
                 and d.requirement.profile == requirement.profile
                 and d.requirement.language == requirement.language
                 and d.requirement.dialect == requirement.dialect),
                None,
            )
            if previous and previous.status == "blocked_unknown":
                continue
            if automatic and previous:
                if environments.satisfies_base(previous, requirement):
                    continue
                if approved_requirements is None and previous.decision in {
                    "defer", "decline", "revoke",
                }:
                    continue
            prefix = f"route-environment:{plan.id}:{revision}:{requirement.recipe_id}"
            demand = environments.request(
                actor,
                prefix,
                EnvironmentDemandInput(
                    recipe_id=requirement.recipe_id,
                    course_environment=requirement.course_environment,
                    plan_id=scope,
                    plan_revision=None if automatic else revision,
                    expected_requirement_revision=previous.requirement_revision if previous else 0,
                ),
            )
            # Reading or replaying an old confirmation never reinstates a revoked decision.
            if approved_requirements is not None and demand.decision != "allow":
                environments.decide(
                    actor, demand.id, prefix + ":allow",
                    EnvironmentDecisionInput(
                        decision="allow",
                        expected_requirement_revision=demand.requirement_revision,
                        expected_decision_revision=demand.decision_revision,
                    ),
                )

    @staticmethod
    def _current_plan(connection, actor, plan_id, revision):
        if plan_id:
            plan = Plans(connection).get(actor, plan_id)
            if not plan.active or plan.active.revision != revision:
                raise BusinessError(
                    "stale_version",
                    "Environment requirement needs the confirmed route revision.",
                )

    def request(self, token, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            previous = Environments(connection).recorded_request(actor, key, data)
            if previous:
                return previous
            self._current_plan(connection, actor, data.plan_id, data.plan_revision)
            return Environments(connection).request(actor, key, data)

    def decide(self, token, demand_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            previous = Environments(connection).recorded_decision(actor, demand_id, key, data)
            if previous:
                return previous
            demand = Environments(connection).get(actor, demand_id)
            self._current_plan(connection, actor, demand.plan_id, demand.plan_revision)
            return Environments(connection).decide(actor, demand_id, key, data)

    def rebuild(self, token, demand_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            previous = Environments(connection).recorded_rebuild(actor, demand_id, key, data)
            if previous:
                return previous
            demand = Environments(connection).get(actor, demand_id)
            self._current_plan(connection, actor, demand.plan_id, demand.plan_revision)
            return Environments(connection).rebuild(
                actor,
                demand_id,
                key,
                data,
            )

    def request_receipt(self, token, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Environments(connection).request_receipt(actor, key)

    def decision_receipt(self, token, demand_id, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Environments(connection).decision_receipt(actor, demand_id, key)

    def rebuild_receipt(self, token, demand_id, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Environments(connection).rebuild_receipt(actor, demand_id, key)

    def observe_engine(self, data):
        with self.database.transaction() as connection:
            Environments(connection).observe_engine(data)

    def claim(self, data):
        with self.database.transaction() as connection:
            claim = Environments(connection).claim_preparation(data.runner_id)
            if claim and self._preparation_current(connection, claim.job_id, claim.claim_token):
                return claim
            return None

    @classmethod
    def _preparation_current(cls, connection, job_id, claim_token):
        environments = Environments(connection)
        context = environments.preparation_context(job_id, claim_token)
        try:
            actor = Identity(PgIdentityStore(connection)).get_actor(context["actor_id"])
            cls._current_plan(
                connection, actor, context["plan_id"], context["plan_revision"]
            )
            return True
        except BusinessError:
            environments.invalidate_preparation(job_id, claim_token)
            return False

    def progress(self, job_id, data):
        with self.database.transaction() as connection:
            if not self._preparation_current(connection, job_id, data.claim_token):
                return {"allowed": False}
            return {"allowed": Environments(connection).progress_preparation(job_id, data)}

    def report(self, job_id, data):
        with self.database.transaction() as connection:
            self._preparation_current(connection, job_id, data.claim_token)
            return Environments(connection).report_preparation(job_id, data)

    def unavailable(self, release_id, data):
        with self.database.transaction() as connection:
            Environments(connection).unavailable(release_id, data.reason)
        return {"recorded": True}

    def verify_release(self, release_id, data):
        with self.database.transaction() as connection:
            try:
                owner = Environments(connection).release_context(release_id)
                actor = Actor(id=owner["actor_id"], display_name="")
                self._current_plan(connection, actor, owner["plan_id"], owner["plan_revision"])
                Environments(connection).require_release(
                    actor,
                    release_id,
                    **data.model_dump(),
                    plan_id=owner["plan_id"],
                    plan_revision=owner["plan_revision"],
                )
                return {"allowed": True}
            except BusinessError:
                return {"allowed": False}

    def expire(self):
        with self.database.transaction() as connection:
            return Environments(connection).expire_preparations()
