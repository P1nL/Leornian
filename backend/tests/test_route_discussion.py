import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_dynamic_plans import document
from test_teaching_delivery import body, drain, provider
from test_teaching_delivery import managed as managed
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.contracts import Receipt, RoleSpec
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.policies import estimate_tokens, fit_optional_history
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_consumers import prepare_consumer_in
from leornian.bootstrap.planning_materials import PlanningMaterials
from leornian.bootstrap.route_discussion import RouteDiscussionReply
from leornian.bootstrap.teaching_delivery import TeachingDelivery
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.learning.contracts import PlanDocument
from leornian.modules.tutor.contracts import PlanningInput
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.route_requirements import RouteRequirements
from leornian.shared_kernel.errors import BusinessError


def discuss(managed, session, workflow, text, route=None, revision=0, requirements=None, rag=None,
            ready=False):
    tutor, settings, conversation = managed
    start = route is not None
    if route is not None:
        route = {**route, "assumptions": []}
    with tutor.database.transaction(snapshot=True) as connection:
        saved = RouteRequirements(connection).get(conversation.id)
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(
            text=text, expected_revision=revision, discussion=True, start_plan=start,
            expected_requirements_revision=saved["revision"] if start and saved else None,
        ),
    )
    reply = {"text": "请补充每周可学习的时间。" if route is None
             else "已根据你的目标整理完整路线。", "route": route}
    if ready:
        reply["ready_for_route"] = True
    if requirements:
        reply["requirement_updates"] = [
            {"key": key, "value": value, "source_turn_id": str(accepted.turn_id),
             "source_quote": text}
            for key, value in requirements.items()
        ]
    if rag:
        reply["rag_intent"] = {
            **rag, "learner_evidence": [{
                "source_turn_id": str(accepted.turn_id), "source_quote": text,
            }],
        }
    gateway, sent, _ = provider(settings, author=json.dumps(reply))
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted"
    assert not sent[0].get("tools")
    assert "NOT a lesson tutor" in sent[0]["messages"][0]["content"]
    return accepted, sent, workflow.snapshot(session.token)


def test_discussion_clarifies_then_delivers_unconfirmed_route(managed, session, workflow):
    tutor, _, _ = managed
    _, _, first = discuss(
        managed, session, workflow, "零基础，想学习 Python。",
        requirements={"goal": "学习 Python", "prior_knowledge": "零基础"}, ready=True,
    )
    assert not first.plans and not first.teaching_sessions
    assert first.turns[0].turns[-1].assistant_text == "请补充每周可学习的时间。"
    _, sent, second = discuss(
        managed, session, workflow, "每周五小时，先做文件整理工具。", document(),
    )
    assert any("零基础" in message["content"] for message in sent[0]["messages"])
    assert any("请补充每周" in message["content"] for message in sent[0]["messages"])
    historical = [json.loads(message["content"]) for message in sent[0]["messages"]
                  if message["role"] == "assistant"]
    assert historical == [{"text": first.turns[0].turns[-1].assistant_text}]
    example, _ = json.JSONDecoder().raw_decode(
        sent[0]["messages"][0]["content"].split("Format-only JSON example: ", 1)[1],
    )
    RouteDiscussionReply.model_validate_json(json.dumps(example), strict=True)
    plan = second.plans[0]
    assert plan.active is None and len(plan.latest.document.nodes) == 2
    reply = second.turns[0].turns[-1].assistant_text
    assert all(
        node.title in reply and node.objective in reply for node in plan.latest.document.nodes
    )
    assert all(run.purpose == "planning" for run in second.runs)
    assert not second.teaching_sessions
    assert tutor.confirm_plan(session.token, plan.id, 1).active.revision == 1
    assert not workflow.snapshot(session.token).teaching_sessions


