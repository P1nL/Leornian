from datetime import UTC, datetime
from uuid import uuid4

from leornian.modules.execution.environment_contracts import (
    EngineState,
    EnvironmentDecision,
    EnvironmentDecisionInput,
    EnvironmentDemand,
    EnvironmentPreparationClaim,
    EnvironmentRelease,
    EnvironmentRequirement,
    ExecutionEnvironments,
)
from leornian.modules.execution.environment_recipes import (
    automatic_recipe_ids,
    course_recipe,
    recipe,
    requirements,
)
from leornian.modules.identity.contracts import Actor
from leornian.shared_kernel.errors import BusinessError
from psycopg.types.json import Jsonb

SCOPE = "this-device.v1"


class Environments:
    """Own local preparation consent, immutable releases and their actual-use gate."""

    def __init__(self, connection):
        self.connection = connection

    def _lock(self, actor_id):
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("execution-environments:" + str(actor_id),),
        )

    def _row(self, actor, demand_id):
        row = self.connection.execute(
            "SELECT * FROM execution.environment_demands WHERE id=%s AND actor_id=%s",
            (demand_id, actor.id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Local environment demand not found.")
        return row

    def get(self, actor, demand_id):
        row = self._row(actor, demand_id)
        release = None
        if row["release_id"]:
            value = self.connection.execute(
                "SELECT * FROM execution.environment_releases WHERE id=%s",
                (row["release_id"],),
            ).fetchone()
            release = self._release(value)
        job = self.connection.execute(
            "SELECT error_code FROM execution.environment_preparation_jobs WHERE demand_id=%s "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (demand_id,),
        ).fetchone()
        return EnvironmentDemand(
            **{
                key: row[key]
                for key in EnvironmentDemand.model_fields
                if key not in {"release", "error_code"}
            },
            release=release,
            error_code=job["error_code"] if job else None,
        )

    @staticmethod
    def _release(row):
        return EnvironmentRelease(**{key: row[key] for key in EnvironmentRelease.model_fields})

    @staticmethod
    def _decision(row):
        return EnvironmentDecision(
            **{key: row[key] for key in EnvironmentDecision.model_fields
               if key != "authorization_basis"},
            authorization_basis=row["command"].get("authorization_basis", "user"),
        )

    @staticmethod
    def route_requirements(recipe_ids, course_environments=()):
        base_ids = [
            *recipe_ids,
            *[f"{course.language}-standard.v1" for course in course_environments],
            *(["html-css-browser.v1"] if any(
                course.build == "vite" for course in course_environments
            ) else []),
        ]
        return [
            *[recipe(key).requirement for key in dict.fromkeys(base_ids)],
            *[course_recipe(course).requirement for course in course_environments],
        ]

    @staticmethod
    def same_requirement(left, right):
        if isinstance(left, dict):
            left = EnvironmentRequirement.model_validate(left)
        if isinstance(right, dict):
            right = EnvironmentRequirement.model_validate(right)
        return left.installation_scope() == right.installation_scope()

    @staticmethod
    def satisfies_base(demand, requirement):
        if requirement.recipe_id not in automatic_recipe_ids() or demand.decision != "allow":
            return False
        existing = demand.requirement
        return (
            (existing.profile, existing.language, existing.dialect)
            == (requirement.profile, requirement.language, requirement.dialect)
            and recipe(existing.recipe_id, existing.course_environment).base_image
            == recipe(requirement.recipe_id, requirement.course_environment).base_image
            and set(requirement.dependency_lock) <= set(existing.dependency_lock)
        )

    def snapshot(self, actor):
        engine = self.connection.execute(
            "SELECT * FROM execution.environment_engine_observations WHERE local_scope=%s",
            (SCOPE,),
        ).fetchone()
        connected = engine and (datetime.now(UTC) - engine["observed_at"]).total_seconds() <= 45
        state = EngineState(
            status=engine["status"] if connected else "not_connected",
            version=engine["version"] if engine else None,
            operating_system=engine["operating_system"] if engine else None,
            detail=engine["detail"]
            if connected
            else ("本机控制器尚未连接；在应用的本机服务中启动后重新检查。"),
            observed_at=engine["observed_at"] if engine else None,
        )
        rows = self.connection.execute(
            "SELECT id FROM execution.environment_demands WHERE actor_id=%s ORDER BY created_at,id",
            (actor.id,),
        ).fetchall()
        return ExecutionEnvironments(
            engine=state,
            recipes=requirements(),
            demands=[self.get(actor, row["id"]) for row in rows],
            automatic_recipe_ids=automatic_recipe_ids(),
        )

    def _command_receipt(self, actor, key, operation, command=None, demand_id=None):
        row = self.connection.execute(
            "SELECT * FROM execution.environment_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if row is None:
            return None
        if (
            row["operation"] != operation
            or command is not None
            and row["command"] != command
            or demand_id is not None
            and row["demand_id"] != demand_id
        ):
            raise BusinessError("idempotency_conflict", "Environment command key was reused.")
        return EnvironmentDemand.model_validate(row["receipt"])

    def _record_command(self, actor, key, operation, command, demand):
        self.connection.execute(
            "INSERT INTO execution.environment_commands(actor_id,command_key,operation,demand_id,"
            "command,receipt) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                actor.id,
                key,
                operation,
                demand.id,
                Jsonb(command),
                Jsonb(demand.model_dump(mode="json")),
            ),
        )
        return demand

    def request_receipt(self, actor, key):
        receipt = self._command_receipt(actor, key, "request")
        if receipt is None:
            raise BusinessError("not_found", "Environment request receipt not found.")
        return receipt

    def recorded_request(self, actor, key, data):
        return self._command_receipt(actor, key, "request", data.model_dump(mode="json"))

    def recorded_rebuild(self, actor, demand_id, key, data):
        return self._command_receipt(
            actor,
            key,
            "rebuild",
            {"demand_id": str(demand_id), **data.model_dump(mode="json")},
            demand_id,
        )

    def recorded_decision(self, actor, demand_id, key, data):
        row = self.connection.execute(
            "SELECT * FROM execution.environment_install_decisions "
            "WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if row is None:
            return None
        if row["command"] != {"demand_id": str(demand_id), **data.model_dump(mode="json")}:
            raise BusinessError("idempotency_conflict", "Installation decision key was reused.")
        return self._decision(row)

    def request(self, actor, key, data):
        self._lock(actor.id)
        command = data.model_dump(mode="json")
        receipt = self._command_receipt(actor, key, "request", command)
        if receipt:
            return receipt
        maintained = recipe(data.recipe_id, data.course_environment)
        requirement = maintained.requirement
        payload = requirement.model_dump(mode="json")
        row = self.connection.execute(
            "SELECT * FROM execution.environment_demands WHERE actor_id=%s AND local_scope=%s "
            "AND plan_id IS NOT DISTINCT FROM %s AND profile=%s AND language=%s AND dialect=%s",
            (
                actor.id,
                SCOPE,
                data.plan_id,
                requirement.profile,
                requirement.language,
                requirement.dialect or "",
            ),
        ).fetchone()
        inherited = None
        if row is None:
            if data.expected_requirement_revision != 0:
                raise BusinessError("stale_version", "This environment requirement does not exist.")
            demand_id = uuid4()
            self.connection.execute(
                "INSERT INTO execution.environment_demands(id,actor_id,local_scope,plan_id,"
                "plan_revision,profile,language,dialect,requirement) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    demand_id,
                    actor.id,
                    SCOPE,
                    data.plan_id,
                    data.plan_revision,
                    requirement.profile,
                    requirement.language,
                    requirement.dialect or "",
                    Jsonb(payload),
                ),
            )
        else:
            demand_id = row["id"]
            unchanged = (
                self.same_requirement(row["requirement"], requirement)
                and row["plan_revision"] == data.plan_revision
            )
            if data.expected_requirement_revision != row["requirement_revision"] and not (
                unchanged and data.expected_requirement_revision == 0
            ):
                raise BusinessError("stale_version", "The environment requirement changed.")
            if not unchanged and row["status"] == "blocked_unknown":
                raise BusinessError(
                    "precondition_failed", "Resolve the original environment preparation first.",
                )
            if not unchanged:
                if (
                    self.same_requirement(row["requirement"], requirement)
                    and row["decision"] == "allow"
                ):
                    inherited = self.connection.execute(
                        "SELECT id FROM execution.environment_install_decisions "
                        "WHERE demand_id=%s AND revision=%s",
                        (demand_id, row["decision_revision"]),
                    ).fetchone()
                stopped = row["decision"] in {"defer", "decline", "revoke"}
                self.connection.execute(
                    "UPDATE execution.environment_demands SET requirement_revision="
                    "requirement_revision+1,requirement=%s,plan_revision=%s,decision=%s,"
                    "status=%s,release_id=NULL,updated_at=now() WHERE id=%s",
                    (
                        Jsonb(payload), data.plan_revision,
                        row["decision"] if stopped else None,
                        {"defer": "deferred", "decline": "declined", "revoke": "revoked"}.get(
                            row["decision"], "waiting_authorization",
                        ),
                        demand_id,
                    ),
                )
                self._cancel_jobs(demand_id)
        current = self.get(actor, demand_id)
        if current.decision is None and (
            not maintained.requires_consent or inherited
        ):
            basis = "reused_consent" if inherited else "managed_base"
            self._decide(
                actor,
                demand_id,
                f"{basis}:{demand_id}:{current.requirement_revision}",
                EnvironmentDecisionInput(
                    expected_requirement_revision=current.requirement_revision,
                    expected_decision_revision=current.decision_revision,
                    decision="allow",
                ),
                authorization_basis=basis,
                inherited_from=str(inherited["id"]) if inherited else None,
            )
        return self._record_command(actor, key, "request", command, self.get(actor, demand_id))

    def _cancel_jobs(self, demand_id):
        self.connection.execute(
            "UPDATE execution.environment_preparation_jobs SET status='cancelled',"
            "error_code='environment_authorization_changed' WHERE demand_id=%s "
            "AND status IN ('queued','waiting_engine','preparing','verifying')",
            (demand_id,),
        )

    def _queue(self, actor, row):
        job_id = uuid4()
        self.connection.execute(
            "INSERT INTO execution.environment_preparation_jobs(id,demand_id,actor_id,"
            "requirement_revision,decision_revision,requirement) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                job_id,
                row["id"],
                actor.id,
                row["requirement_revision"],
                row["decision_revision"],
                Jsonb(row["requirement"]),
            ),
        )
        self.connection.execute(
            "UPDATE execution.environment_demands SET status='queued',updated_at=now() WHERE id=%s",
            (row["id"],),
        )
        return job_id

    def decide(self, actor, demand_id, key, data):
        return self._decide(actor, demand_id, key, data)

    def _decide(
        self, actor, demand_id, key, data, *, authorization_basis="user", inherited_from=None,
    ):
        self._lock(actor.id)
        command = {"demand_id": str(demand_id), **data.model_dump(mode="json")}
        if authorization_basis != "user":
            command["authorization_basis"] = authorization_basis
            if inherited_from:
                command["inherited_from"] = inherited_from
        old = self.connection.execute(
            "SELECT * FROM execution.environment_install_decisions "
            "WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if old:
            if old["command"] != command:
                raise BusinessError("idempotency_conflict", "Installation decision key was reused.")
            return self._decision(old)
        row = self._row(actor, demand_id)
        if (
            row["requirement_revision"] != data.expected_requirement_revision
            or row["decision_revision"] != data.expected_decision_revision
        ):
            raise BusinessError("stale_version", "Environment requirement or decision changed.")
        decision = self.connection.execute(
            "INSERT INTO execution.environment_install_decisions(id,actor_id,demand_id,"
            "requirement_revision,revision,decision,command_key,command,requirement) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4(),
                actor.id,
                demand_id,
                row["requirement_revision"],
                row["decision_revision"] + 1,
                data.decision,
                key,
                Jsonb(command),
                Jsonb(row["requirement"]),
            ),
        ).fetchone()
        status = {
            "allow": "queued",
            "defer": "deferred",
            "decline": "declined",
            "revoke": "revoked",
        }[data.decision]
        if data.decision == "allow" and row["decision"] == "allow" and row["status"] == "ready":
            status = "ready"
        self._cancel_jobs(demand_id)
        self.connection.execute(
            "UPDATE execution.environment_demands SET decision=%s,decision_revision=%s,status=%s,"
            "updated_at=now() WHERE id=%s",
            (data.decision, decision["revision"], status, demand_id),
        )
        if status == "queued":
            self._queue(actor, self._row(actor, demand_id))
        return self._decision(decision)

    def decision_receipt(self, actor, demand_id, key):
        row = self.connection.execute(
            "SELECT * FROM execution.environment_install_decisions WHERE actor_id=%s "
            "AND demand_id=%s AND command_key=%s",
            (actor.id, demand_id, key),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Environment decision receipt not found.")
        return self._decision(row)

    def rebuild_receipt(self, actor, demand_id, key):
        receipt = self._command_receipt(actor, key, "rebuild", demand_id=demand_id)
        if receipt is None:
            raise BusinessError("not_found", "Environment rebuild receipt not found.")
        return receipt

    def rebuild(self, actor, demand_id, key, data):
        self._lock(actor.id)
        command = {"demand_id": str(demand_id), **data.model_dump(mode="json")}
        receipt = self._command_receipt(actor, key, "rebuild", command, demand_id)
        if receipt:
            return receipt
        row = self._row(actor, demand_id)
        if (
            row["requirement_revision"] != data.expected_requirement_revision
            or row["decision_revision"] != data.expected_decision_revision
        ):
            raise BusinessError("stale_version", "The environment authorization changed.")
        if row["decision"] != "allow":
            raise BusinessError("precondition_failed", "Allow this requirement before rebuilding.")
        active = self.connection.execute(
            "SELECT id FROM execution.environment_preparation_jobs WHERE demand_id=%s "
            "AND status IN ('queued','waiting_engine','preparing','verifying')",
            (demand_id,),
        ).fetchone()
        if not active:
            self._queue(actor, row)
        return self._record_command(
            actor,
            key,
            "rebuild",
            command,
            self.get(actor, demand_id),
        )

    def observe_engine(self, data):
        self.connection.execute(
            "INSERT INTO execution.environment_engine_observations(local_scope,runner_id,status,"
            "version,operating_system,detail) VALUES(%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(local_scope) DO UPDATE SET runner_id=EXCLUDED.runner_id,"
            "status=EXCLUDED.status,version=EXCLUDED.version,"
            "operating_system=EXCLUDED.operating_system,detail=EXCLUDED.detail,observed_at=now()",
            (SCOPE, data.runner_id, data.status, data.version, data.operating_system, data.detail),
        )

    def claim_preparation(self, runner_id):
        engine = self.connection.execute(
            "SELECT status FROM execution.environment_engine_observations WHERE local_scope=%s "
            "AND runner_id=%s AND observed_at>now()-interval '45 seconds'",
            (SCOPE, runner_id),
        ).fetchone()
        if engine and engine["status"] == "ready":
            self.retry_downloads()
        candidates = self.connection.execute(
            "SELECT id,actor_id FROM execution.environment_preparation_jobs "
            "WHERE status IN ('queued','waiting_engine') ORDER BY created_at,id LIMIT 10"
        ).fetchall()
        for candidate in candidates:
            self._lock(candidate["actor_id"])
            row = self.connection.execute(
                "SELECT j.*,d.decision,d.requirement_revision AS current_revision,"
                "d.decision_revision AS current_decision "
                "FROM execution.environment_preparation_jobs "
                "j JOIN execution.environment_demands d ON d.id=j.demand_id WHERE j.id=%s "
                "AND j.status IN ('queued','waiting_engine') FOR UPDATE OF j",
                (candidate["id"],),
            ).fetchone()
            if row is None:
                continue
            if not self._authorized(row):
                self.connection.execute(
                    "UPDATE execution.environment_preparation_jobs SET status='cancelled' "
                    "WHERE id=%s",
                    (row["id"],),
                )
                continue
            if not engine or engine["status"] != "ready":
                self.connection.execute(
                    "UPDATE execution.environment_preparation_jobs SET status='waiting_engine' "
                    "WHERE id=%s",
                    (row["id"],),
                )
                self._status(row["demand_id"], "waiting_engine")
                continue
            token = uuid4()
            self.connection.execute(
                "UPDATE execution.environment_preparation_jobs SET status='preparing',"
                "phase='downloading',runner_id=%s,claim_token=%s,"
                "lease_until=now()+interval '90 seconds' WHERE id=%s",
                (runner_id, token, row["id"]),
            )
            self._status(row["demand_id"], "preparing")
            return EnvironmentPreparationClaim(
                job_id=row["id"],
                claim_token=token,
                demand_id=row["demand_id"],
                requirement_revision=row["requirement_revision"],
                requirement=row["requirement"],
            )
        return None

    def retry_downloads(self):
        rows = self.connection.execute(
            "SELECT d.id,d.actor_id FROM execution.environment_demands d "
            "WHERE d.status='failed' AND d.decision='allow' AND "
            "(SELECT j.error_code='downloading_failed' AND "
            "j.reported_at<now()-interval '30 seconds' "
            "FROM execution.environment_preparation_jobs j WHERE j.demand_id=d.id "
            "ORDER BY j.created_at DESC,j.id DESC LIMIT 1) LIMIT 10"
        ).fetchall()
        for row in rows:
            self._lock(row["actor_id"])
            actor = Actor(id=row["actor_id"], display_name="")
            current = self._row(actor, row["id"])
            if current["status"] == "failed" and current["decision"] == "allow":
                self._queue(actor, current)

    @staticmethod
    def _authorized(row):
        return (
            row["decision"] == "allow"
            and row["requirement_revision"] == row["current_revision"]
            and row["decision_revision"] == row["current_decision"]
        )

    def _job(self, job_id, claim_token):
        preliminary = self.connection.execute(
            "SELECT actor_id FROM execution.environment_preparation_jobs WHERE id=%s",
            (job_id,),
        ).fetchone()
        if preliminary is None:
            raise BusinessError("not_found", "Environment preparation not found.")
        self._lock(preliminary["actor_id"])
        row = self.connection.execute(
            "SELECT j.*,d.decision,d.requirement_revision AS current_revision,"
            "d.decision_revision AS current_decision,d.plan_id,d.plan_revision,"
            "j.lease_until>now() AS timely "
            "FROM execution.environment_preparation_jobs j JOIN execution.environment_demands d "
            "ON d.id=j.demand_id WHERE j.id=%s FOR UPDATE OF j",
            (job_id,),
        ).fetchone()
        if row["claim_token"] != claim_token:
            raise BusinessError("stale_version", "Environment preparation claim changed.")
        return row

    def preparation_context(self, job_id, claim_token):
        row = self._job(job_id, claim_token)
        return {
            "actor_id": row["actor_id"],
            "plan_id": row["plan_id"],
            "plan_revision": row["plan_revision"],
        }

    def invalidate_preparation(self, job_id, claim_token):
        row = self._job(job_id, claim_token)
        if row["timely"] and row["status"] in {"preparing", "verifying"}:
            self.connection.execute(
                "UPDATE execution.environment_preparation_jobs SET status='cancelled',"
                "error_code='environment_scope_changed' WHERE id=%s",
                (job_id,),
            )
            if self._authorized(row):
                self._status(row["demand_id"], "failed")

    def progress_preparation(self, job_id, data):
        row = self._job(job_id, data.claim_token)
        valid = (
            self._authorized(row)
            and row["timely"]
            and row["status"]
            in {
                "preparing",
                "verifying",
            }
        )
        if not valid:
            return False
        status = "verifying" if data.phase == "verifying" else "preparing"
        self.connection.execute(
            "UPDATE execution.environment_preparation_jobs SET status=%s,phase=%s,"
            "lease_until=now()+interval '90 seconds' WHERE id=%s",
            (status, data.phase, job_id),
        )
        self._status(row["demand_id"], status)
        return True

    def _status(self, demand_id, status):
        self.connection.execute(
            "UPDATE execution.environment_demands SET status=%s,updated_at=now() WHERE id=%s",
            (status, demand_id),
        )

    def report_preparation(self, job_id, data):
        row = self._job(job_id, data.claim_token)
        payload = data.model_dump(mode="json")
        recorded = row["report"] or row["late_report"]
        if recorded:
            if recorded != payload:
                raise BusinessError("idempotency_conflict", "Preparation receipt already recorded.")
            existing = self.connection.execute(
                "SELECT * FROM execution.environment_releases WHERE preparation_id=%s",
                (job_id,),
            ).fetchone()
            return self._release(existing) if existing else None
        current = (
            self._authorized(row)
            and row["timely"]
            and row["status"]
            in {
                "preparing",
                "verifying",
            }
        )
        if not current:
            self.connection.execute(
                "UPDATE execution.environment_preparation_jobs SET late_report=%s WHERE id=%s",
                (Jsonb(payload), job_id),
            )
            return None
        course = row["requirement"].get("course_environment")
        if data.outcome == "ready" and course is not None and (
            data.verification.get("course_environment") != course
            or data.verification.get("dependency_lock") != row["requirement"]["dependency_lock"]
        ):
            raise BusinessError(
                "precondition_failed", "The release must verify the approved course dependencies.",
            )
        self.connection.execute(
            "UPDATE execution.environment_preparation_jobs SET status=%s,report=%s,"
            "error_code=%s,reported_at=now() WHERE id=%s",
            (data.outcome, Jsonb(payload), data.error_code, job_id),
        )
        self._status(row["demand_id"], data.outcome)
        if data.outcome != "ready":
            return None
        requirement = row["requirement"]
        release = self.connection.execute(
            "INSERT INTO execution.environment_releases(id,actor_id,demand_id,preparation_id,"
            "requirement_revision,recipe_id,recipe_revision,profile,language,dialect,runtime_version,"
            "image_id,image_ids,toolchains,verification) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4(),
                row["actor_id"],
                row["demand_id"],
                job_id,
                row["requirement_revision"],
                requirement["recipe_id"],
                requirement["recipe_revision"],
                requirement["profile"],
                requirement["language"],
                requirement["dialect"] or "",
                data.runtime_version,
                data.image_id,
                Jsonb(data.image_ids),
                Jsonb(data.toolchains),
                Jsonb(data.verification),
            ),
        ).fetchone()
        self.connection.execute(
            "UPDATE execution.environment_demands SET release_id=%s WHERE id=%s",
            (release["id"], row["demand_id"]),
        )
        return self._release(release)

    def expire_preparations(self):
        rows = self.connection.execute(
            "SELECT id,actor_id FROM execution.environment_preparation_jobs WHERE "
            "status IN ('preparing','verifying') AND lease_until<now() LIMIT 25"
        ).fetchall()
        for candidate in rows:
            self._lock(candidate["actor_id"])
            row = self.connection.execute(
                "UPDATE execution.environment_preparation_jobs SET status='blocked_unknown',"
                "error_code='preparation_lease_expired' WHERE id=%s "
                "AND status IN ('preparing','verifying') AND lease_until<now() "
                "RETURNING demand_id,requirement_revision,decision_revision",
                (candidate["id"],),
            ).fetchone()
            if row:
                self.connection.execute(
                    "UPDATE execution.environment_demands SET status='blocked_unknown',"
                    "updated_at=now() WHERE id=%s AND requirement_revision=%s "
                    "AND decision_revision=%s "
                    "AND decision='allow'",
                    (row["demand_id"], row["requirement_revision"], row["decision_revision"]),
                )
        return len(rows)

    def require_release(
        self,
        actor,
        release_id,
        *,
        profile,
        language=None,
        dialect=None,
        runtime_version=None,
        plan_id=None,
        plan_revision=None,
    ):
        self._lock(actor.id)
        row = self.connection.execute(
            "SELECT r.*,d.decision,d.status,d.local_scope,d.plan_id,d.plan_revision,"
            "d.requirement_revision AS current_revision,d.release_id AS current_release "
            "FROM execution.environment_releases r JOIN execution.environment_demands d "
            "ON d.id=r.demand_id WHERE r.id=%s AND r.actor_id=%s",
            (release_id, actor.id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Owned local environment release not found.")
        if (
            row["decision"] != "allow"
            or row["status"] != "ready"
            or row["requirement_revision"] != row["current_revision"]
            or row["current_release"] != release_id
            or row["local_scope"] != SCOPE
        ):
            raise BusinessError(
                "precondition_failed",
                "Allow and prepare the current local environment first.",
            )
        if (
            row["profile"] != profile
            or language is not None
            and row["language"] != language
            or dialect is not None
            and row["dialect"] != dialect
            or runtime_version is not None
            and row["runtime_version"] != runtime_version
            or row["plan_id"] is not None
            and (row["plan_id"] != plan_id or row["plan_revision"] != plan_revision)
        ):
            raise BusinessError(
                "stale_version", "The release does not match this route or toolchain."
            )
        return self._release(row)

    def release_context(self, release_id):
        row = self.connection.execute(
            "SELECT r.actor_id,r.demand_id,d.plan_id,d.plan_revision FROM "
            "execution.environment_releases r JOIN execution.environment_demands d "
            "ON d.id=r.demand_id WHERE r.id=%s",
            (release_id,),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Local release not found.")
        return dict(row)

    def unavailable(self, release_id, reason):
        row = self.connection.execute(
            "SELECT * FROM execution.environment_releases WHERE id=%s",
            (release_id,),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Local release not found.")
        self._lock(row["actor_id"])
        actor = Actor(id=row["actor_id"], display_name="")
        demand = self._row(actor, row["demand_id"])
        if demand["release_id"] != release_id or demand["decision"] != "allow":
            return
        active = self.connection.execute(
            "SELECT id FROM execution.environment_preparation_jobs WHERE demand_id=%s "
            "AND status IN ('queued','waiting_engine','preparing','verifying')",
            (row["demand_id"],),
        ).fetchone()
        if not active:
            self._queue(actor, demand)
