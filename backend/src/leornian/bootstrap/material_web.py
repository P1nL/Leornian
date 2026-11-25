from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.agent_runtime.gateway import DeliveryUnknown
from leornian.agent_runtime.repository import Runs
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.source_acquisition import MaterialSources, identity
from leornian.modules.knowledge.source_candidates import (
    MAX_SEARCH_RESULTS,
    MAX_SEARCH_ROUNDS,
    DiscoveredSourceCatalog,
)
from leornian.modules.knowledge.source_network import (
    SourceResponse,
    approved_source_url,
    canonical_source_url,
)
from leornian.platform.material_search_configuration import MaterialSearchConfiguration
from leornian.platform.tavily import TAVILY_ORIGIN, TavilyGateway
from leornian.shared_kernel.errors import BusinessError


class MaterialWebWorkflow:
    """Targeted public-source acquisition, using the existing durable call journal."""

    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    @staticmethod
    def enabled(connection, actor, settings):
        return MaterialSearchConfiguration(connection, settings).get(actor).enabled

    @staticmethod
    def prepare(connection, actor, settings, action, request, *, discovery=None, observation=None,
                sources=(), public_scope=None):
        binding = MaterialSearchConfiguration(connection, settings).binding(actor)
        identity_data = {"action": action, "request": request, "binding": binding}
        if public_scope is not None:
            identity_data["public_scope"] = public_scope
        fingerprint = identity(identity_data)
        previous = connection.execute(
            "SELECT id FROM knowledge.material_web_requests WHERE actor_id=%s "
            "AND discovery_id IS NOT DISTINCT FROM %s "
            "AND observation_id IS NOT DISTINCT FROM %s AND request_digest=%s AND NOT retired",
            (actor.id, discovery, observation, fingerprint),
        ).fetchone()
        if previous:
            return previous["id"]
        operation = uuid4()
        connection.execute(
            "INSERT INTO knowledge.material_web_requests"
            "(id,actor_id,discovery_id,observation_id,request_digest) VALUES(%s,%s,%s,%s,%s)",
            (operation, actor.id, discovery, observation, fingerprint),
        )
        Runs(connection).prepare_operation(
            actor.id, operation, TAVILY_ORIGIN + "/" + action, request,
            {"timeout_seconds": 75},
            {"operation": "tavily-" + action, "configuration": binding, "sources": list(sources),
             **({"public_scope": public_scope} if public_scope is not None else {})},
        )
        return operation

    def ensure_search(
        self, connection, actor, row, demand, source_ids, missing, *, discover_public=False,
        max_rounds=MAX_SEARCH_ROUNDS, examples=False,
    ):
        if not self.enabled(connection, actor, self.settings):
            return False
        pending = connection.execute(
            "SELECT id FROM knowledge.material_web_requests WHERE actor_id=%s AND discovery_id=%s "
            "AND NOT applied AND NOT retired ORDER BY created_at LIMIT 1",
            (actor.id, row["id"]),
        ).fetchone()
        if pending:
            call = Runs(connection).operation(pending["id"])
            if call.status in {"unknown", "dispatching"}:
                raise BusinessError("external_result_unknown", "原搜索结果未知，不会追加搜索。")
            return call.status in {"prepared", "result_recorded"}
        sources = MaterialSources(connection)
        permissions = []
        for source_id in source_ids:
            source, data = sources.require(actor, source_id, purpose=demand.purpose)
            permissions.append({
                "id": str(source_id), "revision": source["revision"],
                "prefixes": data.allowed_prefixes,
            })
        state = row.get("acquisition_state") or {}
        if state.get("search_rounds", 0) >= max_rounds or state.get("search_disabled"):
            return False
        public_scope = None
        if discover_public:
            from leornian.modules.learning.application import Learning
            from leornian.modules.learning.infrastructure import PgGoalStore

            scope = Learning(PgGoalStore(connection)).get_goal(actor, demand.goal_id).material_scope
            if not scope or not scope.authorized_public_sources:
                raise BusinessError(
                    "source_not_current", "Public discovery is outside goal permission.",
                )
            public_scope = {"goal_id": str(demand.goal_id), "scope": scope.model_dump(mode="json")}
        if not permissions and public_scope is None:
            return False
        query = "\n".join(
            missing or ([demand.goal_text] if demand.goal_text else demand.required_facets),
        )
        if examples:
            query = " ".join(filter(None, [
                demand.language, demand.framework, " / ".join(missing), "代码示例 code example",
            ]))[:380]
        elif discover_public:
            query = "\n".join(filter(None, [
                demand.language, demand.language_version,
                demand.framework, demand.framework_version,
                query, "public tutorial reference examples",
                "alternative sources" if state.get("search_rounds") else None,
            ]))
        operation = self.prepare(
            connection, actor, self.settings, "search", {
                "query": query[:4000],
                "topic": "general", "search_depth": "basic",
                **({} if discover_public else {"include_domains": sorted({
                    urlsplit(prefix).hostname
                    for permission in permissions for prefix in permission["prefixes"]
                })}),
                "max_results": MAX_SEARCH_RESULTS,
                "include_answer": False, "include_raw_content": False,
            }, discovery=row["id"], sources=permissions, public_scope=public_scope,
        )
        request = connection.execute(
            "SELECT applied FROM knowledge.material_web_requests WHERE id=%s", (operation,),
        ).fetchone()
        if request["applied"]:
            return False
        call = Runs(connection).operation(operation)
        if call.status in {"unknown", "dispatching"}:
            raise BusinessError("external_result_unknown", "Tavily 搜索结果未知，需核对原回执。")
        if call.status == "failed_known":
            return False
        state = {**state, "search_rounds": state.get("search_rounds", 0) + 1}
        if examples:
            state["node_example_lookup"] = {
                **state["node_example_lookup"], "operation": str(operation),
            }
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET status='queued',"
            "error_code='tavily_search_pending',next_run_at=now(),published_at=NULL,"
            "lease_token=NULL,lease_until=NULL,acquisition_state=%s WHERE id=%s",
            (Jsonb(state), row["id"]),
        )
        return True

    def consume(self, operation, session_digest, guard, transport=None, *, dispatch_deadline=None):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                session_digest,
            )
            owner = guard(connection, actor)
            call = Runs(connection).operation(operation)
            config = MaterialSearchConfiguration(connection, self.settings)
            if call.status == "result_recorded":
                config.binding(actor)
                try:
                    return TavilyGateway.result(call.response_body), call
                except (ValueError, TypeError):
                    raise BusinessError(
                        "tavily_invalid_response", "Tavily 返回内容无效，需要修复后再继续。",
                    ) from None
            if call.status in {"unknown", "dispatching"}:
                Runs(connection).record(call.id, unknown=True)
                raise BusinessError(
                    "external_result_unknown", "Tavily 原调用结果未知，不会自动重发。",
                )
            if call.status != "prepared":
                raise BusinessError("tavily_provider_rejected", "Tavily 拒绝了原请求。")
            deadline = dispatch_deadline(owner) if dispatch_deadline else None
            if deadline and deadline <= datetime.now(UTC):
                Runs(connection).cancel_operations([operation])
                connection.execute(
                    "UPDATE knowledge.material_web_requests SET retired=true WHERE id=%s",
                    (operation,),
                )
                return None, call
            secret = config.secret(actor, call.context_manifest["configuration"])
            if not Runs(connection).dispatch(call.id):
                raise BusinessError("external_result_unknown", "另一个处理器持有 Tavily 调用。")
        try:
            receipt = TavilyGateway(secret, transport=transport).send(call.endpoint, call.request)
        except DeliveryUnknown:
            receipt = None
        with self.database.transaction() as connection:
            Runs(connection).record(call.id, receipt, unknown=receipt is None)
        return self.consume(operation, session_digest, guard, transport,
                            dispatch_deadline=dispatch_deadline)

    def advance_search(self, discovery_id, transport=None, *, lease=None):
        from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

        with self.database.transaction(snapshot=True) as connection:
            request = connection.execute(
                "SELECT w.id,d.session_digest FROM knowledge.material_web_requests w "
                "JOIN knowledge.material_discovery_jobs d ON d.id=w.discovery_id "
                "WHERE w.discovery_id=%s AND NOT w.applied AND NOT w.retired "
                "ORDER BY w.created_at LIMIT 1",
                (discovery_id,),
            ).fetchone()
        if not request:
            return

        def guard(connection, actor):
            current = MaterialDiscoveryWorkflow.current(connection, discovery_id)
            if not current or current[1]["status"] in {"cancelled", "ready"}:
                raise BusinessError("stale_version", "Material search is no longer active.")
            if lease and (
                current[1]["lease_token"] != lease
                or not current[1]["lease_until"]
                or current[1]["lease_until"] <= datetime.now(UTC)
            ):
                raise BusinessError("lease_lost", "Another worker owns material discovery.")
            call = Runs(connection).operation(request["id"])
            public_scope = call.context_manifest.get("public_scope")
            if public_scope:
                from leornian.modules.learning.application import Learning
                from leornian.modules.learning.infrastructure import PgGoalStore

                scope = Learning(PgGoalStore(connection)).get_goal(
                    actor, current[2].goal_id,
                ).material_scope
                if not scope or public_scope != {
                    "goal_id": str(current[2].goal_id), "scope": scope.model_dump(mode="json"),
                }:
                    raise BusinessError("source_not_current", "Public-source permission changed.")
            for permission in call.context_manifest["sources"]:
                MaterialSources(connection).require(
                    actor, permission["id"], revision=permission["revision"],
                    purpose=current[2].purpose,
                )
            return current

        def search_deadline(current):
            lookup = current[1]["acquisition_state"].get("node_example_lookup", {})
            if lookup.get("operation") == str(request["id"]) and lookup.get("deadline_at"):
                return datetime.fromisoformat(lookup["deadline_at"])
            return None

        try:
            result, call = self.consume(
                request["id"], request["session_digest"], guard, transport,
                dispatch_deadline=search_deadline,
            )
            if result is None:
                return
        except BusinessError as error:
            if error.code not in {"tavily_invalid_response", "tavily_provider_rejected"}:
                raise
            # The known unusable receipt is retained; acquisition can use approved entry URLs.
            with self.database.transaction() as connection:
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True),
                ).authenticate_digest(request["session_digest"])
                guard(connection, actor)
                connection.execute(
                    "UPDATE knowledge.material_web_requests SET applied=true WHERE id=%s",
                    (request["id"],),
                )
                call = Runs(connection).operation(request["id"])
                if call.status == "result_recorded":
                    Runs(connection).applied(call.id)
                elif call.http_status in {401, 402, 403}:
                    connection.execute(
                        "UPDATE knowledge.material_discovery_jobs SET acquisition_state="
                        "acquisition_state||'{\"search_disabled\":true}'::jsonb WHERE id=%s",
                        (discovery_id,),
                    )
            return
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                request["session_digest"],
            )
            _actor, row, demand = guard(connection, actor)
            sources = MaterialSources(connection)
            hits = []
            for order, item in enumerate(result["results"][:MAX_SEARCH_RESULTS]):
                try:
                    address = urlsplit(item["url"])
                    url = canonical_source_url(urlunsplit(address._replace(fragment="")))
                except (BusinessError, ValueError, KeyError, TypeError):
                    continue
                if call.context_manifest.get("public_scope"):
                    try:
                        entry = DiscoveredSourceCatalog(connection).remember(
                            actor, row["id"], item, demand,
                        )
                        if entry:
                            hits.append(entry["url"])
                    except (BusinessError, ValueError, TypeError):
                        continue
                for permission in call.context_manifest["sources"]:
                    try:
                        approved_source_url(url, permission["prefixes"])
                    except BusinessError:
                        continue
                    resource = sources.add_resource(
                        permission["id"], url, 1, label=str(item.get("title", ""))[:500],
                        order=order,
                    )
                    hits.append(url)
                    # Entry HTML retains directory detection and exact chapter navigation.
                    connection.execute(
                        "UPDATE knowledge.material_source_resources SET "
                        "acquisition_provider='tavily' WHERE id=%s AND document_id IS NULL "
                        "AND depth>0",
                        (resource["id"],),
                    )
                    break
            state = row.get("acquisition_state") or {}
            lookup = state.get("node_example_lookup")
            if lookup and lookup.get("operation") == str(request["id"]):
                connection.execute(
                    "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
                    (Jsonb({**state, "node_example_lookup": {
                        **lookup, "hits": list(dict.fromkeys(hits)),
                    }}), row["id"]),
                )
            connection.execute(
                "UPDATE knowledge.material_web_requests SET applied=true WHERE id=%s",
                (request["id"],),
            )
            Runs(connection).applied(call.id)
            if lease:
                connection.execute(
                    "UPDATE knowledge.material_discovery_jobs SET error_code=NULL WHERE id=%s",
                    (row["id"],),
                )
            else:
                MaterialDiscoveryWorkflow.transition(connection, row["id"], "queued")

    def extract(self, actor, row, data, resource, guard, transport=None):
        with self.database.transaction() as connection:
            guard(connection, actor)
            operation = self.prepare(
                connection, actor, self.settings, "extract",
                {"urls": [approved_source_url(resource["url"], data.allowed_prefixes)],
                 "extract_depth": "basic", "format": "markdown",
                 "include_images": True},
                observation=row["id"],
            )
        result, call = self.consume(
            operation, row["session_digest"], guard, transport,
            dispatch_deadline=lambda _owner: row.get("example_deadline"),
        )
        if result is None:
            raise BusinessError("material_example_deadline", "示例补读时间已用完。")
        page = next((
            page for page in result["results"] if page.get("url") == resource["url"]
            and isinstance(page.get("raw_content"), str) and page["raw_content"].strip()
        ), None)
        if page is None:
            raise BusinessError(
                "tavily_extraction_failed", "所选页面没有提取到有效正文，可修复为原站直接获取。",
            )
        content = page["raw_content"].encode("utf-8")
        with self.database.transaction() as connection:
            guard(connection, actor)
            Runs(connection).applied(call.id)
            connection.execute(
                "UPDATE knowledge.material_web_requests SET applied=true WHERE id=%s", (operation,),
            )
        if page.get("images") or "![" in page["raw_content"] or "<svg" in page["raw_content"]:
            raise BusinessError(
                "tavily_original_required",
                "页面包含图像或图表，改用原站解析以保留内容完整性。",
            )
        return SourceResponse(
            url=TAVILY_ORIGIN + "/extract", status_code=200, content=content,
            content_type="text/markdown; charset=utf-8", etag=None, last_modified=None,
            redirects=(),
        )