def test_model_first_route_reuses_course_state_without_waiting_for_optional_material(
    managed, session, workflow, monkeypatch,
):
    tutor, _settings, conversation = managed
    discuss(
        managed, session, workflow, "Learn Python by building a file organizer.",
        requirements={"goal": "Learn Python by building a file organizer."}, ready=True,
        rag={
            "action": "prepare", "goal": "Optional pathlib reference", "topics": ["file paths"],
            "reason": "A supplemental reference is useful for this goal.",
        },
    )

    def unnecessary_wait(*_args, **_kwargs):
        pytest.fail("A model-first route must not wait for an optional reference batch")

    monkeypatch.setattr(PlanningMaterials, "ready_in", unnecessary_wait)
    route = {
        **document(), "assumptions": [],
        "curriculum": {
            "basis": "model_knowledge", "technologies": [{"name": "Python", "version": None}],
            "texts": [], "project": {
                "title": "File organizer", "outcome": "Preview intended file moves.",
                "conventions": ["Keep the preview separate from file changes."],
            },
        },
    }
    route["nodes"][0]["project_milestone"] = "Preview directory entries."
    _accepted, sent, snapshot = discuss(
        managed, session, workflow, "Please create the complete route.", route,
    )
    assert len(sent) == 2 and len(snapshot.plans) == 1
    plan = snapshot.plans[0]
    assert plan.active is None
    assert plan.latest.document.curriculum.basis == "model_knowledge"
    assert plan.latest.document.curriculum.texts == []
    with tutor.database.transaction() as connection:
        assert len(MaterialIntake(connection).planning_batches(
            session.actor, conversation.goal_id,
        )) == 1
    confirmed = tutor.confirm_plan(session.token, plan.id, 1)
    assert confirmed.active.document.curriculum.project.conventions == (
        ["Keep the preview separate from file changes."]
    )
    assert not workflow.snapshot(session.token).teaching_sessions


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_blank_planning_output_has_a_diagnosed_repair_and_stops_without_progress(
    managed, session, repair_succeeds,
):
    original, settings, conversation = managed
    settings = replace(settings, model_thinking="enabled")
    tutor = TutorWorkflow(original.database, settings)
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="学习数据整理，每天半小时。", expected_revision=0, discussion=True),
    )
    reply = json.dumps({"text": "你希望整理哪类数据？", "route": None})
    gateway, sent, _ = provider(
        settings, author=lambda i: reply if repair_succeeds and i > 1 else " " * 545,
    )
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == ("accepted" if repair_succeeds else "blocked_protocol")
    assert len(sent) == (3 if repair_succeeds else 2)
    repair = json.loads(sent[1]["messages"][-1]["content"])
    assert repair["issues"][0]["code"] == "empty_model_response"
    assert "whitespace-only" in repair["issues"][0]["repair_instruction"]
    assert sent[1]["thinking"] == {"type": "enabled"}
    assert sent[1]["response_format"] == {"type": "json_object"}
    with tutor.database.transaction(snapshot=True) as connection:
        records = connection.execute(
            "SELECT response_body FROM runtime.external_calls WHERE run_id=%s ORDER BY step",
            (accepted.run_id,),
        ).fetchall()
    assert json.loads(records[0]["response_body"])["choices"][0]["message"]["content"] == " " * 545
    assert tutor.turn_history(session.token, conversation.id)[0].assistant_text == (
        "你希望整理哪类数据？" if repair_succeeds else None
    )


def test_route_repair_keeps_one_failed_response_after_the_unchanged_evidence_prefix():
    manifest = {"route_discussion": 1, "planning_requested": True}
    role = RoleSpec(
        policy_version="planner.v1", context_manifest=manifest,
        messages=[
            {"role": "system", "content": "Fixed planning contract."},
            {"role": "system", "content": "Exact planning evidence." * 100},
            {"role": "user", "content": "Please create the complete route."},
        ],
    )
    task = {
        "kind": "planning", "context_manifest": manifest, "fragments": [],
        "candidate": "Older rejected route." * 100, "repair_strategy": "diagnostic",
        "output_multiplier": 1,
    }
    missing = json.dumps({"text": "A primary source for TypeScript is missing."})
    malformed = '{"text":"The same source is still missing","route":null'
    baseline = TeachingDelivery.author_role(role, {**task, "issues": []}).messages
    prompts = []
    for raw in (missing, malformed):
        diagnostics = TeachingDelivery.candidate_diagnostics(task, raw)
        repaired = TeachingDelivery.author_role(role, {
            **task, "issues": [{
                "code": "invalid_delivery_candidate", "diagnostics": diagnostics,
                "previous_response": raw,
            }],
        })
        prompts.append(repaired.messages)
        payload = json.loads(repaired.messages[-1]["content"])
        assert repaired.messages[:-1] == baseline
        assert payload["issues"][0]["previous_response"] == raw
        assert "previous_candidate" not in payload
        assert "route=null" in payload["instruction"]
    assert prompts[0][:-1] == prompts[1][:-1]
    missing_issue = TeachingDelivery.candidate_diagnostics(task, missing)[0]
    syntax_issue = TeachingDelivery.candidate_diagnostics(task, malformed)[0]
    assert missing_issue["type"] == "missing_route_or_material_gaps"
    assert syntax_issue["type"] == "json_invalid" and syntax_issue["position"] > 0
    shifted = TeachingDelivery.candidate_diagnostics(task, ' ' * 20 + malformed)
    assert shifted[0]["position"] != syntax_issue["position"]
    assert TeachingDelivery.diagnostic_keys(shifted) == TeachingDelivery.diagnostic_keys(
        [syntax_issue],
    )


