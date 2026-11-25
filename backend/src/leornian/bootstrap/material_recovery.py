from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.platform.material_models import MaterialModelGateway
from leornian.platform.material_search_configuration import MaterialSearchConfiguration
from leornian.platform.models import MaterialProbeConfiguration, UserModels
from leornian.platform.tavily import TavilyGateway
from leornian.shared_kernel.contracts import Contract
from leornian.shared_kernel.errors import BusinessError


class MaterialRecoveryResult(Contract):
    repaired_steps: int
    message: str


class MaterialRecoveryWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def repair(self, token, conversation_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            conversation = Tutor(PgTutorStore(connection)).get(actor, conversation_id, lock=True)
            turn = next((
                turn for turn in reversed(PgTutorStore(connection).turns(conversation.id))
                if turn.purpose == "planning" and turn.material_demand_id
            ), None)
            if turn is None:
                raise BusinessError("precondition_failed", "当前没有需要修复的资料任务。")
            intake = MaterialIntake(connection)
            demand = intake.demand(actor, turn.material_demand_id)
            MaterialIntakeWorkflow.require_scope(connection, actor, demand)
            discovery = MaterialSources(connection).discovery(actor, demand.id, demand.revision)
            if not discovery:
                raise BusinessError("precondition_failed", "资料任务尚未建立，请重新发起制定计划。")
            observations = connection.execute(
                "SELECT DISTINCT o.* FROM knowledge.source_observations o "
                "WHERE o.actor_id=%s AND EXISTS("
                "SELECT 1 FROM knowledge.material_source_check_commands c "
                "JOIN knowledge.source_observations selected ON selected.id=c.observation_id "
                "WHERE selected.resource_id=o.resource_id AND c.command_key LIKE %s) "
                "AND o.status IN ('waiting_dependency','waiting_config','blocked_unknown')",
                (actor.id, f"discovery:{discovery.id}:shallow-v1:%"),
            ).fetchall()
            affected_jobs = [o["job_id"] for o in observations if o["job_id"]]
            if demand.preparation == "complete":
                affected_jobs.extend(
                    job.id for job in intake.pending_goal_uploads(actor, demand.goal_id)
                )
            jobs = connection.execute(
                "SELECT DISTINCT j.* FROM knowledge.material_jobs j "
                "WHERE j.actor_id=%s AND (j.demand_id=%s OR j.id=ANY(%s::uuid[]) OR EXISTS("
                "SELECT 1 FROM knowledge.material_searches s,"
                "jsonb_array_elements(s.request->'source_versions') v WHERE s.id=%s "
                "AND v->>'document_id'=j.document_id::text "
                "AND (v->>'document_revision')::int=j.document_revision)) "
                "AND j.state IN ('waiting_dependency','waiting_config','blocked_unknown')",
                (actor.id, demand.id, affected_jobs,
                 connection.execute(
                     "SELECT search_id FROM knowledge.material_discovery_jobs WHERE id=%s",
                     (discovery.id,),
                 ).fetchone()["search_id"]),
            ).fetchall()
            repaired = 0
            for observation in observations:
                web = connection.execute(
                    "SELECT w.id,c.status FROM knowledge.material_web_requests w "
                    "JOIN runtime.external_calls c ON c.operation_ref=w.id "
                    "WHERE w.observation_id=%s AND NOT w.retired", (observation["id"],),
                ).fetchone()
                if web and web["status"] in {"unknown", "dispatching"}:
                    raise BusinessError(
                        "unknown_unresolved", "页面提取结果未知，必须先核对原回执，不能直接重试。",
                    )
                if web and web["status"] == "prepared":
                    call = Runs(connection).operation(web["id"])
                    if MaterialSearchConfiguration(connection, self.settings).binding(actor) != (
                        call.context_manifest["configuration"]
                    ):
                        connection.execute(
                            "UPDATE knowledge.material_web_requests SET retired=true WHERE id=%s",
                            (web["id"],),
                        )
                        connection.execute(
                            "UPDATE knowledge.source_observations SET status='queued',"
                            "published_at=NULL,error_code=NULL WHERE id=%s", (observation["id"],),
                        )
                        repaired += 1
                        continue
                if web and web["status"] == "result_recorded" and observation["error_code"] in {
                    "external_result_unknown", "tavily_configuration_changed",
                }:
                    connection.execute(
                        "UPDATE knowledge.source_observations SET status='queued',"
                        "dispatched_at=NULL,error_code=NULL,published_at=NULL WHERE id=%s",
                        (observation["id"],),
                    )
                    repaired += 1
                    continue
                if observation["error_code"] in {
                    "tavily_extraction_failed", "tavily_invalid_response",
                    "tavily_provider_rejected",
                }:
                    # Change the failed acquisition strategy, not the successful document pipeline.
                    connection.execute(
                        "UPDATE knowledge.material_source_resources "
                        "SET acquisition_provider='direct' "
                        "WHERE id=%s", (observation["resource_id"],),
                    )
                    connection.execute(
                        "UPDATE knowledge.source_observations SET status='cancelled' WHERE id=%s",
                        (observation["id"],),
                    )
                    MaterialSources(connection).schedule(
                        actor, observation["source_id"], Identity.digest(token),
                        f"repair-direct:{observation['id']}",
                        resource_id=observation["resource_id"],
                    )
                    repaired += 1
                elif observation["error_code"] in {
                    "tavily_not_configured", "tavily_configuration_changed",
                }:
                    MaterialSearchConfiguration(connection, self.settings).binding(actor)
                    connection.execute(
                        "UPDATE knowledge.source_observations SET status='queued',"
                        "error_code=NULL,published_at=NULL WHERE id=%s", (observation["id"],),
                    )
                    repaired += 1
                elif observation["error_code"] in {
                    "source_http_unavailable", "source_read_unknown",
                } and observation["response_status"] in {408, 429, 502, 503, 504}:
                    connection.execute(
                        "UPDATE knowledge.source_observations SET status='cancelled' WHERE id=%s",
                        (observation["id"],),
                    )
                    MaterialSources(connection).schedule(
                        actor, observation["source_id"], Identity.digest(token),
                        f"repair-read:{observation['id']}", resource_id=observation["resource_id"],
                    )
                    repaired += 1
            for job in jobs:
                if job["state"] == "waiting_config" and job["phase"] in {"ocr", "indexing"}:
                    role = "ocr" if job["phase"] == "ocr" else "embedding"
                    models = UserModels(connection, self.settings)
                    models.resolve_material(actor, models.binding(actor, role))
                calls = connection.execute(
                    "SELECT o.id,o.purpose,o.binding,c.status,c.http_status,c.applied "
                    "FROM knowledge.material_operations o JOIN runtime.external_calls c "
                    "ON c.operation_ref=o.id WHERE o.job_id=%s AND NOT o.retired", (job["id"],),
                ).fetchall()
                for operation in calls:
                    self.repair_operation(
                        connection, actor, operation, "knowledge.material_operations",
                    )
                if job["issues"] and connection.execute(
                    "SELECT id FROM knowledge.material_repair_attempts WHERE job_id=%s "
                    "AND state IN ('waiting','superseded') LIMIT 1", (job["id"],),
                ).fetchone():
                    raise BusinessError(
                        "precondition_failed",
                        "已有解析修复未取得进展，请更换可读取的资料或补充来源。",
                    )
                intake.transition(
                    job["id"], "waiting_dependency", job["phase"],
                    reason=job["reason_code"], issues=job["issues"],
                )
                connection.execute(
                    "UPDATE knowledge.material_jobs SET published_at=NULL WHERE id=%s",
                    (job["id"],),
                )
                repaired += 1
            web_calls = connection.execute(
                "SELECT w.id,c.status,c.context_manifest,c.http_status "
                "FROM knowledge.material_web_requests w JOIN runtime.external_calls c "
                "ON c.operation_ref=w.id WHERE w.discovery_id=%s AND NOT w.retired",
                (discovery.id,),
            ).fetchall()
            for call in web_calls:
                if call["status"] in {"unknown", "dispatching"}:
                    raise BusinessError("unknown_unresolved", "教材搜索结果未知，请先核对原回执。")
                if call["status"] == "failed_known":
                    binding = MaterialSearchConfiguration(connection, self.settings).binding(actor)
                    if binding == call["context_manifest"]["configuration"] and call[
                        "http_status"
                    ] not in {408, 429}:
                        raise BusinessError(
                            "precondition_failed", "请先修正 Tavily Key 或授权，再修复教材搜索。",
                        )
                    connection.execute(
                        "UPDATE knowledge.material_web_requests SET retired=true WHERE id=%s",
                        (call["id"],),
                    )
                    repaired += 1
                elif call["status"] == "prepared":
                    binding = MaterialSearchConfiguration(connection, self.settings).binding(actor)
                    if binding != call["context_manifest"]["configuration"]:
                        connection.execute(
                            "UPDATE knowledge.material_web_requests SET retired=true WHERE id=%s",
                            (call["id"],),
                        )
                    repaired += 1
                elif call["status"] == "result_recorded" and discovery.error_code == (
                    "tavily_invalid_response"
                ):
                    # Use the approved direct entry after a known malformed search response.
                    connection.execute(
                        "UPDATE knowledge.material_web_requests SET applied=true WHERE id=%s",
                        (call["id"],),
                    )
                    Runs(connection).applied(Runs(connection).operation(call["id"]).id)
                    repaired += 1
                elif call["status"] == "result_recorded":
                    recorded = Runs(connection).operation(call["id"])
                    if not recorded.applied:
                        try:
                            TavilyGateway.result(recorded.response_body)
                        except (ValueError, TypeError):
                            raise BusinessError(
                                "precondition_failed", "教材搜索回执无效，需切换原站获取策略。",
                            ) from None
                        repaired += 1
            search_id = connection.execute(
                "SELECT search_id FROM knowledge.material_discovery_jobs WHERE id=%s",
                (discovery.id,),
            ).fetchone()["search_id"]
            for operation in connection.execute(
                "SELECT o.*,c.status AS call_status,c.http_status FROM "
                "knowledge.material_search_operations o JOIN runtime.external_calls c "
                "ON c.operation_ref=o.id WHERE o.search_id=%s AND NOT o.retired",
                (search_id,),
            ).fetchall():
                if self.repair_operation(
                    connection, actor, operation, "knowledge.material_search_operations",
                ):
                    repaired += 1
            if search_id and repaired:
                connection.execute(
                    "UPDATE knowledge.material_searches SET status='queued',error_code=NULL,"
                    "published_at=NULL WHERE id=%s AND status<>'ready'", (search_id,),
                )
            if not repaired:
                # A changed model/key can resume a recorded receipt; no new call is made here.
                if discovery.status == "blocked_unknown":
                    raise BusinessError("unknown_unresolved", "资料处理结果未知，请先核对原回执。")
                if discovery.status == "waiting_config" and discovery.error_code in {
                    "tavily_not_configured", "tavily_configuration_changed",
                }:
                    MaterialSearchConfiguration(connection, self.settings).binding(actor)
                elif discovery.status == "waiting_config" and discovery.error_code in {
                    "model_unavailable", "provider_configuration_changed",
                }:
                    models = UserModels(connection, self.settings)
                    for role in ("embedding", "rerank"):
                        models.resolve_material(actor, models.binding(actor, role))
                elif discovery.error_code in {
                    "approved_source_required", "approved_source_coverage_gap",
                }:
                    from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

                    row = connection.execute(
                        "SELECT * FROM knowledge.material_discovery_jobs WHERE id=%s",
                        (discovery.id,),
                    ).fetchone()
                    MaterialDiscoveryWorkflow(self.database, self.settings).acquire(
                        connection, actor, row, demand,
                        discovery.missing_facets or [demand.goal_text],
                    )
                    recovered = MaterialSources(connection).discovery(
                        actor, demand.id, demand.revision,
                    )
                    if recovered.status != "queued":
                        raise BusinessError(
                            "precondition_failed",
                            "当前已授权来源仍无可用的补充章节，请核对来源范围。",
                        )
                    repaired += 1
                elif discovery.status == "ready":
                    repaired += 1
                else:
                    raise BusinessError(
                        "precondition_failed",
                        "暂无可执行的新修复策略。请按正文补充资料或修正配置后继续，"
                        "不会重复发送原请求。",
                    )
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET status='queued',error_code=NULL,"
                "next_run_at=now(),published_at=NULL,session_digest=%s WHERE id=%s",
                (Identity.digest(token), discovery.id),
            )
            if turn.planning_state and turn.planning_state.material_blocked:
                run_id = Runs(connection).turn_run_ids(actor.id, conversation.id).get(turn.id)
                deliveries = Deliveries(connection)
                task = deliveries.for_run(run_id) if run_id else None
                if task and task["status"] == "waiting_input" and not task["cancel_requested"]:
                    deliveries.await_route_materials(task["id"], demand, turn_id=turn.id)
                    deliveries.state(task["id"], "waiting_dependency")
            return MaterialRecoveryResult(
                repaired_steps=repaired, message="已诊断并恢复受影响步骤，已完成资料保留。",
            )

    def repair_operation(self, connection, actor, operation, table):
        call = Runs(connection).operation(operation["id"])
        if call.status in {"unknown", "dispatching"}:
            raise BusinessError("unknown_unresolved", "资料模型调用结果未知，请先核对原回执。")
        if call.applied:
            return False
        binding = UserModels(connection, self.settings).binding(actor, operation["purpose"])
        changed = binding != operation["binding"]
        retire = call.status == "prepared" and changed
        if call.status == "failed_known":
            if not changed and call.http_status not in {408, 429}:
                raise BusinessError(
                    "precondition_failed", "原请求被明确拒绝，请先修正模型配置后再修复。",
                )
            retire = True
        if call.status == "result_recorded":
            try:
                MaterialModelGateway(
                    MaterialProbeConfiguration(
                        **call.context_manifest["configuration"], api_key="",
                    ),
                ).result(call.response_body, call.request)
            except ModelProtocolError:
                if not changed:
                    raise BusinessError(
                        "precondition_failed",
                        "原模型回执未通过格式或完整性校验，请修正模型配置或补充资料后再修复。",
                    ) from None
                retire = True
        if retire:
            connection.execute(f"UPDATE {table} SET retired=true WHERE id=%s", (operation["id"],))
        return retire or call.status in {"prepared", "result_recorded"}
