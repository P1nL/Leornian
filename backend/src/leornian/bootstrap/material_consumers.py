from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.retrieval import Retrieval
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.material_contracts import (
    MaterialBindingInput,
    MaterialCitation,
    citation_key,
    material_content_key,
)
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError


def binding_citations(bindings):
    return [
        MaterialCitation(binding_id=b.id, binding_revision=b.revision, purpose=b.purpose, ref=ref)
        for b in bindings
        for ref in b.refs
    ]


def manifest_citations(manifest, purpose=None):
    if "material_context_citations" in manifest:
        return [MaterialCitation(**item) for item in manifest["material_context_citations"]]
    return [
        MaterialCitation(
            binding_id=b["id"],
            binding_revision=b["revision"],
            purpose=b.get("purpose", purpose),
            ref=ref,
        )
        for b in manifest.get("material_bindings", [])
        for ref in b["refs"]
    ]


def read_citations_in(connection, actor, goal_id, citations):
    """Resolve the immutable binding as well as live, purpose-specific permission."""
    bindings = {}
    blocks = []
    for citation in citations:
        key = (citation.binding_id, citation.binding_revision)
        if key not in bindings:
            bindings[key] = MaterialBindings(connection).get(actor, *key)
        binding = bindings[key]
        if binding.goal_id != goal_id or binding.purpose != citation.purpose:
            raise BusinessError("source_not_current", "Citation is outside its exact binding.")
        if citation_key(citation) not in {citation_key(c) for c in binding_citations([binding])}:
            MaterialBindings.require_ref_in(binding, citation.ref)
            Retrieval(connection).require_bound_selection(
                actor,
                goal_id,
                citation.purpose,
                citation.ref,
                binding.id,
                binding.revision,
            )
        blocks.extend(
            Materials(connection).read_refs(actor, goal_id, citation.purpose, [citation.ref])
        )
    return blocks


def attempt_material_scope_in(connection, actor, focus):
    from leornian.bootstrap.evaluation import EvaluationWorkflow
    from leornian.modules.item_bank.supply import Packs
    from leornian.modules.tutor.evaluations import Evaluations

    feedback = Evaluations(connection).receipt_context(actor, focus.assessment_receipt_id)
    pack = Packs(connection).row(actor, feedback["pack_id"])
    if (pack["plan_id"], pack["plan_revision"], pack["node_key"]) != (
        focus.plan_id, focus.expected_plan_revision, focus.node_key
    ):
        raise BusinessError("stale_version", "Feedback belongs to another node.")
    _, node, _ = EvaluationWorkflow.current(connection, actor, feedback)
    question = feedback["context_data"]["question"]
    legacy_only = bool(question.get("source_refs")) and not (
        question.get("material_citations") or node.material_citations
    )
    return question, legacy_only


def prepare_consumer_in(
    connection, actor, conversation, turn, purpose, focus, *, session_digest=None,
    discussion=False,
):
    if purpose == "planning" and discussion:
        from leornian.bootstrap.planning_materials import PlanningMaterials

        return PlanningMaterials.for_turn_in(connection, actor, conversation, turn)
    goal = Learning(PgGoalStore(connection)).get_goal(actor, conversation.goal_id)
    node = None
    if focus.plan_id:
        plan = Plans(connection).get(actor, focus.plan_id)
        if (
            plan.goal_id != goal.id
            or not plan.active
            or plan.active.revision != focus.expected_plan_revision
        ):
            raise BusinessError("stale_version", "Consumer needs the active exact plan.")
        node = next((n for n in plan.active.document.nodes if n.key == focus.node_key), None)
        if not node:
            raise BusinessError("not_found", "Consumer node not found.")
    objective = node.objective if node else goal.title
    consumer_ref = f"tutor-turn:{turn.id}:{purpose}"
    question = None
    if purpose == "teaching" and focus.kind == "attempt":
        question, legacy_only = attempt_material_scope_in(connection, actor, focus)
        if legacy_only:
            # Legacy receipts keep their checked exact sources after unrelated uploads.
            return None
        objective = "\n".join((question["title"], question["prompt"]))
        consumer_ref += ":attempt-source.v1"
    if not node and goal.material_scope and goal.material_scope.language is None:
        objective = "\n".join(
            part for part in (goal.title, goal.motivation, turn.user_text) if part
        )
    demand = register_node_demand_in(
        connection, actor, goal.id, focus, purpose, consumer_ref, objective
    )
    if question is not None or node is not None:
        from leornian.modules.tutor.infrastructure import PgTutorStore

        PgTutorStore(connection).bind_material_demand(turn.id, demand.id)
    if node and node.material_citations:
        ensure_node_binding_in(connection, actor, goal.id, focus, node, purpose)
    if session_digest and consumer_material_required_in(connection, actor, demand):
        from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

        MaterialDiscoveryWorkflow.ensure_in(
            connection, actor, session_digest, demand, resume_examples=True,
        )
    return demand