def test_route_repair_locates_reply_fields_misplaced_inside_a_large_route():
    task = {"kind": "planning", "fragments": [], "context_manifest": {
        "route_discussion": 1, "planning_requested": True, "planning_policy": "model-first.v1",
        "route_requirements": {"learner_stated": {"goal": {
            "value": "Learn file iteration", "source_turn_id": str(uuid4()),
            "source_quote": "Learn file iteration",
        }}},
    }}
    route = {**document(), "assumptions": []}
    malformed = (
        '{"text":"Draft","route":' + json.dumps(route)[:-1]
        + ',"material_gaps":[],"rag_intent":{"action":"none"}}'
    )
    diagnostics = TeachingDelivery.candidate_diagnostics(task, malformed)
    assert diagnostics[0]["type"] == "json_invalid"
    assert diagnostics[1]["path"] == ["route", "material_gaps"]
    assert "route LAST" in diagnostics[1]["message"]
    with pytest.raises(ValueError):
        TeachingDelivery.candidate(task, malformed)
    corrected = json.dumps({
        "text": "Draft", "material_gaps": [], "rag_intent": {"action": "none"}, "route": route,
    })
    validated = json.loads(TeachingDelivery.candidate(task, corrected))
    assert [node["key"] for node in validated["route"]["nodes"]] == ["paths", "organizer"]
    assert validated["material_gaps"] == []


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_requested_route_repairs_distinct_errors_and_stops_repeated_syntax_across_restart(
    managed, session, workflow, repair_succeeds,
):
    tutor, settings, conversation = managed
    discuss(
        managed, session, workflow, "学习 Python 文件整理。",
        requirements={"goal": "学习 Python 文件整理"}, ready=True,
    )
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(
            text="请制定完整路线。", expected_revision=0, discussion=True,
            start_plan=True, expected_requirements_revision=1,
        ),
    )
    missing = json.dumps({"text": "The route needs a suitable primary source."})
    malformed = '{"text":"Return a complete route","route":'
    responses = [
        missing, malformed,
        json.dumps({"text": "完整路线。", "route": {**document(), "assumptions": []}})
        if repair_succeeds else ' ' * 40 + malformed,
    ]
    gateway, sent, _ = provider(settings, author=lambda index: responses[index - 1])
    for _ in range(8):
        tutor = TutorWorkflow(tutor.database, settings)
        AgentLoop(tutor, gateway).run(accepted.run_id)
        result = tutor.delivery_task(session.token, accepted.delivery_task_id)
        if result.status in {"accepted", "blocked_protocol"}:
            break
    assert result.status == ("accepted" if repair_succeeds else "blocked_protocol")
    assert len(sent) == (4 if repair_succeeds else 3)
    assert sent[1]["messages"][:-1] == sent[2]["messages"][:-1]
    context = next(
        message["content"] for message in sent[0]["messages"]
        if message["role"] == "system"
        and message["content"].startswith("Planning context (data): ")
    )
    ordered = json.loads(context.split(": ", 1)[1])
    assert next(iter(ordered)) == "execution_environments"
    assert next(iter(ordered["execution_environments"])) == "recipes"
    assert list(ordered).index("rag_batches") < list(ordered).index("route_requirements")
    repairs = [json.loads(wire["messages"][-1]["content"]) for wire in sent[1:3]]
    assert repairs[0]["issues"][0]["diagnostics"][0]["type"] == (
        "missing_route_or_material_gaps"
    )
    assert repairs[1]["issues"][0]["diagnostics"][0]["type"] == "json_invalid"
    assert repairs[0]["issues"][0]["previous_response"] == missing
    assert repairs[1]["issues"][0]["previous_response"] == malformed
    assert all("previous_candidate" not in payload for payload in repairs)
    if repair_succeeds:
        assert len(workflow.snapshot(session.token).plans) == 1
    else:
        with tutor.database.transaction(snapshot=True) as connection:
            task = Deliveries(connection).for_run(accepted.run_id)
            assert task["issues"][0]["diagnostics"][0]["type"] == "json_invalid"
        AgentLoop(TutorWorkflow(tutor.database, settings), gateway).run(accepted.run_id)
        assert len(sent) == 3
        assert not workflow.snapshot(session.token).plans


def test_route_revisions_and_request_mode_keep_original_receipts(managed, session, workflow):
    tutor, _, conversation = managed
    discuss(
        managed, session, workflow, "学习路径处理，已有编程基础。",
        requirements={"goal": "学习路径处理", "prior_knowledge": "已有编程基础"}, ready=True,
    )
    accepted, _, first = discuss(managed, session, workflow, "先给我完整路线。", document())
    _, revision_calls, revised = discuss(
        managed, session, workflow, "加一点难度。", document(title="Revised route"), 1,
    )
    assert revised.plans[0].latest.revision == 2 and revised.plans[0].active is None
    with tutor.database.transaction() as connection:
        key = connection.execute(
            "SELECT idempotency_key FROM tutor.turns WHERE id=%s", (accepted.turn_id,),
        ).fetchone()["idempotency_key"]
        ids = Runs(connection).turn_run_ids(session.actor.id, conversation.id)
        assert ids[accepted.turn_id] == accepted.run_id
        assert Runs(connection).turn_run_ids(uuid4(), conversation.id) == {}
        assert Runs(connection).turn_run_ids(session.actor.id, uuid4()) == {}
        assert Deliveries(connection).accepted_plan_review(
            conversation.id, accepted.turn_id, {},
        ) is None
    with pytest.raises(BusinessError, match="mode changed"):
        tutor.submit_plan(session.token, conversation.id, key,
                          PlanningInput(text="先给我完整路线。", expected_revision=0))
    assert first.plans[0].latest.revision == 1
    reuse = json.loads(revision_calls[1]["messages"][-1]["content"])["plan_review_reuse"]
    assert set(reuse["reused_node_keys"]) == {node["key"] for node in document()["nodes"]}
    assert not reuse["affected_node_keys"]
    assert reuse["accepted_check_id"] and reuse["review_call_id"]


