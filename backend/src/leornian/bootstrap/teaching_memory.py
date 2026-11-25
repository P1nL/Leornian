"""Compose a bounded learning memory from existing owners' committed facts."""

import json
from collections import Counter

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_consumers import manifest_citations, read_citations_in
from leornian.modules.assessment.evidence import AssessmentEvidence
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.execution.application import Execution
from leornian.modules.item_bank.evidence_context import EvidenceContext
from leornian.modules.item_bank.supply import Packs
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.learning.evidence import project_evidence
from leornian.modules.learning.lessons import Lessons
from leornian.modules.learning.material_contracts import MaterialCitation
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.modules.tutor.learning_memory import LearningMemory
from leornian.modules.tutor.teaching_sessions import TeachingSessions
from leornian.shared_kernel.errors import BusinessError

UNAVAILABLE = {"not_found", "source_not_current", "stale_version", "precondition_failed"}


def excerpt(text, limit):
    """Offsets always refer to the original public string, including code newlines."""
    return {
        "text": text[:limit], "start": 0, "end": min(len(text), limit),
        "original_length": len(text), "truncated": len(text) > limit,
    }


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


class TeachingMemory:
    @staticmethod
    def _sources(connection, actor, goal_id, sources, citations):
        Knowledge(connection).current(actor, goal_id, [
            ref if isinstance(ref, SourceRef) else SourceRef(**{
                "source_id": ref["source_id"], "revision": ref["revision"],
            }) for ref in sources
        ])
        read_citations_in(connection, actor, goal_id, citations)

    @staticmethod
    def _turn(connection, actor, goal_id, row, delivery, node, run_id):
        if delivery and delivery["status"] != "accepted":
            return None
        manifest = delivery["context_manifest"] if delivery else {
            "sources": [ref.model_dump(mode="json") for ref in node.source_refs],
            "material_context_citations": [
                citation.model_dump(mode="json") for citation in node.material_citations
            ],
        }
        TeachingMemory._sources(
            connection, actor, goal_id, manifest.get("sources", []),
            manifest_citations(manifest),
        )
        text = row["assistant_text"]
        lesson = None
        if row["purpose"] == "lesson":
            lesson = Lessons(connection).for_run(actor, run_id) if run_id else None
            if not lesson:
                return None
            binding = row["context_focus"]
            if (
                str(lesson.plan_id) != binding.get("plan_id")
                or lesson.plan_revision != binding.get("expected_plan_revision")
                or lesson.node_key != node.key
                or {(source.source_id, source.revision) for source in lesson.sources}
                != {(source.source_id, source.revision) for source in node.source_refs}
            ):
                raise BusinessError("stale_version", "Remembered lesson belongs to another node.")
            TeachingMemory._sources(
                connection, actor, goal_id,
                [source.model_dump(mode="json") for source in lesson.sources],
                [citation for section in lesson.document.sections
                 for citation in section.material_citations],
            )
            text = lesson.document.introduction
        item = {
            "turn_id": str(row["id"]), "kind": row["purpose"],
            "completed_at": row["completed_at"].isoformat(),
            "focus": row["context_focus"], "excerpt": excerpt(text, 1000),
            "sources": manifest.get("sources", []),
            "material_citations": [
                citation.model_dump(mode="json") for citation in manifest_citations(manifest)
            ],
        }
        if row["learning_interaction"] and row["learning_interaction"].get("type") == "artifact":
            item["delivered_artifact"] = row["learning_interaction"]
        if lesson:
            item["lesson_id"] = str(lesson.id)
            item["material_citations"].extend(
                citation.model_dump(mode="json") for section in lesson.document.sections
                for citation in section.material_citations
            )
            item["section_count"] = len(lesson.document.sections)
            item["section_headings"] = [
                section.heading for section in lesson.document.sections[:12]
            ]
            item["sections"] = [
                {
                    "heading": section.heading,
                    "explanation": excerpt(section.explanation, 400),
                    "code_example": excerpt(section.code_example, 600),
                }
                for section in lesson.document.sections[:3]
            ]
        return item

    @staticmethod
    def _submission(connection, actor, fact):
        if fact.evidence_kind == "python_attempt":
            owner = PythonAssessment(connection)
            row = owner.row(actor, fact.source_receipt)
            if row["purpose"] != "training":
                return None
            attempt = owner.practice_public(row)
            answer = {"type": "python", "code": excerpt(attempt.code, 1800)}
        elif fact.evidence_kind == "program_attempt":
            owner = ProgramAssessment(connection)
            row = owner.row(actor, fact.source_receipt)
            if row["purpose"] != "training":
                return None
            attempt = owner.public(row)
            submitted = attempt.answer.model_dump(mode="json")
            answer = {"type": submitted["type"]}
            if "query" in submitted:
                answer["query"] = excerpt(submitted["query"], 1800)
            else:
                files = submitted["files"]
                answer["file_count"] = len(files)
                answer["file_index"] = [
                    {"path": file["path"], "read_only": file.get("read_only", False)}
                    for file in files
                ]
                answer["files"] = [
                    {"path": file["path"], "content": excerpt(file["content"], 800)}
                    for file in files[:6]
                ]
                answer["omitted_files"] = len(files) - len(answer["files"])
        else:
            return None
        result = {
            "source_owner": "assessment", "source_receipt": str(attempt.id),
            "pack_id": str(attempt.pack_id), "slot": attempt.slot,
            "node_key": fact.node_key, "plan_revision": fact.plan_revision,
            "state_kind": "submitted_snapshot", "answer": answer,
            "status": attempt.status, "attempt_number": attempt.attempt_number,
            "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
            "feedback": excerpt(attempt.feedback, 400) if attempt.feedback else None,
        }
        if fact.evidence_kind == "program_attempt":
            result["environment"] = attempt.environment.model_dump(mode="json")
        return result

    @staticmethod
    def _example_work(connection, actor, conversation, focus, nodes, accessible, before, branch_id,
                      run_ids, deliveries):
        from leornian.bootstrap.compositions import CompositionWorkflow
        from leornian.bootstrap.example_runs import ExampleRuns

        anchor = TeachingSessions(connection).branch(conversation.id, branch_id)[
            "anchor_artifact_id"
        ] if branch_id else None
        store = LearningArtifacts(connection)
        refs = store.teaching_example_refs(
            actor, conversation.id, focus, accessible, before.created_at, anchor,
        )
        shared = Execution(connection).shared_teaching_example(
            actor, conversation.id, {str(ref["id"]): ref["revision"] for ref in refs},
            before.created_at,
        )
        nearby = {node.key for node in nodes[-2:]} | set(nodes[-1].prerequisite_keys)
        shared_id = shared["artifact_id"] if shared else None
        for ref in sorted(refs, key=lambda item: str(item["id"]) != shared_id):
            use_shared = str(ref["id"]) == shared_id
            if not use_shared and (anchor or ref["node_key"] not in nearby):
                continue
            delivery = deliveries.get(run_ids.get(ref["source_turn_id"]))
            if not delivery or delivery["status"] != "accepted":
                continue
            scope = delivery["context_manifest"]
            try:
                TeachingMemory._sources(connection, actor, conversation.goal_id,
                                        scope.get("sources", []), manifest_citations(scope))
                artifact = store.row(actor, conversation.id, ref["id"])
                if artifact["revision"] != ref["revision"] or artifact["state"] != "ready":
                    continue
                presentation, _, _ = CompositionWorkflow.current(
                    connection, actor, conversation.id, artifact,
                )
            except BusinessError as error:
                if error.code not in UNAVAILABLE:
                    raise
                continue
            editors = ExampleRuns.editors(presentation)
            component_id = shared["component_id"] if use_shared else (
                editors[0] if len(editors) == 1 else None
            )
            if component_id not in editors:
                continue
            definition = presentation["definition"]
            component = next(item for item in definition["components"]
                             if item["id"] == component_id)
            code = shared["code"] if use_shared else definition["states"][
                component["props"]["state"]
            ]["value"]
            return {
                "basis": "shared_successful_run" if use_shared else "published_example",
                "node_key": ref["node_key"], "source_turn_id": str(ref["source_turn_id"]),
                "artifact_id": str(ref["id"]), "revision": ref["revision"],
                "component_id": component_id, "label": component["props"].get("label"),
                "code": excerpt(code, 6000),
                **({key: shared[key] for key in ("command_id", "language")} if use_shared else {}),
            }, scope
        return None, None

    @staticmethod
    def build_in(
        connection, actor, conversation, focus, *, plan=None, branch_id=None,
        before_turn_id=None, max_chars=18000, node_dialogue=False,
    ):
        store = LearningMemory(connection)
        owned = store.conversation(actor, conversation.id)
        if owned.goal_id != conversation.goal_id:
            raise BusinessError("not_found", "Learning memory goal not found.")
        stated = store.learner_stated(actor, conversation.id)
        before = PgTutorStore(connection).get_turn(
            conversation.id, before_turn_id,
        ) if before_turn_id else None
        if before_turn_id and not before:
            raise BusinessError("not_found", "Learning memory turn not found.")
        snapshot = {
            "version": 1, "binding": {
                "conversation_id": str(conversation.id), "goal_id": str(conversation.goal_id),
                "plan_id": str(focus.plan_id) if focus.plan_id else None,
                "plan_revision": focus.expected_plan_revision,
                "branch_id": str(branch_id) if branch_id else None,
            },
            "learner_stated": {
                "revision": stated["revision"],
                "facts": {
                    key: {
                        "value": excerpt(fact["value"], 500),
                        "source_turn_id": fact["source_turn_id"],
                        "source_quote": excerpt(fact["source_quote"], 400),
                    } for key, fact in stated["facts"].items()
                },
            },
            "delivered_teaching": [], "learner_messages": [], "assessment": {},
            "project_state": {"basis": "submitted_snapshots", "submissions": []},
            "unresolved": [], "omissions": {},
        }
        if focus.kind == "goal":
            return snapshot, TeachingMemory._manifest(snapshot)
        plan = plan or Plans(connection).get(actor, focus.plan_id)
        if (
            plan.id != focus.plan_id or plan.goal_id != conversation.goal_id
            or not plan.active or plan.active.revision != focus.expected_plan_revision
        ):
            raise BusinessError("stale_version", "Learning memory needs the exact active plan.")
        nodes = plan.active.document.nodes
        current = next((node for node in nodes if node.key == focus.node_key), None)
        if not current:
            raise BusinessError("not_found", "Learning memory node not found.")
        # Include prior route nodes and the current node, never future delivered branches.
        nodes = nodes[:nodes.index(current) + 1]
        accessible = {}
        omissions = Counter()
        for node in nodes:
            try:
                TeachingMemory._sources(
                    connection, actor, conversation.goal_id, node.source_refs,
                    node.material_citations,
                )
                accessible[node.key] = node
            except BusinessError as error:
                if error.code not in UNAVAILABLE:
                    raise
                omissions["unavailable_nodes"] += 1
        run_ids = Runs(connection).turn_run_ids(actor.id, conversation.id)
        deliveries = store.delivery_manifests(actor, run_ids.values())
        example_scope = None
        if node_dialogue and before:
            work, example_scope = TeachingMemory._example_work(
                connection, actor, conversation, focus, nodes, accessible, before, branch_id,
                run_ids, deliveries,
            )
            if work:
                snapshot["project_state"]["example_work"] = work
                snapshot["project_state"]["basis"] = "attributed_snapshots"
        by_node = {}
        counted = set()
        turns = store.delivered(
            actor, conversation.id, focus, branch_id=branch_id, before_turn_id=before_turn_id,
            node_dialogue=node_dialogue,
        )
        for row in turns:
            if row["purpose"] == "lesson" and row["lesson_request_id"]:
                request = Lessons(connection).get_request(actor, row["lesson_request_id"])
                if (
                    request.plan_id != plan.id or request.plan_revision != plan.active.revision
                ):
                    continue
                row = {**row, "context_focus": {
                    "kind": "node", "plan_id": str(request.plan_id),
                    "expected_plan_revision": request.plan_revision, "node_key": request.node_key,
                }}
            key = row["context_focus"].get("node_key")
            if key not in accessible:
                continue
            try:
                item = TeachingMemory._turn(
                    connection, actor, conversation.goal_id, row,
                    deliveries.get(run_ids.get(row["id"])), accessible[key], run_ids.get(row["id"]),
                )
            except BusinessError as error:
                if error.code not in UNAVAILABLE:
                    raise
                omissions["unavailable_deliveries"] += 1
                continue
            if not item:
                continue
            if node_dialogue and row["teaching_branch_id"]:
                item["branch_id"] = str(row["teaching_branch_id"])
            node = accessible[key]
            group = by_node.setdefault(key, {
                "node_key": key, "title": node.title,
                "delivered_count": 0, "extracts": [],
            })
            count_key = (key, row["purpose"], row["history_group"])
            if count_key not in counted:
                group["delivered_count"] += row["delivered_count"]
                counted.add(count_key)
            group["extracts"].append(item)
            if not row["teaching_intent_id"] and row["purpose"] == "teaching":
                snapshot["learner_messages"].append({
                    "turn_id": str(row["id"]), "node_key": key,
                    "kind": "learner_self_report", "excerpt": excerpt(row["user_text"], 400),
                })
        for group in by_node.values():
            group["extracts"] = [
                *[item for item in group["extracts"] if item["kind"] == "lesson"][-1:],
                *[item for item in group["extracts"] if item["kind"] == "teaching"][-2:],
            ]
        snapshot["delivered_teaching"] = list(by_node.values())

        facts = [
            fact for fact in AssessmentEvidence(connection, EvidenceContext(connection)).list(actor)
            if fact.plan_id == plan.id and fact.plan_revision == plan.active.revision
            and fact.node_key in accessible
            and (before is None or fact.occurred_at <= before.created_at)
        ]
        projection = project_evidence(facts)
        # Aggregates cover the entire scoped history; details preserve the latest receipt of
        # each original owner/slot, so a newer pass resolves that same earlier failure.
        latest = {}
        latest_issues = {}
        for fact in facts:
            latest[(fact.node_key, fact.pack_id, fact.slot, fact.evidence_kind)] = fact
            issue_key = (
                (fact.node_key, fact.dimension, fact.evidence_kind)
                if fact.evidence_kind in {"concept_gate", "new_context_transfer"}
                else (fact.node_key, fact.pack_id, fact.slot, fact.evidence_kind)
            )
            latest_issues[issue_key] = fact
        selected = sorted(latest.values(), key=lambda fact: fact.occurred_at, reverse=True)
        snapshot["assessment"] = {
            "dimensions": [item.model_dump(mode="json") for item in projection.dimensions],
            "total_receipts": len(facts),
            "recent_receipts": [fact.model_dump(mode="json") for fact in selected[:12]],
        }
        snapshot["unresolved"] = [
            {
                "source_receipt": str(fact.source_receipt), "node_key": fact.node_key,
                "outcome": fact.outcome, "dimension": fact.dimension,
                "kind": "execution_issue" if fact.outcome == "error" else "assessment_not_passed",
                "independence": fact.independence,
            }
            for fact in sorted(
                latest_issues.values(), key=lambda fact: fact.occurred_at, reverse=True,
            ) if fact.outcome in {"not_passed", "error"}
        ][:8]
        submission_scopes = {}
        for fact in selected:
            if fact.evidence_kind not in {"python_attempt", "program_attempt"}:
                continue
            try:
                pack = Packs(connection).row(actor, fact.pack_id)
                material = pack.get("material_context") or {}
                TeachingMemory._sources(
                    connection, actor, conversation.goal_id, pack["sources"],
                    [
                        MaterialCitation(**citation)
                        for field in ("origin_citations", "author_citations", "review_citations")
                        for citation in material.get(field, [])
                    ],
                )
                submission = TeachingMemory._submission(connection, actor, fact)
            except BusinessError as error:
                if error.code not in UNAVAILABLE:
                    raise
                omissions["unavailable_submissions"] += 1
                continue
            if submission:
                snapshot["project_state"]["submissions"].append(submission)
                submission_scopes[submission["source_receipt"]] = {
                    "sources": pack["sources"],
                    "material_context_citations": [
                        citation for field in (
                            "origin_citations", "author_citations", "review_citations",
                        ) for citation in material.get(field, [])
                    ],
                }
            if len(snapshot["project_state"]["submissions"]) >= 3:
                break
        # Curriculum is part of the same immutable PlanDocument, including old-plan None.
        curriculum = Plans(connection).curriculum_snapshot(
            actor, plan.id, plan_revision=plan.active.revision, node_key=focus.node_key,
        )
        if curriculum:
            try:
                TeachingMemory._sources(
                    connection, actor, conversation.goal_id, [],
                    [
                        MaterialCitation(**citation)
                        for text in curriculum["texts"]
                        for citation in text.get("material_citations", [])
                    ],
                )
                snapshot["curriculum"] = TeachingMemory._curriculum(curriculum, nodes, current)
            except BusinessError as error:
                if error.code not in UNAVAILABLE:
                    raise
                omissions["unavailable_curriculum"] += 1
        omissions["older_receipt_details"] = max(0, len(selected) - 12)
        snapshot["omissions"] = dict(omissions)
        TeachingMemory._fit(snapshot, current.prerequisite_keys, max_chars)
        return snapshot, TeachingMemory._manifest(snapshot, submission_scopes, curriculum,
                                                 example_scope)

    @staticmethod
    def _curriculum(curriculum, nodes, current):
        relevant = {current.key, *current.prerequisite_keys}
        return {
            "plan_id": curriculum["plan_id"], "plan_revision": curriculum["plan_revision"],
            "basis": curriculum.get("basis", "selected_materials"),
            "technologies": curriculum["technologies"][:8],
            "texts": [
                {
                    **{key: text.get(key) for key in (
                        "key", "title", "role", "edition", "source_url",
                    )},
                    "document_refs": list({
                        (
                            citation["ref"]["document_id"],
                            citation["ref"]["document_revision"],
                        ): {
                            "document_id": citation["ref"]["document_id"],
                            "document_revision": citation["ref"]["document_revision"],
                        } for citation in text.get("material_citations", [])
                    }.values())[:4],
                } for text in curriculum["texts"][:8]
            ],
            "project": {
                "title": curriculum["project"]["title"],
                "outcome": excerpt(curriculum["project"]["outcome"], 600),
                "conventions": curriculum["project"]["conventions"][:12],
                "state_kind": "planned_conventions_and_milestones",
            },
            "nodes": [
                {
                    "node_key": node.key,
                    "chapters": [chapter.model_dump(mode="json")
                                 for chapter in node.curriculum_chapters[:8]],
                    "planned_milestone": node.project_milestone,
                } for node in nodes if node.key in relevant
            ],
        }

    @staticmethod
    def require_current_in(connection, actor, goal_id, manifest):
        """Recheck the exact remembered sources before publishing an in-flight answer."""
        if ref := manifest.get("example_work"):
            row = LearningArtifacts(connection).row(
                actor, manifest["binding"]["conversation_id"], ref["artifact_id"],
            )
            if row["revision"] != ref["revision"] or row["state"] != "ready":
                raise BusinessError("stale_version", "The teaching example is no longer current.")
        TeachingMemory._sources(
            connection, actor, goal_id, manifest.get("sources", []),
            [MaterialCitation(**citation) for citation in manifest.get("material_citations", [])],
        )

    @staticmethod
    def _fit(snapshot, prerequisites, max_chars):
        # Keep context proportional: shorten text first, then drop lower-priority old details.
        # Each retained item keeps its exact reference and truncation information.
        priorities = set(prerequisites)
        snapshot["delivered_teaching"].sort(
            key=lambda group: (
                group["node_key"] in priorities, group["extracts"][-1]["completed_at"],
            ),
        )
        excerpts = []

        def collect(value):
            if isinstance(value, dict):
                if {"text", "start", "end", "original_length", "truncated"} <= value.keys():
                    excerpts.append(value)
                else:
                    for part in value.values():
                        collect(part)
            elif isinstance(value, list):
                for part in value:
                    collect(part)

        collect(snapshot)
        while encoded_size(snapshot) > max_chars:
            longest = max(excerpts, key=lambda item: len(item["text"]), default=None)
            if longest and len(longest["text"]) > 160:
                size = max(160, len(longest["text"]) // 2)
                longest.update(
                    text=longest["text"][:size], end=size,
                    truncated=longest["original_length"] > size,
                )
                continue
            candidates = [
                snapshot["learner_messages"], snapshot["assessment"].get("recent_receipts", []),
                snapshot["project_state"]["submissions"], snapshot["delivered_teaching"],
            ]
            target = next((items for items in candidates if len(items) > 1), None)
            if target is None:
                target = next((items for items in candidates if items), None)
            if target is None:
                if snapshot.get("curriculum") and not snapshot["curriculum"].get(
                    "omitted_for_budget",
                ):
                    snapshot["curriculum"] = {
                        "plan_id": snapshot["curriculum"]["plan_id"],
                        "plan_revision": snapshot["curriculum"]["plan_revision"],
                        "omitted_for_budget": True,
                    }
                    continue
                if snapshot["unresolved"]:
                    snapshot["unresolved"].pop()
                    continue
                if snapshot["learner_stated"]["facts"]:
                    snapshot["learner_stated"]["facts"].popitem()
                    continue
                if snapshot["project_state"].pop("example_work", None):
                    snapshot["project_state"]["basis"] = "submitted_snapshots"
                    snapshot["omissions"]["example_work_for_budget"] = 1
                    continue
                break
            target.pop(0 if target is snapshot["delivered_teaching"] else -1)
            snapshot["omissions"]["budget_items"] = snapshot["omissions"].get("budget_items", 0) + 1

    @staticmethod
    def _manifest(snapshot, submission_scopes=None, curriculum=None, example_scope=None):
        scopes = [
            {
                "sources": extract["sources"],
                "material_context_citations": extract["material_citations"],
            }
            for group in snapshot["delivered_teaching"] for extract in group["extracts"]
        ]
        scopes += [
            (submission_scopes or {}).get(item["source_receipt"], {})
            for item in snapshot["project_state"]["submissions"]
        ]
        work = snapshot["project_state"].get("example_work")
        if work and example_scope:
            scopes.append(example_scope)
        if snapshot.get("curriculum") and not snapshot["curriculum"].get("omitted_for_budget"):
            scopes.append({
                "material_context_citations": [
                    citation for text in (curriculum or {}).get("texts", [])
                    for citation in text.get("material_citations", [])
                ],
            })
        sources = {
            (str(ref["source_id"]), ref["revision"]): {
                "source_id": str(ref["source_id"]), "revision": ref["revision"],
            }
            for scope in scopes for ref in scope.get("sources", [])
        }
        citations = {
            citation.model_dump_json(): citation.model_dump(mode="json")
            for scope in scopes for citation in manifest_citations(scope)
        }
        return {
            "version": 1, "binding": snapshot["binding"],
            **({"example_work": {key: work[key] for key in ("artifact_id", "revision")}}
               if work else {}),
            "learner_requirements_revision": snapshot["learner_stated"]["revision"],
            "turn_ids": [
                extract["turn_id"] for group in snapshot["delivered_teaching"]
                for extract in group["extracts"]
            ],
            "receipt_ids": [
                fact["source_receipt"]
                for fact in snapshot["assessment"].get("recent_receipts", [])
            ],
            "submission_ids": [
                item["source_receipt"] for item in snapshot["project_state"]["submissions"]
            ],
            "lesson_ids": [
                extract["lesson_id"] for group in snapshot["delivered_teaching"]
                for extract in group["extracts"] if "lesson_id" in extract
            ],
            "sources": list(sources.values()), "material_citations": list(citations.values()),
            "omissions": snapshot["omissions"],
        }