def register_node_demand_in(connection, actor, goal_id, focus, purpose, consumer_ref, objective):
    goal = Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
    subject = {
        name: getattr(goal.material_scope, name)
        for name in ("language", "language_version", "framework", "framework_version")
    } if goal.material_scope else {}
    prefix = None
    if focus.plan_id and focus.node_key:
        curriculum = Plans(connection).curriculum_snapshot(
            actor, focus.plan_id, focus.expected_plan_revision, node_key=focus.node_key,
        )
        if curriculum:
            from leornian.modules.knowledge.source_catalog import topic_subjects

            # A route-wide framework is not automatically a dependency of each node.
            subject.update(framework=None, framework_version=None)
            node = curriculum["node_chapters"][0]
            preparation = node["material_plan"]
            technologies = preparation["technologies"]
            inferred = []
            for technology in technologies:
                for item in topic_subjects(technology["name"]):
                    version = "framework_version" if item["framework"] else "language_version"
                    item[version] = technology["version"]
                    inferred.append(item)
            inferred = inferred or topic_subjects(objective)
            languages = [item for item in inferred if not item["framework"]]
            language = next(
                (item for item in languages if item["language"] == subject.get("language")),
                languages[0] if languages else None,
            )
            framework = next((item for item in inferred if item["framework"]), None)
            if language:
                version = language["language_version"] or (
                    subject.get("language_version")
                    if subject.get("language") == language["language"] else None
                )
                subject.update(
                    language=language["language"], language_version=version,
                )
            if framework:
                if not language and not subject.get("language"):
                    subject["language"] = framework["language"]
                subject.update(
                    framework=framework["framework"],
                    framework_version=framework["framework_version"],
                )
            if focus.kind != "attempt" and preparation["topics"]:
                objective = "\n".join(preparation["topics"])
            parts = [objective]
            if node["chapters"]:
                parts.append("Selected curriculum chapters: " + "; ".join(
                    chapter["title"] for chapter in node["chapters"]
                ))
            if preparation["readings"]:
                parts.append("Preferred readings: " + "; ".join(
                    reading["title"] for reading in preparation["readings"]
                ))
            if technologies:
                parts.append("Technology versions: " + "; ".join(
                    f"{item['name']} {item['version']}" if item["version"] else item["name"]
                    for item in technologies
                ))
            objective = "\n".join(parts)
        if focus.kind != "attempt" and purpose in {"teaching", "lesson"}:
            prefix = (
                f"node-material:{focus.plan_id}:{focus.expected_plan_revision}:"
                f"{focus.node_key}:{purpose}:v1"
            )
    request = MaterialDemandInput(
        goal_id=goal_id,
        plan_id=focus.plan_id,
        plan_revision=focus.expected_plan_revision,
        node_key=focus.node_key,
        purpose=purpose,
        scope_mode="teaching_goal",
        goal_text=objective,
        **subject,
    )
    intake = MaterialIntake(connection)
    reusable = intake.reusable_consumer_demand(actor, prefix, request) if prefix else None
    return reusable or intake.ensure_consumer_demand(
        actor, f"{prefix + ':' if prefix else ''}{consumer_ref}:semantic-goal.v1", request,
    )


def stop_consumer_material_in(connection, actor, demand, turn_id):
    from leornian.agent_runtime.repository import Runs
    from leornian.modules.knowledge.source_acquisition import MaterialSources
    from leornian.modules.tutor.deliveries import Deliveries
    from leornian.modules.tutor.infrastructure import PgTutorStore

    runs = Runs(connection)
    for other in PgTutorStore(connection).material_consumer_turns(actor.id, demand.id):
        if other == turn_id:
            continue
        run = runs.for_turn(actor.id, other)
        task = Deliveries(connection).for_run(run.id)
        if not run.cancel_requested and (
            task and not task["cancel_requested"]
            and task["status"] not in {"accepted", "cancelled", "superseded"}
            or run.status in {"queued", "running"}
        ):
            return
    stopped = MaterialSources(connection).stop_preparation(actor, demand)
    runs.cancel_operations(stopped["operations"])
    for run_id in stopped["runs"]:
        run = runs.get(actor.id, run_id)
        if run.status not in {"succeeded", "failed", "cancelled"}:
            runs.cancel(run_id)
            runs.mark_unknown(run_id)
            runs.finish(run_id, "cancelled")