@pytest.mark.parametrize("planning_policy", [None, "model-first.v1"])
def test_discussion_proposals_reuse_plan_source_validation(planning_policy):
    route = document(sources=[{"source_id": str(uuid4()), "revision": 1}])
    route["assumptions"] = []
    task = {"kind": "planning", "context_manifest": {
        "route_discussion": 1, "planning_requested": True,
        "planning_policy": planning_policy,
    }, "fragments": []}
    with pytest.raises(ValueError, match="unsupported source"):
        TeachingDelivery.candidate(task, json.dumps({"text": "A route", "route": route}))


@pytest.mark.parametrize("stage", ["discussion", "plan_request", "material_gap", "complete_route"])
def test_route_review_contract_matches_the_current_stage(stage):
    reply = {"text": "Current-stage reply.", "route": None}
    if stage == "plan_request":
        reply.update(request_plan=True, plan_request_quote="Please create the plan.")
    if stage == "complete_route":
        reply["route"] = {**document(), "assumptions": []}
    task = {
        "kind": "planning", "candidate_call_id": uuid4(), "candidate": json.dumps(reply),
        "candidate_input": [], "issues": [], "output_multiplier": 1,
        "context_manifest": {
            "route_discussion": 1,
            "planning_requested": stage in {"material_gap", "complete_route"},
            "route_requirements": {"learner_stated": {}},
        },
    }
    role = TeachingDelivery.review_role(task)
    payload = json.loads(role.messages[-1]["content"])
    revised = TeachingDelivery.review_role({
        **task, "candidate_call_id": uuid4(),
        "candidate": json.dumps({**reply, "text": "Revised reply."}),
    })
    assert role.messages[-1]["content"].split('"candidate":')[0] == (
        revised.messages[-1]["content"].split('"candidate":')[0]
    )
    assert json.loads(revised.messages[-1]["content"])["candidate"] != payload["candidate"]
    assert payload["planning_stage"]["name"] == stage
    assert payload["planning_stage"]["route_required"] == (stage == "complete_route")
    if stage == "complete_route":
        assert {"goal_coverage", "prerequisites", "source_grounding"} <= set(
            payload["required_checks"],
        )
        assert "environment_recipes" in payload["execution_environment_checks"]
    else:
        assert not {"goal_coverage", "prerequisites", "source_grounding"} & set(
            payload["required_checks"],
        )
        assert "full-route coverage checks" in payload["route_requirement_checks"]
        if stage == "plan_request":
            assert "request_authorization" in payload["required_checks"]
            assert "route=null is REQUIRED" in payload["planning_stage"]["instruction"]


@pytest.mark.parametrize("discussion", [False, True])
@pytest.mark.parametrize("gaps", [[], ["A native build is not supported."]])
def test_route_review_preserves_environment_defaults_and_declared_gaps(discussion, gaps):
    route = PlanDocument.model_validate({
        **document(), "environment_recipes": ["typescript-standard.v1"],
        "environment_dependencies": [{
            "language": "typescript", "title": "Vue reading list", "build": "vite",
            "dependencies": [
                {"name": "vite", "version": "5.4.11"},
                {"name": "vue", "version": "3.5.13"},
                {"name": "@vitejs/plugin-vue", "version": "5.2.1"},
            ],
        }],
        "environment_gaps": gaps,
    })
    candidate = (
        RouteDiscussionReply(text="A route draft.", route=route).model_dump_json()
        if discussion else route.model_dump_json()
    )
    task = {
        "kind": "planning", "candidate_call_id": uuid4(), "candidate": candidate,
        "candidate_input": [], "issues": [], "output_multiplier": 1,
        "context_manifest": {"route_discussion": 1} if discussion else {},
    }
    normalized = json.loads(candidate)
    original_route = normalized["route"] if discussion else normalized
    assert ("environment_gaps" in original_route) == bool(gaps)

    role = TeachingDelivery.review_role(task)
    payload = json.loads(role.messages[-1]["content"])
    reviewed = json.loads(payload["candidate"])
    reviewed_route = reviewed["route"] if discussion else reviewed

    assert reviewed_route["environment_gaps"] == gaps
    assert reviewed_route["environment_recipes"] == original_route["environment_recipes"]
    assert reviewed_route["environment_dependencies"] == original_route["environment_dependencies"]
    assert PlanDocument.model_validate(reviewed_route) == route
    assert task["candidate"] == candidate
    assert "execution_environment_checks" in payload["required_checks"]


