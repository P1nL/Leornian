from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.retrieval import Retrieval
from leornian.modules.knowledge.source_acquisition import MaterialSources, identity
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.material_contracts import MaterialBindingInput, material_content_key
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError


class PlanningMaterials:
    """Checked planning intents reuse Knowledge demands; batches never certify a whole route."""

    @staticmethod
    def blocks_drafting(turn, manifest):
        return manifest.get("planning_policy") != "model-first.v1" or bool(
            turn.planning_state and turn.planning_state.material_gaps
        )

    @staticmethod
    def complete_objective_in(connection, conversation_id):
        """Plan against current learner choices, not accumulated discovery wording."""
        from leornian.modules.tutor.route_requirements import RouteRequirements

        saved = RouteRequirements(connection).get(conversation_id)
        facts = saved["learner_stated"] if saved else {}
        return "\n".join(
            f"{label}: {facts[key]['value']}"
            for key, label in (
                ("goal", "Learning goal"),
                ("included_scope", "Included scope"),
                ("preferences", "Learning preferences and order"),
            )
            if facts.get(key, {}).get("value")
        ) or None

    @staticmethod
    def is_batch(demand):
        return bool(demand and demand.consumer_ref.startswith("planning-batch:"))

    @staticmethod
    def can_draft_from_partial(demand, selection):
        """A broad planning batch can inform a draft; exact gaps still need resolution."""
        return bool(
            PlanningMaterials.is_batch(demand)
            and demand.purpose == "planning" and demand.preparation == "complete"
            and not demand.consumer_ref.startswith(f"planning-batch:{demand.goal_id}:gap:")
            and selection.coverage.basis == "route-planning-evidence.v1"
            and selection.coverage.status == "partial"
            and selection.coverage.usable_for_planning and selection.evidence
            and selection.coverage.required
            and all(
                facet.status in {"supported", "partial"}
                for facet in selection.coverage.required
            )
        )

    @staticmethod
    def for_turn_in(connection, actor, conversation, turn):
        intake = MaterialIntake(connection)
        if turn.material_demand_id:
            return intake.demand(actor, turn.material_demand_id)
        previous = next((
            item for item in reversed(PgTutorStore(connection).turns(conversation.id))
            if item.id != turn.id and item.purpose == "planning" and item.material_demand_id
            and (item.created_at, str(item.id)) < (turn.created_at, str(turn.id))
        ), None)
        if previous:
            demand = intake.demand(actor, previous.material_demand_id)
            if demand.status != "cancelled":
                PgTutorStore(connection).bind_material_demand(turn.id, demand.id)
                return demand
        batches = intake.planning_batches(actor, conversation.goal_id)
        if batches:
            demand = batches[-1]
            PgTutorStore(connection).bind_material_demand(turn.id, demand.id)
            return demand
        return None

    @staticmethod
    def overview_in(connection, conversation, turn, context, *, model_first=False):
        from leornian.modules.identity.application import Identity
        from leornian.modules.identity.infrastructure import PgIdentityStore

        owner = connection.execute(
            "SELECT actor_id FROM tutor.conversations WHERE id=%s", (conversation.id,),
        ).fetchone()
        actor = Identity(PgIdentityStore(connection)).get_actor(owner["actor_id"])
        batches = MaterialIntake(connection).planning_batches(actor, conversation.goal_id)
        inputs = MaterialIntake(connection).planning_inputs(actor, conversation.goal_id)
        sources = MaterialSources(connection)
        items = []
        partial_draft_ready = False
        for demand in batches:
            discovery = sources.discovery(actor, demand.id, demand.revision)
            item = {
                "demand_id": str(demand.id), "stage": demand.preparation,
                "goal": demand.goal_text, "status": discovery.status if discovery else "queued",
            }
            if discovery and discovery.selection_id and discovery.status == "ready":
                selection = Retrieval(connection).selection(actor, discovery.selection_id)
                item["synopsis"] = selection.coverage.synopsis
                item["coverage_status"] = selection.coverage.status
                item["missing_topics"] = selection.coverage.missing_facets
                if demand.id == turn.material_demand_id:
                    partial_draft_ready = PlanningMaterials.can_draft_from_partial(
                        demand, selection,
                    )
            items.append(item)
        curriculum = PlanningMaterials.curriculum_sources_in(
            connection, actor, conversation.goal_id,
        )
        return {
            "batches": items,
            "first_batch_only": bool(
                turn.stage_replies and any(
                    demand.id == turn.material_demand_id and demand.preparation == "initial"
                    for demand in batches
                )
            ),
            "learner_materials": [
                {key: value for key, value in item.items()
                 if key not in {"input_key", "content_digest"}} for item in inputs
            ],
            "route_ready": model_first or partial_draft_ready or bool(
                context.get("material_goal_coverage", {}).get("basis")
                in {"semantic-goal-evidence.v1", "route-planning-evidence.v1"}
                and context["material_goal_coverage"]["status"] == "sufficient"
            ),
            "materials_required": not model_first and bool(
                Learning(PgGoalStore(connection)).get_goal(
                    actor, conversation.goal_id,
                ).material_scope or context.get("bound_materials") or inputs
            ),
            "curriculum_sources": curriculum,
            "reading_sources": PlanningMaterials.reading_sources_in(
                connection, actor, conversation.goal_id,
                exclude_urls={item["source_url"] for item in curriculum},
            ),
        }

    @staticmethod
    def reading_sources_in(connection, actor, goal_id, *, exclude_urls=(), preview=True):
        """Supply existing outlines and catalog candidates without starting material work."""
        from types import SimpleNamespace

        from leornian.modules.knowledge.retrieval import terms
        from leornian.modules.knowledge.source_candidates import (
            MAX_CATALOG_CANDIDATES,
            ranked_candidates,
        )

        goal = Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
        topic = "\n".join((goal.title, goal.motivation))
        observed = MaterialSources(connection).curriculum_catalog(actor, goal_id)
        result = [{
            "title": source["title"], "source_url": source["source_url"],
            "chapters": source["chapters"], "basis": "observed_outline",
        } for source in observed if source["source_url"] not in exclude_urls]
        scope = goal.material_scope
        if scope:
            demand = SimpleNamespace(
                language=scope.language, language_version=scope.language_version,
                framework=None, framework_version=None, preparation="complete", goal_text=topic,
            )
            known = {*exclude_urls, *(item["source_url"] for item in result)}
            result.extend({
                "title": entry["title"], "source_url": entry["url"],
                "chapters": [], "basis": "catalog_candidate",
            } for entry in ranked_candidates(
                demand, topic,
                allowed_origins=None if scope.authorized_public_sources else {"official"},
            ) if entry["url"] not in known)
        if preview:
            wanted = set(terms(topic))
            result.sort(key=lambda source: -len(wanted & set(terms(source["title"]))))
            result = result[:MAX_CATALOG_CANDIDATES]
            for source in result:
                chapters = source["chapters"]
                selected = sorted(
                    enumerate(chapters),
                    key=lambda item: (-len(wanted & set(terms(item[1]["title"]))), item[0]),
                )[:MAX_CATALOG_CANDIDATES]
                source["total_chapters"] = len(chapters)
                source["chapters"] = [
                    {**chapter, "ordinal": index} for index, chapter in sorted(selected)
                ]
        return result

    @staticmethod
    def curriculum_sources_in(connection, actor, goal_id):
        from leornian.modules.learning.material_contracts import MaterialCitation

        bindings = MaterialBindings(connection).for_scope(actor, goal_id, "planning")
        citations = [
            MaterialCitation(
                binding_id=binding.id, binding_revision=binding.revision,
                purpose="planning", ref=ref,
            ) for binding in bindings for ref in binding.refs
        ]
        blocks = Materials(connection).read_refs(
            actor, goal_id, "planning", [citation.ref for citation in citations],
        )
        document_ids = {block.ref.document_id for block in blocks}
        sources = MaterialSources(connection).curriculum_catalog(actor, goal_id, document_ids)
        for source in sources:
            for block in blocks:
                if str(block.ref.document_id) not in source["evidence_document_ids"]:
                    continue
                version = Materials(connection).version(
                    actor, block.ref.document_id, block.ref.document_revision,
                )
                chapter = {
                    "title": " / ".join(block.section_path) or version.title,
                    "source_url": version.source_url,
                }
                if chapter not in source["chapters"]:
                    source["chapters"].append(chapter)
        covered = {value for source in sources for value in source["evidence_document_ids"]}
        for document_id in sorted(document_ids, key=str):
            if str(document_id) in covered:
                continue
            document_blocks = [block for block in blocks if block.ref.document_id == document_id]
            version = Materials(connection).version(
                actor, document_id, document_blocks[0].ref.document_revision,
            )
            sources.append({
                "title": version.title, "source_url": (
                    version.source_url if version.source_url.startswith("https://") else None
                ),
                "evidence_document_ids": [str(document_id)],
                "chapters": [
                    {"title": title, "source_url": (
                        version.source_url if version.source_url.startswith("https://") else None
                    ), "document_id": str(document_id)}
                    for title in dict.fromkeys(
                        " / ".join(block.section_path) or version.title for block in document_blocks
                    )
                ],
            })
        return sources

    @staticmethod
    def validate_route_in(connection, actor, goal_id, document, *, materials_required=True):
        """Validate the selected curriculum against supplied, currently allowed addresses."""
        planned = [
            reading for node in document.nodes if node.material_plan
            for reading in node.material_plan.readings
        ]
        if planned:
            sources = [
                *PlanningMaterials.curriculum_sources_in(connection, actor, goal_id),
                *PlanningMaterials.reading_sources_in(connection, actor, goal_id, preview=False),
            ]
            urls = {
                url for source in sources
                for url in [
                    source["source_url"],
                    *(chapter["source_url"] for chapter in source["chapters"]),
                ] if url
            }
            supplied_documents = {
                str(value) for source in sources
                for value in source.get("evidence_document_ids", [])
            }
            for reading in planned:
                if reading.source_url and reading.source_url not in urls:
                    raise BusinessError(
                        "invalid_plan_output", "Planned readings need supplied source addresses.",
                    )
                if reading.document_id:
                    if str(reading.document_id) not in supplied_documents:
                        raise BusinessError(
                            "invalid_plan_output", "Planned readings need supplied documents.",
                        )
                    Materials(connection).require_use(
                        actor, reading.document_id, reading.document_revision,
                        "planning", goal_id=goal_id,
                    )
        if document.curriculum is None:
            if materials_required:
                raise BusinessError("invalid_plan_output", "Select the route curriculum first.")
            return
        sources = PlanningMaterials.curriculum_sources_in(connection, actor, goal_id)
        selected = {}
        for text in document.curriculum.texts:
            documents = {str(citation.ref.document_id) for citation in text.material_citations}
            source = next((
                source for source in sources if source["source_url"] == text.source_url
                and documents <= set(source["evidence_document_ids"])
            ), None)
            if source is None:
                raise BusinessError(
                    "invalid_plan_output", "Curriculum texts need supplied source evidence.",
                )
            selected[text.key] = {
                (chapter["title"], chapter["source_url"], chapter.get("document_id")
                 if chapter["source_url"] is None else None)
                for chapter in source["chapters"]
            }
        for node in document.nodes:
            for chapter in node.curriculum_chapters:
                if (chapter.title, chapter.source_url, str(chapter.document_id)
                    if chapter.source_url is None else None) not in selected[chapter.text_key]:
                    raise BusinessError(
                        "invalid_plan_output", "Use an observed curriculum chapter and address.",
                    )

    @staticmethod
    def apply_in(
        connection, actor, conversation, turn, reply, digest, *, previous=None, model_first=False,
    ):
        from leornian.bootstrap.material_consumers import consumer_material_required_in
        from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

        intent = reply.rag_intent
        if model_first and turn.planning_requested and not reply.material_gaps:
            return previous
        if (
            reply.route is not None and intent.action == "none"
            and not reply.material_gaps and previous
        ):
            # Publish against the checked batch used by this candidate, including a resolved gap.
            return previous
        batches = MaterialIntake(connection).planning_batches(actor, conversation.goal_id)
        complete = turn.planning_requested
        if intent.action == "none" and not complete:
            return previous
        goal = Learning(PgGoalStore(connection)).get_goal(actor, conversation.goal_id)
        complete_objective = (
            PlanningMaterials.complete_objective_in(connection, conversation.id)
            if complete else None
        )
        if reply.material_gaps:
            objective = "\n".join(reply.material_gaps)
        elif complete_objective:
            objective = complete_objective
        elif intent.action == "none":
            if complete and turn.planning_state and turn.planning_state.material_goal:
                objective = "\n".join([
                    turn.planning_state.material_goal, *turn.planning_state.material_topics,
                ])
            elif previous and previous.preparation == "complete":
                return previous
            elif previous:
                objective = previous.goal_text
            elif reply.route:
                objective = "\n".join([
                    reply.route.title, reply.route.summary,
                    *(node.objective for node in reply.route.nodes),
                ])
            else:
                return previous
        else:
            objective = "\n".join([
                intent.goal.strip(), *sorted(set(intent.topics), key=str.casefold),
            ])
        preparation = "complete" if complete else "initial" if not batches else "incremental"
        # Canonical exact intents share work across retries and regenerations.
        lines = list(dict.fromkeys(
            " ".join(line.split()).casefold() for line in objective.splitlines() if line.strip()
        ))
        normalized = "\n".join(
            sorted(lines) if reply.material_gaps else [*lines[:1], *sorted(lines[1:])]
        )
        subject = {
            name: getattr(goal.material_scope, name)
            for name in ("language", "language_version", "framework", "framework_version")
        } if goal.material_scope else {}
        request = MaterialDemandInput(
            goal_id=goal.id, purpose="planning", scope_mode="teaching_goal",
            preparation=preparation, goal_text=normalized, **subject,
        )
        scope = {
            **MaterialIntake.demand_request(request.model_copy(update={"preparation": "complete"})),
            "coverage_stage": "complete" if preparation == "complete" else "batch",
            "learner_inputs": [
                item["input_key"] for item in MaterialIntake(connection).planning_inputs(
                    actor, goal.id,
                )
            ],
            "authorized_scope": goal.material_scope.model_dump(mode="json")
            if goal.material_scope else None,
        }
        if reply.material_gaps:
            scope["requirements_revision"] = turn.planning_state.requirements_revision
        consumer = (
            f"planning-batch:{goal.id}:"
            + ("gap:" if reply.material_gaps else "")
            + identity(scope)
        )
        existing = MaterialIntake(connection).consumer_demand(actor, consumer)
        if existing and existing.status == "cancelled":
            consumer += f":turn:{turn.id}"
            existing = MaterialIntake(connection).consumer_demand(actor, consumer)
        if existing:
            request = request.model_copy(update={"preparation": existing.preparation})
        demand = MaterialIntake(connection).ensure_consumer_demand(actor, consumer, request)
        older = [
            item for item in PgTutorStore(connection).turns(conversation.id)
            if item.purpose == "planning"
            and (item.created_at, str(item.id)) <= (turn.created_at, str(turn.id))
        ]
        MaterialIntake(connection).supersede_planning_consumers(
            actor, goal.id, [
                ref for item in older for ref in (
                    f"tutor-turn:{item.id}:planning",
                    f"tutor-turn:{item.id}:planning:semantic-goal.v1",
                )
            ] + [item.consumer_ref for item in batches if item.id != demand.id],
        )
        PgTutorStore(connection).bind_material_demand(turn.id, demand.id)
        if consumer_material_required_in(connection, actor, demand):
            MaterialDiscoveryWorkflow.ensure_in(connection, actor, digest, demand)
            if turn.material_demand_id and turn.material_demand_id != demand.id:
                MaterialSources(connection).inherit_acquisition_budget(
                    actor, turn.material_demand_id, demand.id,
                    chain_started_at=turn.created_at,
                )
        return demand

    @staticmethod
    def ready_in(connection, actor, digest, demand):
        from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

        discovery = MaterialDiscoveryWorkflow.ensure_in(connection, actor, digest, demand)
        if discovery is None or discovery.status != "ready" or not discovery.selection_id:
            raise BusinessError(
                "material_pending", (discovery.error_code if discovery else None)
                or "planning_material_batch_pending",
            )
        selection = Retrieval(connection).selection(actor, discovery.selection_id)
        if not PlanningMaterials.can_draft_from_partial(demand, selection) and (
            selection.coverage.basis not in {
                "semantic-goal-evidence.v1", "planning-batch-evidence.v1",
                "route-planning-evidence.v1",
            } or selection.coverage.status != "sufficient"
        ):
            raise BusinessError("material_pending", "The requested planning batch is not checked.")
        refs = [item.ref for item in selection.evidence]
        Materials(connection).read_refs(actor, demand.goal_id, "planning", refs)
        bindings = MaterialBindings(connection)
        current = bindings.for_scope(actor, demand.goal_id, "planning")
        previous = {material_content_key(ref): ref for binding in current for ref in binding.refs}
        additions = {material_content_key(ref): ref for ref in refs}
        if not additions.keys() <= previous.keys():
            revision = current[0].revision if current else 0
            bindings.bind(
                actor, f"planning-batch:{demand.id}:selection:{selection.id}:base:{revision}",
                MaterialBindingInput(
                    goal_id=demand.goal_id, purpose="planning",
                    expected_binding_revision=revision,
                    refs=list({**previous, **additions}.values()),
                ),
            )
        return selection

    @staticmethod
    def begin_in(connection, actor, conversation, turn, digest):
        return PlanningMaterials.for_turn_in(connection, actor, conversation, turn)

    @staticmethod
    def blockage_in(connection, actor, demand):
        from leornian.bootstrap.material_acquisition import REPLACEABLE
        from leornian.modules.knowledge.progress import MaterialPreparation

        progress = MaterialPreparation(connection).for_demand(actor, demand.id)
        discovery = MaterialSources(connection).discovery(actor, demand.id, demand.revision)
        if discovery and discovery.error_code == "material_discovery_exhausted" and (
            progress.status != "blocked_unknown"
        ):
            return progress.model_copy(update={
                "status": "waiting_dependency", "reason_code": "material_discovery_exhausted",
            })
        if discovery and discovery.status in {"queued", "processing"} and (
            progress.reason_code in REPLACEABLE and progress.status != "blocked_unknown"
        ):
            return None
        if progress.status in {"blocked_unknown", "waiting_config"} or (
            progress.status == "waiting_dependency" and progress.reason_code in {
                "automatic_repair_exhausted", "material_nontext_processing_required",
                "material_replacement_source_required", "approved_source_coverage_gap",
                "source_http_unavailable", "tavily_provider_rejected", "tavily_extraction_failed",
                "tavily_invalid_response", "provider_rejected", "invalid_material_response",
                "material_discovery_exhausted",
                "material_quality_pending",
            }
        ):
            return progress
        return None