def consumer_material_required_in(connection, actor, demand):
    scope = Learning(PgGoalStore(connection)).get_goal(actor, demand.goal_id).material_scope
    if scope:
        from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

        if scope.language is not None or MaterialDiscoveryWorkflow.catalog_in(
            connection, actor, demand
        ):
            return True
    if MaterialBindings(connection).for_scope(
        actor,
        demand.goal_id,
        demand.purpose,
        plan_id=demand.plan_id,
        plan_revision=demand.plan_revision,
        node_key=demand.node_key,
    ):
        return True
    return bool(
        connection.execute(
            "SELECT 1 FROM knowledge.documents WHERE actor_id=%s AND goal_id=%s "
            "UNION ALL SELECT 1 FROM knowledge.material_source_registrations "
            "WHERE actor_id=%s AND goal_id=%s "
            "UNION ALL SELECT 1 FROM knowledge.material_uploads WHERE actor_id=%s "
            "AND specification->'material'->>'goal_id'=%s LIMIT 1",
            (actor.id, demand.goal_id, actor.id, demand.goal_id, actor.id, str(demand.goal_id)),
        ).fetchone()
    )


def exhausted_teaching_material_in(connection, actor, demand, bindings):
    from leornian.modules.knowledge.source_acquisition import MaterialSources

    refs = MaterialSources(connection).node_teaching_refs(
        actor, demand, [ref for binding in bindings for ref in binding.refs],
    )
    if refs and not bindings:
        Materials(connection).read_refs(actor, demand.goal_id, "teaching", refs)
        bindings = [MaterialBindings(connection).bind(
            actor, f"node-teaching-excerpts:{demand.id}:{demand.revision}",
            MaterialBindingInput(
                goal_id=demand.goal_id, purpose="teaching", plan_id=demand.plan_id,
                plan_revision=demand.plan_revision, node_key=demand.node_key,
                expected_binding_revision=0, refs=refs,
            ),
        )]
    return bindings, refs


def ensure_consumer_material_in(
    connection, actor, session_digest, demand, *, frozen_bindings=None
):
    from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
    from leornian.modules.knowledge.source_acquisition import MaterialSources, ordinary_node_reading

    bindings = MaterialBindings(connection)
    if frozen_bindings is not None:
        if not frozen_bindings:
            raise BusinessError("source_not_current", "Frozen material bindings are missing.")
        current = []
        for frozen in frozen_bindings:
            exact = bindings.get(actor, frozen.id, frozen.revision)
            bindings.require_scope(actor, exact)
            if exact != frozen or (
                exact.goal_id, exact.purpose, exact.plan_id, exact.plan_revision, exact.node_key
            ) != (
                demand.goal_id, demand.purpose, demand.plan_id, demand.plan_revision,
                demand.node_key,
            ):
                raise BusinessError("source_not_current", "Frozen material binding changed scope.")
            current.append(exact)
        required_refs = [ref for binding in current for ref in binding.refs]
    else:
        required_refs = None
        current = bindings.for_scope(
            actor, demand.goal_id, demand.purpose, plan_id=demand.plan_id,
            plan_revision=demand.plan_revision, node_key=demand.node_key,
        )
    discovery = MaterialDiscoveryWorkflow.ensure_in(
        connection, actor, session_digest, demand, required_refs=required_refs
    )
    if discovery and discovery.error_code == "node_material_review_failed":
        raise BusinessError(discovery.error_code, "节点材料审核未能返回有效结果，已停止审核。")
    if discovery and discovery.error_code == "material_discovery_exhausted" and (
        demand.consumer_ref.startswith("node-material:")
    ):
        gaps = "；".join(discovery.missing_facets)
        raise BusinessError(discovery.error_code, f"节点材料仍缺少：{gaps}")
    node_reading = frozen_bindings is None and ordinary_node_reading(demand)
    if discovery and discovery.status == "ready" and not discovery.selection_id and (
        node_reading and current
    ):
        return None
    if discovery is None or discovery.status != "ready" or not discovery.selection_id:
        raise BusinessError(
            "material_pending",
            discovery.error_code
            if discovery and discovery.error_code
            else "Teaching material is being prepared for the complete goal.",
        )
    selection = Retrieval(connection).selection(actor, discovery.selection_id)
    partial_reading = node_reading and selection.coverage.status == "partial"
    if partial_reading:
        refs = MaterialSources(connection).node_teaching_refs(actor, demand)
        evidence = [item for item in selection.evidence if item.ref in refs]
        if not evidence:
            raise BusinessError("material_pending", "No checked node reading is available.")
        selection = selection.model_copy(update={"evidence": evidence})
    allowed_basis = (
        {"semantic-goal-evidence.v1", "route-planning-evidence.v1"}
        if demand.purpose == "planning" else {"semantic-goal-evidence.v1"}
    )
    if (
        selection.coverage.basis not in allowed_basis
        or not partial_reading and selection.coverage.status != "sufficient"
    ):
        raise BusinessError("material_pending", "The exact goal still needs supported evidence.")
    Materials(connection).read_refs(
        actor, demand.goal_id, demand.purpose, [item.ref for item in selection.evidence]
    )
    if current and frozen_bindings is None and (
        MaterialDiscoveryWorkflow.public_sources_in(connection, actor, demand)
    ):
        original = current[0]
        refs = {material_content_key(ref): ref for ref in original.refs}
        selected_refs = {
            material_content_key(item.ref): item.ref for item in selection.evidence
        }
        if not selected_refs.keys() <= refs.keys():
            current = [bindings.bind(
                actor, f"consumer-supplement:{demand.id}:{selection.id}:base:{original.revision}",
                MaterialBindingInput(
                    goal_id=demand.goal_id, purpose=demand.purpose,
                    plan_id=demand.plan_id, plan_revision=demand.plan_revision,
                    node_key=demand.node_key, expected_binding_revision=original.revision,
                    refs=list({**refs, **selected_refs}.values()),
                ),
            )]
    if current:
        for evidence in selection.evidence:
            binding = next(
                (
                    candidate
                    for candidate in current
                    if any(
                        ref.document_id == evidence.ref.document_id
                        and ref.document_revision == evidence.ref.document_revision
                        and ref.block_id == evidence.ref.block_id
                        and ref.span.start <= evidence.ref.span.start
                        and ref.span.end >= evidence.ref.span.end
                        for ref in candidate.refs
                    )
                ),
                None,
            )
            if binding is None:
                raise BusinessError(
                    "source_not_current", "Selected source left its material binding."
                )
            if evidence.ref not in binding.refs:
                if required_refs is not None:
                    Retrieval(connection).require_frozen_selection(
                        actor, demand.goal_id, demand.purpose, evidence.ref, required_refs
                    )
                else:
                    Retrieval(connection).require_bound_selection(
                        actor, demand.goal_id, demand.purpose, evidence.ref,
                        binding.id, binding.revision,
                    )
    else:
        MaterialBindings(connection).bind(
            actor,
            "semantic-consumer:" + str(demand.id),
            MaterialBindingInput(
                goal_id=demand.goal_id,
                purpose=demand.purpose,
                plan_id=demand.plan_id,
                plan_revision=demand.plan_revision,
                node_key=demand.node_key,
                expected_binding_revision=0,
                refs=[item.ref for item in selection.evidence],
            ),
        )
    return selection