def test_material_wait_does_not_block_clarification_and_resumes_the_original_route_task(
    managed, session, workflow, monkeypatch,
):
    tutor, settings, conversation = managed
    ready = False

    def materials(*args, **kwargs):
        if not ready:
            raise BusinessError("material_pending", "official_material_preparation_pending")
        return None

    monkeypatch.setattr(
        "leornian.bootstrap.teaching_context.consumer_material_required_in", lambda *_: True,
    )
    monkeypatch.setattr(
        "leornian.bootstrap.material_consumers.consumer_material_required_in", lambda *_: True,
    )
    monkeypatch.setattr(
        "leornian.bootstrap.planning_materials.PlanningMaterials.ready_in", materials,
    )
    _, sent, first = discuss(
        managed, session, workflow, "I want to learn Python.",
        requirements={"goal": "Learn Python"}, ready=True,
        rag={"action": "prepare", "goal": "Python beginner file tools", "topics": ["file paths"],
             "reason": "Prepare a first useful learning-direction batch."},
    )
    assert len(sent) == 2 and not first.plans
    assert "material_preparation" not in planning_context(sent[0]["messages"])
    assert not planning_context(sent[0]["messages"])["rag_batches"]["batches"]

    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Beginner, five hours a week. Please draft the complete route.",
                      expected_revision=0, discussion=True, start_plan=True,
                      expected_requirements_revision=1),
    )
    gateway, calls, _ = provider(settings, author=json.dumps({
        "text": "The route draft is ready; check the required dependency compatibility.",
        "route": {**document(), "assumptions": []}, "ready_for_route": True,
        "material_gaps": ["Confirm compatibility of the explicitly required dependency."],
    }))
    waiting = drain(tutor, settings, accepted, gateway, session.token)
    assert waiting.status == "waiting_dependency" and len(calls) == 2
    review_payload = json.loads(calls[-1]["messages"][-1]["content"])
    assert review_payload["planning_stage"]["name"] == "material_gap"
    with tutor.database.transaction() as connection:
        task = Deliveries(connection).for_run(accepted.run_id)
        draft = task["context_manifest"]["planning_route_draft"]
        demand = MaterialIntake(connection).demand(
            session.actor, task["context_manifest"]["material_demand"]["id"],
        )
        assert demand.goal_text == "confirm compatibility of the explicitly required dependency."
        assert [node["key"] for node in draft["nodes"]] == ["paths", "organizer"]
    assert tutor.resume_delivery(session.token, accepted.delivery_task_id).status == (
        "waiting_dependency"
    )
    pending = workflow.snapshot(session.token)
    assert len(calls) == 2 and not pending.plans
    assert pending.turns[0].turns[-1].assistant_text is None
    assert pending.turns[0].turns[-1].stage_replies == []
    assert any(
        step.title == "等待RAG解析" and step.status == "waiting"
        for step in pending.turns[0].turns[-1].thinking_steps
    )

    ready = True
    tutor.resume_delivery(session.token, accepted.delivery_task_id)
    gateway, resumed, _ = provider(settings, author=json.dumps({
        "text": "Here is the complete route.", "route": {**document(), "assumptions": []},
    }))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert "material_preparation" not in planning_context(resumed[0]["messages"])
    assert planning_context(resumed[0]["messages"])["route_draft"] == draft
    final = workflow.snapshot(session.token)
    assert len(final.turns[0].turns) == 2
    assert final.turns[0].turns[-1].id == accepted.turn_id
    assert final.turns[0].turns[-1].stage_replies == []
    assert final.plans[0].active is None


def planning_context(messages):
    return json.loads(next(
        message["content"].removeprefix("Planning context (data): ")
        for message in messages if message["content"].startswith("Planning context (data): ")
    ))


