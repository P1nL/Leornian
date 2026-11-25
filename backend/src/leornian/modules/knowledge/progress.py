import json

from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.progress_contracts import (
    MaterialPreparationDocument,
    MaterialPreparationProgress,
    MaterialPreparationStep,
)
from leornian.modules.knowledge.source_acquisition import MAX_GAP_SOURCE_DEPTH

STAGES = (
    "sources", "acquisition", "parsing", "ocr", "quality", "chunking", "embedding",
    "indexing", "retrieval",
)
WAITS = {"waiting_config", "waiting_dependency", "blocked_unknown", "cancelled"}


class MaterialPreparation:
    def __init__(self, connection):
        self.connection = connection

    def for_demand(self, actor, demand_id):
        demand = MaterialIntake(self.connection).demand(actor, demand_id)
        discovery = self.connection.execute(
            "SELECT id,status,error_code,search_id,selection_id "
            "FROM knowledge.material_discovery_jobs "
            "WHERE actor_id=%s AND demand_id=%s "
            "AND demand_revision=%s",
            (actor.id, demand.id, demand.revision),
        ).fetchone()
        prefix = f"discovery:{discovery['id']}:shallow-v1:%" if discovery else ""
        observations = self.connection.execute(
            "SELECT o.id,o.job_id,o.status,o.error_code,o.recorded_at "
            "FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_registrations s ON s.id=o.source_id "
            "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
            "WHERE o.actor_id=%s AND s.goal_id=%s AND s.admission='allowed' "
            "AND o.status<>'cancelled' AND r.depth<=%s AND (r.depth=0 OR EXISTS("
            "SELECT 1 FROM knowledge.material_source_check_commands c "
            "JOIN knowledge.source_observations chosen ON chosen.id=c.observation_id "
            "WHERE chosen.resource_id=o.resource_id AND c.command_key LIKE %s)) "
            "AND NOT EXISTS(SELECT 1 FROM knowledge.source_observations newer "
            "WHERE newer.resource_id=o.resource_id AND newer.created_at>o.created_at)",
            (actor.id, demand.goal_id, MAX_GAP_SOURCE_DEPTH, prefix),
        ).fetchall()
        required = []
        frozen = False
        if discovery and discovery["status"] == "ready" and discovery["selection_id"]:
            selection = self.connection.execute(
                "SELECT refs FROM knowledge.material_selections WHERE id=%s AND actor_id=%s",
                (discovery["selection_id"], actor.id),
            ).fetchone()
            required = selection["refs"] if selection else []
            frozen = bool(required)
        elif discovery and discovery["search_id"]:
            search = self.connection.execute(
                "SELECT request,status FROM knowledge.material_searches "
                "WHERE id=%s AND actor_id=%s",
                (discovery["search_id"], actor.id),
            ).fetchone()
            request = (search or {}).get("request", {})
            required = request.get("required_refs") or request.get("source_versions") or []
            frozen = bool(required and (
                discovery["status"] == "ready" or (search or {}).get("status") != "ready"
            ))
        jobs = self.connection.execute(
            "SELECT DISTINCT ON (COALESCE(j.document_id,j.upload_id,j.id)) "
            "j.id,j.state,j.phase,j.reason_code,j.issues,"
            "COALESCE(j.document_id,j.upload_id,j.id) AS document_key,"
            "COALESCE(u.specification->'material'->>'title',v.title,'Material') "
            "AS title FROM knowledge.material_jobs j "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "LEFT JOIN knowledge.material_uploads u ON u.id=j.upload_id "
            "LEFT JOIN knowledge.document_versions v ON v.document_id=j.document_id "
            "AND v.revision=j.document_revision "
            "LEFT JOIN knowledge.material_uploads origin ON origin.id=v.upload_id "
            "WHERE j.actor_id=%s AND d.goal_id=%s AND d.status<>'cancelled' "
            "AND j.state<>'cancelled' AND (j.demand_id=%s "
            "OR (%s AND COALESCE(u.source_id,origin.source_id) IS NULL) OR j.id=ANY(%s::uuid[]) "
            "OR EXISTS(SELECT 1 FROM jsonb_to_recordset(%s::jsonb) "
            "AS ref(document_id uuid,document_revision integer) "
            "WHERE ref.document_id=j.document_id AND ref.document_revision=j.document_revision)) "
            "ORDER BY COALESCE(j.document_id,j.upload_id,j.id),"
            "j.document_revision DESC,j.created_at DESC,j.id",
            (actor.id, demand.goal_id, demand.id, demand.preparation == "complete" and not frozen,
             [row["job_id"] for row in observations if row["job_id"]] if not frozen else [],
             json.dumps(required)),
        ).fetchall()
        if frozen:
            observations = [
                item for item in observations if item["job_id"] in {job["id"] for job in jobs}
            ]
        builds = self.connection.execute(
            "SELECT b.job_id,b.state,b.space,count(c.id) AS chunks,"
            "count(c.embedding) AS embedded FROM knowledge.material_index_builds b "
            "LEFT JOIN knowledge.material_chunks c ON c.build_id=b.id "
            "WHERE b.actor_id=%s AND b.job_id=ANY(%s::uuid[]) AND b.state<>'purged' "
            "GROUP BY b.id",
            (actor.id, [row["id"] for row in jobs]),
        ).fetchall()
        checks = None
        if discovery and discovery["search_id"]:
            checks = self.connection.execute(
                "SELECT level,count(*) AS total,"
                "count(*) FILTER (WHERE state='reviewed') AS completed,"
                "max(max(reviewed_at)) OVER () AS last_progress_at "
                "FROM knowledge.material_goal_coverage_parts WHERE search_id=%s "
                "GROUP BY level ORDER BY level DESC LIMIT 1",
                (discovery["search_id"],),
            ).fetchone()
        result = self.summarize(demand.id, discovery, observations, jobs, builds, checks)
        background = self.connection.execute(
            "SELECT count(DISTINCT COALESCE(j.document_id,j.upload_id,j.id)) AS total,"
            "count(DISTINCT COALESCE(j.document_id,j.upload_id,j.id)) "
            "FILTER (WHERE j.state='ready') AS ready FROM knowledge.material_jobs j "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "WHERE j.actor_id=%s AND d.goal_id=%s AND j.state<>'cancelled' "
            "AND COALESCE(j.document_id,j.upload_id,j.id)<>ALL(%s::uuid[])",
            (actor.id, demand.goal_id, [job["document_key"] for job in jobs]),
        ).fetchone()
        progress = self.connection.execute(
            "SELECT max(first_seen) AS last_progress_at FROM ("
            "SELECT min(created_at) AS first_seen FROM knowledge.material_job_steps "
            "WHERE job_id=ANY(%s::uuid[]) GROUP BY job_id,phase,state,reason_code "
            "UNION ALL SELECT max(created_at) FROM knowledge.material_job_steps "
            "WHERE job_id=ANY(%s::uuid[]) "
            "AND reason_code IN ('indexing_pending','ocr_pages_pending')) states",
            ([job["id"] for job in jobs], [job["id"] for job in jobs]),
        ).fetchone()["last_progress_at"]
        timestamps = [
            progress, (checks or {}).get("last_progress_at"),
            *(item["recorded_at"] for item in observations),
        ]
        return result.model_copy(update={
            "preparation": demand.preparation, "goal": demand.goal_text,
            "background_documents": background["total"],
            "background_ready_documents": background["ready"],
            "last_progress_at": max((value for value in timestamps if value), default=None),
        })

    @staticmethod
    def summarize(demand_id, discovery, observations, jobs, builds, checks=None):
        items = []
        documents = []
        for job in jobs:
            rank = {"parsing": 2, "ocr": 3, "checking": 4, "indexing": 5, "validating": 8}[
                job["phase"]
            ]
            if job["state"] == "ready":
                rank = 8
            elif "html_nontext_content_pending" in job.get("issues", []):
                rank = 3
            elif job["phase"] == "indexing":
                indexes = [build for build in builds if build["job_id"] == job["id"]]
                if indexes and all(build["chunks"] for build in indexes):
                    rank = 6
                    if all(
                        build["space"].get("mode") == "lexical"
                        or build["embedded"] == build["chunks"] for build in indexes
                    ):
                        rank = 7
                    if all(build["state"] == "indexed" for build in indexes):
                        rank = 8
            state = job["state"]
            if state == "waiting_dependency" and job["reason_code"] in {
                "indexing_pending", "ocr_pages_pending",
            }:
                state = "processing"
            items.append((rank, state, job["reason_code"]))
            documents.append(MaterialPreparationDocument(
                title=job["title"], state=state, phase=STAGES[rank],
                reason_code=job["reason_code"],
            ))
        for observation in observations:
            if observation["job_id"] or observation["status"] in {
                "changed", "unchanged", "noise_only",
            }:
                continue
            items.append((1, observation["status"], observation["error_code"]))
        if not items:
            items.append((0, (discovery or {}).get("status", "processing"),
                          (discovery or {}).get("error_code")))
        blockers = sorted(
            [item for item in items if item[1] in WAITS],
            key=lambda item: (
                {"blocked_unknown": 0, "waiting_config": 1,
                 "cancelled": 2, "waiting_dependency": 3}[item[1]], item[0],
            ),
        )
        ready = bool(discovery and discovery["status"] == "ready" and not blockers)
        status = "ready" if ready else (
            blockers[0][1] if blockers else (
                discovery["status"] if discovery and discovery["status"] in WAITS else "processing"
            )
        )
        reason = None if ready else (
            blockers[0][2] if blockers else (discovery or {}).get("error_code")
        )
        steps = []
        for index, key in enumerate(STAGES):
            complete = len(items) if ready else sum(rank > index for rank, _, _ in items)
            state = "completed" if complete == len(items) else "pending"
            active = [item for item in items if item[0] == index]
            if active and not ready:
                stage_block = next((item for item in blockers if item[0] == index), None)
                state = {
                    "blocked_unknown": "unknown", "waiting_config": "waiting",
                    "waiting_dependency": "waiting", "cancelled": "cancelled",
                }.get(
                    stage_block[1] if stage_block else (
                        status if index == len(STAGES) - 1 else "processing"
                    ), "running",
                )
            if index == len(STAGES) - 1 and not ready and not any(
                rank < index for rank, _, _ in items
            ):
                state = {
                    "blocked_unknown": "unknown", "waiting_config": "waiting",
                    "waiting_dependency": "waiting", "cancelled": "cancelled",
                }.get(status, "running")
            unit, total, level = "documents", len(items), None
            if key == "embedding":
                vectors = [build for build in builds if build["space"].get("mode") != "lexical"]
                if vectors:
                    unit = "chunks"
                    complete = sum(build["embedded"] for build in vectors)
                    total = sum(build["chunks"] for build in vectors)
            elif key == "retrieval" and checks:
                unit, level = "checks", checks["level"]
                complete, total = checks["completed"], checks["total"]
            steps.append(MaterialPreparationStep(
                key=key, status=state, completed=complete, total=total, unit=unit, level=level,
            ))
        return MaterialPreparationProgress(
            demand_id=demand_id, status=status, reason_code=reason, steps=steps,
            documents=documents,
            current_documents=len(jobs),
            ready_documents=sum(job["state"] == "ready" for job in jobs),
        )

