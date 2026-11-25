"""Assessment's public read facade for committed evidence, including failed attempts."""

from leornian.modules.assessment.evidence_contracts import OwnedEvidence


class AssessmentEvidence:
    def __init__(self, connection, item_context):
        self.connection = connection
        self.item_context = item_context

    def assistance_before(self, actor, pack_id, slot, occurred_at):
        return [
            {**row, "created_at": row["created_at"].isoformat(), "id": str(row["id"])}
            for row in self.connection.execute(
                "SELECT id,assistance_kind,created_at FROM assessment.practice_assistance "
                "WHERE actor_id=%s AND pack_id=%s AND slot=%s AND created_at<=%s "
                "UNION ALL SELECT id,assistance_kind,created_at FROM assessment.practice_hints "
                "WHERE actor_id=%s AND pack_id=%s AND slot=%s AND created_at<=%s "
                "ORDER BY created_at,id",
                (actor.id, pack_id, slot, occurred_at, actor.id, pack_id, slot, occurred_at),
            ).fetchall()
        ]

    def list(self, actor):
        facts = []
        context = self.item_context

        def pack_fact(row, kind, dimension, policy, *, formal=False):
            occurred_at = row.get("completed_at") or row["created_at"]
            pack_id = row.get("pack_id") or row.get("candidate_pack_id")
            if not pack_id:
                return
            slot = row.get("slot") or row.get("candidate_slot")
            provenance = context.for_pack(actor, pack_id)
            submitted_at = row.get("started_at") or row.get("opened_at") or row["created_at"]
            assistance = self.assistance_before(actor, pack_id, slot, submitted_at) if slot else []
            exposure = context.exposure_before(actor, pack_id, slot, submitted_at)
            if formal and row.get("exposures"):
                # Gate's captured exposure snapshot is the authority at admission time.
                exposure = [
                    {"key": fact["key"]} for fact in row["exposures"] if "key" in fact
                ]
            outcome = row.get("status") or (
                "observed" if row.get("correct") is None
                else "passed" if row["correct"] else "not_passed"
            )
            facts.append(OwnedEvidence(
                source_receipt=row["id"], evidence_kind=kind, dimension=dimension,
                outcome=outcome, occurred_at=occurred_at, pack_id=pack_id, slot=slot,
                policy_version=policy, assistance=assistance, exposure=exposure,
                independence="assisted" if assistance else (
                    "independent_gate" if formal and outcome in {"passed", "not_passed"}
                    else "practice"
                ), **provenance,
            ))

        for row in self.connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE actor_id=%s "
            "AND status IN ('passed','not_passed') ORDER BY completed_at,id", (actor.id,),
        ).fetchall():
            dimension = "concept" if row["policy_version"] == "concept-gate.v1" else "execution"
            pack_fact(row, "concept_gate", dimension, row["policy_version"], formal=True)
        for row in self.connection.execute(
            "SELECT * FROM assessment.transfer_checks WHERE actor_id=%s "
            "AND status IN ('passed','not_passed') ORDER BY completed_at,id", (actor.id,),
        ).fetchall():
            pack_fact(row, "new_context_transfer", "transfer", row["policy_version"], formal=True)
        for row in self.connection.execute(
            "SELECT * FROM assessment.choice_results WHERE actor_id=%s ORDER BY created_at,id",
            (actor.id,),
        ).fetchall():
            pack_fact(row, "choice_practice", "concept", "choice-practice.v1")
        for row in self.connection.execute(
            "SELECT * FROM assessment.response_results WHERE actor_id=%s ORDER BY created_at,id",
            (actor.id,),
        ).fetchall():
            pack_fact(row, "response_practice", "concept", row["profile_version"])
        for table in ("python_attempts", "program_attempts"):
            for row in self.connection.execute(
                f"SELECT * FROM assessment.{table} WHERE actor_id=%s AND purpose='training' "
                "AND status IN ('passed','not_passed','error') ORDER BY completed_at,id",
                (actor.id,),
            ).fetchall():
                pack_fact(row, table.removesuffix("s"), "execution", row.get(
                    "policy_version", row.get("comparison_profile", "python-io-attempt.v1"),
                ))
        for row in self.connection.execute(
            "SELECT * FROM assessment.attempts WHERE actor_id=%s "
            "AND status IN ('passed','not_passed','error') ORDER BY completed_at,id", (actor.id,),
        ).fetchall():
            facts.append(OwnedEvidence(
                source_receipt=row["id"], evidence_kind="baseline_execution", dimension="execution",
                outcome=row["status"], occurred_at=row["completed_at"], track_id=row["track_id"],
                item_version=row["item_version"], policy_version="baseline-three-cases.v1",
                independence="practice",
            ))
        return sorted(facts, key=lambda fact: (fact.occurred_at, str(fact.source_receipt)))