@pytest.mark.parametrize("newer_request", [False, True])
def test_ready_materials_automatically_resume_a_diagnosed_original_route_without_new_messages(
    managed, session, workflow, monkeypatch, newer_request,
):
    tutor, settings, conversation = managed
    ready = False

    def materials(*_args, **_kwargs):
        if not ready:
            raise BusinessError("material_pending", "approved_source_required")

    monkeypatch.setattr(
        "leornian.bootstrap.teaching_context.consumer_material_required_in", lambda *_: True,
    )
    monkeypatch.setattr(
        "leornian.bootstrap.material_consumers.consumer_material_required_in", lambda *_: True,
    )
    monkeypatch.setattr(
        "leornian.bootstrap.planning_materials.PlanningMaterials.ready_in", materials,
    )
    monkeypatch.setattr(
        "leornian.bootstrap.planning_materials.PlanningMaterials.blockage_in",
        lambda *_: None if ready else SimpleNamespace(
            status="waiting_config", reason_code="approved_source_required",
        ),
    )
    discuss(
        managed, session, workflow, "学习 Java 后端开发，每周十小时。",
        requirements={"goal": "Java 后端开发"}, ready=True,
        rag={"action": "prepare", "goal": "Java backend", "topics": ["Maven", "Spring Boot"],
             "reason": "The learner requested this direction."},
    )
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="请制定完整路线。", expected_revision=0, discussion=True,
                      start_plan=True, expected_requirements_revision=1),
    )
    gateway, initial_calls, _ = provider(settings, author=json.dumps({
        "text": "Check the learner-required framework compatibility.",
        "route": {**document(), "assumptions": []},
        "material_gaps": ["Confirm compatibility of the learner-required framework."],
    }))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "waiting_input"
    assert len(initial_calls) == 2
    blocked = tutor.turn_history(session.token, conversation.id)[0]
    assert blocked.planning_state.material_blocked and blocked.completed_at
    with tutor.database.transaction() as connection:
        task = Deliveries(connection).for_run(accepted.run_id)
        assert task["context_manifest"]["awaiting_route_materials"]
        assert task["context_manifest"]["material_demand"]["id"] == str(blocked.material_demand_id)
    ready = True
    if newer_request:
        tutor.submit_plan(
            session.token, conversation.id, str(uuid4()),
            PlanningInput(text="先调整一下项目目标。", expected_revision=0, discussion=True),
        )
        with tutor.database.transaction() as connection:
            Deliveries(connection).material_ready(blocked.material_demand_id)
            assert Deliveries(connection).for_run(accepted.run_id)["status"] == "waiting_input"
        with pytest.raises(BusinessError, match="更新的路线请求"):
            tutor.resume_delivery(session.token, accepted.delivery_task_id)
        return
    with tutor.database.transaction() as connection:
        Deliveries(connection).material_ready(blocked.material_demand_id)
        assert Deliveries(connection).for_run(accepted.run_id)["status"] == "waiting_dependency"
    tutor.reconcile_deliveries()
    gateway, resumed_calls, _ = provider(settings, author=json.dumps({
        "text": "完整路线已经整理完成。", "route": {**document(), "assumptions": []},
    }))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    final = workflow.snapshot(session.token)
    turns = next(page.turns for page in final.turns if page.conversation_id == conversation.id)
    assert len(turns) == 2 and turns[-1].id == accepted.turn_id
    assert not turns[-1].planning_state.material_blocked
    assert len(resumed_calls) == 2 and final.plans[0].active is None
    with pytest.raises(BusinessError, match="已经交付"):
        tutor.resume_delivery(session.token, accepted.delivery_task_id)


def test_requirements_survive_history_trimming_and_explicit_changes(managed, session, workflow):
    tutor, _, conversation = managed
    first, _, _ = discuss(
        managed, session, workflow, "零基础，每天只能学习十五分钟。",
        requirements={"availability": "每天十五分钟", "prior_knowledge": "零基础"},
    )
    second, sent, _ = discuss(
        managed, session, workflow, "现在改为每天三十分钟。",
        requirements={"availability": "每天三十分钟"},
    )
    author = sent[0]["messages"]
    context = planning_context(author)
    old_facts = context["route_requirements"]["learner_stated"]
    assert old_facts["availability"]["value"] == "每天十五分钟"
    review = json.loads(sent[1]["messages"][-1]["content"])
    assert review["route_requirements"] == context["route_requirements"]
    assert "merged requirements" in review["route_requirement_checks"]

    third = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="我们继续讨论内容范围。", expected_revision=0, discussion=True),
    )
    role = tutor.context(tutor.claim(third.run_id))
    facts = planning_context(role.messages)["route_requirements"]["learner_stated"]
    assert facts["availability"]["value"] == "每天三十分钟"
    assert facts["availability"]["source_turn_id"] == str(second.turn_id)
    assert facts["prior_knowledge"]["source_turn_id"] == str(first.turn_id)
    request = {"messages": role.messages}
    fitted = fit_optional_history(
        request, role.optional_history, {"input_limit": estimate_tokens(request)},
    )
    assert fitted["messages"] == role.messages
    assert planning_context(fitted["messages"])["route_requirements"]["learner_stated"] == facts


def test_requirement_updates_need_frozen_learner_evidence():
    turn_id = str(uuid4())
    task = {"kind": "planning", "fragments": [], "context_manifest": {
        "route_discussion": 1,
        "route_requirements": {"revision": 0, "learner_stated": {},
                               "learner_messages": [{"turn_id": turn_id, "text": "每天十五分钟"}]},
    }}
    change = {"key": "availability", "value": "每天十五分钟",
              "source_turn_id": str(uuid4()), "source_quote": "每天十五分钟"}
    reply = {"text": "请补充学习基础。", "requirement_updates": [change]}
    with pytest.raises(ValueError, match="exact supplied learner"):
        TeachingDelivery.candidate(task, json.dumps(reply))
    change.update(source_turn_id=turn_id, source_quote="每天三十分钟")
    with pytest.raises(ValueError, match="exact supplied learner"):
        TeachingDelivery.candidate(task, json.dumps(reply))