def ensure_node_binding_in(connection, actor, goal_id, focus, node, purpose):
    read_citations_in(connection, actor, goal_id, node.material_citations)
    if node.curriculum_chapters:
        current = MaterialBindings(connection).for_scope(
            actor, goal_id, purpose, plan_id=focus.plan_id,
            plan_revision=focus.expected_plan_revision, node_key=focus.node_key,
        )
        for binding in current:
            Materials(connection).read_refs(actor, goal_id, purpose, binding.refs)
        # Planning paragraphs justify curriculum selection. Node preparation owns the full body.
        return current
    # A selection is purpose-bound. Derivation retains its origin in the plan,
    # then separately checks the exact content for the new consumer purpose.
    refs = list(
        {
            material_content_key(c.ref): c.ref.model_copy(update={"selection_id": None})
            for c in node.material_citations
        }.values()
    )
    Materials(connection).read_refs(actor, goal_id, purpose, refs)
    bindings = MaterialBindings(connection)
    current = bindings.for_scope(
        actor,
        goal_id,
        purpose,
        plan_id=focus.plan_id,
        plan_revision=focus.expected_plan_revision,
        node_key=focus.node_key,
    )
    if current:
        if {material_content_key(r) for b in current for r in b.refs} != {
            material_content_key(r) for r in refs
        } and not all(bindings.accepted_successor_of(actor, b, refs) for b in current):
            raise BusinessError("stale_version", "Node consumer material binding changed.")
        for binding in current:
            Materials(connection).read_refs(actor, goal_id, purpose, binding.refs)
        return current
    binding = bindings.bind(
        actor,
        f"node-materials:{focus.plan_id}:{focus.expected_plan_revision}:{focus.node_key}:{purpose}",
        MaterialBindingInput(
            goal_id=goal_id,
            plan_id=focus.plan_id,
            plan_revision=focus.expected_plan_revision,
            node_key=focus.node_key,
            purpose=purpose,
            expected_binding_revision=0,
            refs=refs,
        ),
    )
    return [binding]