def test_plan_button_requires_checked_information_and_a_quoted_message_can_start(
    managed, session, workflow,
):
    tutor, settings, conversation = managed
    with pytest.raises(BusinessError, match="补齐"):
        tutor.submit_plan(
            session.token, conversation.id, str(uuid4()),
            PlanningInput(
                text="制定计划", expected_revision=0, discussion=True, start_plan=True,
                expected_requirements_revision=1,
            ),
        )
    _, _, snapshot = discuss(
        managed, session, workflow, "I know basic syntax and want to learn file iteration.",
        requirements={"goal": "Learn file iteration", "prior_knowledge": "Know basic syntax"},
        rag={
            "action": "prepare", "goal": "Learn file iteration; library choice pending.",
            "topics": ["File iteration", "Iterating over files"], "reason": "Initial discovery.",
        },
        ready=True,
    )
    assert snapshot.turns[0].turns[-1].planning_state.information_complete
    original = snapshot.runs[-1].id
    assert tutor.get(session.token, original).status == "succeeded"
    discuss(
        managed, session, workflow, "Use pathlib for this project.",
        requirements={"included_scope": "Use pathlib for this project"}, ready=True,
    )
    text = "No other requirements. Please create the plan."
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text=text, expected_revision=0, discussion=True),
    )
    gateway, calls, _ = provider(settings, author=json.dumps({
        "text": "Preparing your requested plan.", "ready_for_route": True,
        "request_plan": True, "plan_request_quote": text,
    }))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "waiting_dependency"
    waiting = workflow.snapshot(session.token).turns[0].turns[-1]
    assert waiting.planning_requested and waiting.assistant_text is None
    assert not waiting.stage_replies and len(calls) == 2
    assert waiting.planning_state.material_topics == []
    with tutor.database.transaction(snapshot=True) as connection:
        demand = PlanningMaterials.for_turn_in(connection, session.actor, conversation, waiting)
    assert demand.preparation == "initial"
    assert waiting.planning_state.material_goal == (
        "Learning goal: Learn file iteration\nIncluded scope: Use pathlib for this project"
    )
    assert "Current planning_requested=false: route MUST be null" in (
        calls[0]["messages"][0]["content"]
    )
    tutor.resume_delivery(session.token, accepted.delivery_task_id)
    gateway, followup_calls, _ = provider(settings, author=json.dumps({
        "text": "Your plan.", "route": {**document(), "assumptions": []},
    }))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert "Current planning_requested=true: return the complete requested route" in (
        followup_calls[0]["messages"][0]["content"]
    )


def test_rejected_candidate_does_not_publish_requirements(managed, session):
    tutor, settings, conversation = managed
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="每天十五分钟。", expected_revision=0, discussion=True),
    )
    revisions = []

    def author(_):
        with tutor.database.transaction() as connection:
            saved = RouteRequirements(connection).get(conversation.id)
            revisions.append(saved["revision"] if saved else 0)
        return json.dumps({
            "text": "请补充基础。" if len(revisions) == 1 else "先确认一下目前的学习基础。",
            "requirement_updates": [{
                "key": "availability", "value": "每天十五分钟",
                "source_turn_id": str(accepted.turn_id), "source_quote": "每天十五分钟",
            }],
        })

    gateway, _, _ = provider(settings, author=author, reject=1)
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert revisions == [0, 0]
    with tutor.database.transaction() as connection:
        saved = RouteRequirements(connection).get(conversation.id)
    assert saved["revision"] == 1
    assert saved["learner_stated"]["availability"]["value"] == "每天十五分钟"


def test_checked_material_intents_reuse_the_same_scope_and_only_add_new_topics(
    managed, session, workflow,
):
    tutor, _, conversation = managed
    intent = {"action": "prepare", "goal": "Relational querying", "topics": ["Filtering"],
              "reason": "The learner has supplied a useful direction."}
    first, _, _ = discuss(
        managed, session, workflow, "I want to learn relational querying.", rag=intent,
    )
    with tutor.database.transaction() as connection:
        earlier = PgTutorStore(connection).get_turn(conversation.id, first.turn_id)
        legacy = prepare_consumer_in(
            connection, session.actor, conversation, earlier, "planning", earlier.context_focus,
        )
    repeated, _, _ = discuss(
        managed, session, workflow, "I want to learn relational querying.",
        rag={**intent, "goal": " relational   querying "},
    )
    extra, _, _ = discuss(
        managed, session, workflow, "Add indexes.",
        rag={**intent, "action": "supplement", "topics": ["Indexes"]},
    )
    with tutor.database.transaction() as connection:
        store = PgTutorStore(connection)
        one = store.get_turn(conversation.id, first.turn_id)
        two = store.get_turn(conversation.id, repeated.turn_id)
        three = store.get_turn(conversation.id, extra.turn_id)
        batches = MaterialIntake(connection).planning_batches(session.actor, conversation.goal_id)
        assert MaterialIntake(connection).demand(session.actor, legacy.id).status == "cancelled"
        assert MaterialIntake(connection).demand(
            session.actor, one.material_demand_id,
        ).status == "cancelled"
    assert one.material_demand_id == two.material_demand_id
    assert three.material_demand_id != one.material_demand_id
    assert [batch.preparation for batch in batches] == ["incremental"]
    assert batches[0].goal_text == "relational querying\nindexes"
    assert three.planning_state.material_goal == one.planning_state.material_goal
    assert three.planning_state.material_topics == ["Filtering", "Indexes"]
    returned, _, _ = discuss(
        managed, session, workflow, "Return to filtering.", rag=intent,
    )
    with tutor.database.transaction() as connection:
        latest = PgTutorStore(connection).get_turn(conversation.id, returned.turn_id)
        assert latest.material_demand_id != one.material_demand_id
        assert MaterialIntake(connection).demand(
            session.actor, one.material_demand_id,
        ).status == "cancelled"
        assert [item.id for item in MaterialIntake(connection).planning_batches(
            session.actor, conversation.goal_id,
        )] == [latest.material_demand_id]


def test_exhausted_material_reply_uses_real_search_receipts_and_needs_no_learner_repair(
    managed, session, monkeypatch,
):
    tutor, _settings, conversation = managed
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Please make the route.", expected_revision=0, discussion=True),
    )
    monkeypatch.setattr(
        PlanningMaterials, "blockage_in",
        staticmethod(lambda *_: SimpleNamespace(
            status="waiting_dependency", reason_code="material_discovery_exhausted",
        )),
    )
    monkeypatch.setattr(
        MaterialSources, "discovery",
        lambda *_args, **_kwargs: SimpleNamespace(
            id=uuid4(), missing_facets=["Version compatibility"],
        ),
    )
    with tutor.database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{uuid4()}",
            MaterialDemandInput(
                goal_id=conversation.goal_id, purpose="planning", scope_mode="teaching_goal",
                goal_text="Plan the requested learning direction",
            ),
        )
        PgTutorStore(connection).bind_material_demand(accepted.turn_id, demand.id)
        run = connection.execute(
            "SELECT * FROM runtime.runs WHERE id=%s", (accepted.run_id,),
        ).fetchone()
        task = Deliveries(connection).for_run(accepted.run_id)
        assert tutor._planning_wait(connection, session.actor, run, task, demand)
    reply = tutor.turn_history(session.token, conversation.id)[0].assistant_text
    assert "本轮没有已完成的联网补搜回执" in reply
    assert "已尝试目录候选、公开替代来源和定向补搜" not in reply
    summary = tutor.delivery_task(session.token, accepted.delivery_task_id)
    assert summary.reason_code == "material_discovery_exhausted"
    assert not summary.required_input and not summary.can_resume


def test_legacy_swallowed_reply_is_recovered_for_review_without_replaying_the_author(
    managed, session, workflow, monkeypatch,
):
    tutor, settings, conversation = managed

    def waiting(*_args, **_kwargs):
        raise BusinessError("material_pending", "official_material_preparation_pending")

    monkeypatch.setattr(
        "leornian.bootstrap.teaching_context.consumer_material_required_in", lambda *_: True,
    )
    monkeypatch.setattr(
        "leornian.bootstrap.material_consumers.consumer_material_required_in", lambda *_: True,
    )
    monkeypatch.setattr("leornian.bootstrap.teaching_context.ensure_consumer_material_in", waiting)
    monkeypatch.setattr(
        "leornian.bootstrap.material_consumers.ensure_consumer_material_in", waiting,
    )
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(
            text="Learn relational querying. Please draft the route.",
            expected_revision=0, discussion=True,
        ),
    )
    with tutor.database.transaction() as connection:
        turn = PgTutorStore(connection).get_turn(conversation.id, accepted.turn_id)
        prepare_consumer_in(
            connection, session.actor, conversation, turn, "planning", turn.context_focus,
            session_digest=Identity.digest(session.token),
        )
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    gateway, sent, _ = provider(settings, author=lambda _: pytest.fail("Author was replayed"))
    policy = gateway.policy(role)
    request = gateway.request(role.messages, require_tool=False, allowed_tools=(), policy=policy)
    prepared = tutor.prepare(lease, gateway.endpoint, request, policy, role.context_manifest)
    assert tutor.dispatch(lease, prepared.id)
    text = "The requirements are clear. I am preparing the agreed references."
    tutor.record(prepared.id, Receipt(body=json.dumps(body(json.dumps({
        "text": text, "route": None, "ready_for_route": True,
        "requirement_updates": [{
            "key": "goal", "value": "Learn relational querying",
            "source_turn_id": str(accepted.turn_id),
            "source_quote": "Learn relational querying",
        }],
    }))), http_status=200))
    with tutor.database.transaction() as connection:
        runs = Runs(connection)
        row = runs.lock(accepted.run_id)
        runs.applied(prepared.id)
        Deliveries(connection).await_route_materials(accepted.delivery_task_id)
        runs.messages(accepted.run_id, [])
        tutor._finish(connection, row, "failed", "material_pending")
    assert tutor.resume_delivery(session.token, accepted.delivery_task_id).status == "checking"
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert len(sent) == 1 and "Independently review" in sent[0]["messages"][0]["content"]
    turn = workflow.snapshot(session.token).turns[0].turns[-1]
    assert turn.assistant_text == text and not turn.stage_replies
    tutor.reconcile_deliveries()
    assert len(sent) == 1 and tutor.get(session.token, accepted.run_id).status == "succeeded"
