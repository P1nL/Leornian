import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_composition_practice import definition_for
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_program_practice import observed_environments as observed_environments
from test_program_practice import owned_claim, publish, receipt, submission
from test_program_practice import program_setup as program_setup
from test_program_runner import runner as runner
from test_python_execution import owned_claim as claim_sample
from test_teaching_delivery import body, drain, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.compositions import CompositionWorkflow
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionCancelRunAction,
    CompositionRespondAction,
)
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.learning_artifact_contracts import CancelAction, LearningCandidateInput
from leornian.modules.tutor.program_interaction_contracts import CompositionProgramRunAction
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def program_composition(database, session, program_setup):
    programs, accepted, (_, _, settings, plan, _), document, _ = program_setup
    publish(database, session, program_setup)
    settings = replace(
        settings, delivery_enabled=True, model_context_tokens=128000,
        model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, plan.goal_id)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="loops",
    )
    with database.transaction() as connection:
        source = LearningArtifactWorkflow.candidates_in(
            connection, session.actor, conversation.id, focus, programs=True,
        )["items"][0]
    return {
        "programs": programs, "pack": accepted, "settings": settings, "tutor": tutor,
        "conversation": conversation, "focus": focus, "source": source, "document": document,
        "flow": LearningArtifactWorkflow(database),
    }


def program_definition(source):
    task = source["presentation"]["task"]
    state = (
        {"type": "code", "value": task["starter_query"]}
        if task["language"] == "sql_query" else {"type": "files", "files": task["files"]}
    )
    return {
        "schema_version": "learning_composition.v2", "title": "Exact local program practice",
        "states": {"editor": state},
        "components": [
            {"id": "editor", "component": "CodeEditor", "props": {
                "label": "Published starter", "state": "editor",
            }},
            {"id": "feedback", "component": "ResultFeedback", "props": {
                "label": "Original result", "for_component": "editor",
            }},
            {"id": "run", "component": "ArtifactAction", "props": {
                "label": "Run explicitly", "event": "check_code", "for_component": "editor",
            }},
        ],
    }


def introduce_program(
    session, setup, *, mutate=None, conflict=None, extra_source=None, allow_practice=True,
):
    key = str(uuid4())
    data = TurnInput(
        text="Introduce the exact published SQL/project practice without running it.",
        focus=setup["focus"], presentation_capabilities={
            "versions": ["learning_composition.v2"],
            "actions": ["learning_programs.v1"] + (
                ["learning_practice.v2"] if extra_source and allow_practice else []
            ),
        },
    )
    accepted = setup["tutor"].submit(session.token, setup["conversation"].id, key, data)
    preparations, calls, sources = [], [], []

    def tool(name, args):
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": name, "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }]}, "finish_reason": "tool_calls",
        }]})

    def handle(request):
        wire = json.loads(request.content)
        calls.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            if conflict:
                conflict()
            return httpx.Response(200, json=body(json.dumps(report(
                json.loads(wire["messages"][-1]["content"])
            ))))
        if wire["messages"][-1]["role"] != "tool":
            return tool("list_learning_program_candidates", {})
        result = json.loads(wire["messages"][-1]["content"])
        if "items" in result:
            if extra_source and not sources:
                sources.append(next(
                    item for item in result["items"] if item["id"] == setup["source"]["id"]
                ))
                return tool("list_learning_artifact_candidates", {})
            source = sources[0] if sources else next(
                item for item in result["items"] if item["id"] == setup["source"]["id"]
            )
            args = {
                "command_key": "exact-program-composition",
                "definition": program_definition(source),
                "owner_bindings": [{"component_id": "editor", "candidate_id": source["id"]}],
            }
            if extra_source:
                extra = next(item for item in result["items"] if item["id"] == str(extra_source.id))
                additional = definition_for(extra)
                for node in additional["components"]:
                    if node["id"] != "response":
                        node["id"] = "choice_" + node["id"]
                args["definition"]["states"]["response"] = additional["states"]["response"]
                args["definition"]["components"].extend(additional["components"])
                args["owner_bindings"].append({
                    "component_id": "response", "candidate_id": extra["id"],
                })
            if mutate:
                mutate(args)
            return tool("prepare_learning_program_composition", args)
        preparations.append(result)
        return httpx.Response(200, json=body(json.dumps({
            "text": "Use the fixed task and environment; run only with your explicit action.",
            "interaction": {
                "type": "artifact", "exact_handle": result["candidate"]["id"],
                "intent": "introduce_only",
            } if result["status"] == "completed" else {"type": "none"},
        })))

    gateway = ChatCompletionsGateway(setup["settings"], httpx.MockTransport(handle))
    task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
    return task, accepted, preparations, calls, key, data


def current_program(session, setup):
    summary = setup["flow"].list_v2(session.token, setup["conversation"].id)[0]
    return setup["flow"].get_v2(
        session.token, summary.conversation_id, summary.id,
        program_capability="learning_programs.v1",
    )


def run_program(session, setup, *, wrong=False, parent=None, retry=False, changed=False):
    view = current_program(session, setup)
    data = submission(
        setup["document"]["items"][0], wrong=wrong, parent=parent, retry=retry, changed=changed,
    )
    action = CompositionProgramRunAction(
        action="run_program_component", component_id="editor", client_action_id=uuid4(),
        expected_artifact_revision=view.revision, payload=data.model_dump(exclude={"slot"}),
    )
    return action


@pytest.mark.parametrize("program_setup", [
    ("sql_query", "sqlite"), ("python_project", None),
], indirect=True)
def test_program_candidate_checked_delivery_actions_original_owners_and_reader_negotiation(
    database, session, workflow, program_composition,
):
    setup = program_composition
    task, accepted, preparations, calls, key, turn = introduce_program(session, setup)
    assert task.status == "accepted" and len(calls) == 4
    assert preparations[0]["candidate"]["kind"] == "learning_composition"
    view = current_program(session, setup)
    binding = view.component_bindings[0]
    assert binding.source.kind in {"sql_workspace", "project_workspace"}
    assert binding.state == "ready" and binding.result is None
    assert binding.allowed_actions == ["run"]
    assert "tests" not in binding.source.presentation.task.model_dump()
    assert setup["tutor"].submit(session.token, view.conversation_id, key, turn) == accepted
    with pytest.raises(BusinessError, match="support changed"):
        setup["tutor"].submit(
            session.token, view.conversation_id, key, turn.model_copy(update={
                "presentation_capabilities": turn.presentation_capabilities.model_copy(
                    update={"actions": []},
                ),
            }),
        )
    with database.transaction() as connection:
        assert not connection.execute(
            "SELECT 1 FROM assessment.program_attempts WHERE actor_id=%s AND purpose='training'",
            (session.actor.id,),
        ).fetchone()
        frozen = Runs(connection).lock(accepted.run_id)["tool_contracts"]
        assert frozen["prepare_learning_program_composition"] == 1
        assert "prepare_learning_practice_composition" not in frozen
    client = TestClient(create_app(setup["settings"]))
    path = f"/v2/conversations/{view.conversation_id}/learning-artifacts/{view.id}"
    headers = {"Authorization": "Bearer " + session.token}
    assert client.get(path, headers=headers).status_code == 409
    assert client.get(
        path, headers=headers, params={"program_capability": "learning_programs.v1"},
    ).status_code == 200
    action = run_program(session, setup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: setup["flow"].action(session.token, view.conversation_id, view.id, action),
            range(2),
        ))
    assert results[0] == results[1] and results[0].component_state == "running"
    queued = current_program(session, setup)
    attempt = queued.component_bindings[0].result
    assert attempt.status == "queued" and queued.state == "running"
    claim = owned_claim(database, session, attempt.id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    completed = current_program(session, setup)
    result = completed.component_bindings[0].result
    assert completed.state == "completed" and result.status == "passed"
    assert result.sample_result is not None
    assert setup["programs"].attempt(session.token, attempt.id) == result
    assert completed.component_bindings[0].attempts.attempts == [result]
    recovered = client.get(path + f"/actions/{action.client_action_id}", headers=headers)
    assert recovered.json()["result_id"] == str(attempt.id)
    replay = client.post(path + "/actions", headers=headers, json=action.model_dump(mode="json"))
    assert replay.status_code == 200 and replay.json() == recovered.json()
    assert current_program(session, setup).revision == completed.revision
    body = {
        "command_id": str(uuid4()), "component_id": "editor",
        "expected_artifact_revision": completed.revision,
        "answer": result.answer.model_dump(mode="json"),
    }
    endpoint = path + "/example-runs"
    assert client.post(endpoint, headers=headers, json=body).status_code == 202
    sample = claim_sample(database, session)
    if result.answer.type == "sql":
        assert sample.program.datasets == [binding.source.presentation.task.sample.dataset]
    else:
        assert sample.program.inputs == [binding.source.presentation.task.sample.input]
    with pytest.raises(BusinessError, match="自由练习"):
        setup["flow"].action(session.token, view.conversation_id, view.id,
                             run_program(session, setup, parent=attempt.id))
    assert current_program(session, setup) == completed
    assert not workflow.snapshot(session.token).node_progress
    external = setup["programs"].submit_practice(
        session.token, setup["pack"].pack_id, str(uuid4()),
        submission(setup["document"]["items"][0], parent=attempt.id, changed=True),
    )
    assert current_program(session, setup).component_bindings[0].result.id == external.id
    assert setup["programs"].attempt(session.token, attempt.id) == result
    setup["programs"].cancel(session.token, external.id)


@pytest.mark.parametrize("allow_practice", [True, False])
def test_mixed_program_and_choice_keep_separate_capabilities_and_original_owners(
    database, session, program_composition, learning_setup, allow_practice,
):
    setup = program_composition
    extra = setup["flow"].candidate(
        session.token, setup["conversation"].id, LearningCandidateInput(
            pack_id=learning_setup["pack"].pack_id, slot="practice_1",
        ),
    )
    task, _, preparations, _, _, _ = introduce_program(
        session, setup, extra_source=extra, allow_practice=allow_practice,
    )
    assert task.status == "accepted"
    if not allow_practice:
        assert preparations[0]["status"] != "completed"
        assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
        return
    assert preparations[0]["status"] == "completed"
    view = current_program(session, setup)
    assert {binding.source.kind for binding in view.component_bindings} == {
        "sql_workspace", "knowledge_check",
    }
    setup["flow"].action(session.token, view.conversation_id, view.id, CompositionRespondAction(
        action="respond_component", component_id="response", client_action_id=uuid4(),
        expected_artifact_revision=view.revision, payload={"selected_key": "A"},
    ))
    choice = next(b for b in current_program(session, setup).component_bindings if b.source.kind
                  == "knowledge_check")
    assert choice.result.correct and choice.state == "completed"
    action = setup["flow"].action(
        session.token, view.conversation_id, view.id, run_program(session, setup),
    )
    claim = owned_claim(database, session, action.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    completed = current_program(session, setup)
    assert completed.state == "completed"
    assert {binding.result.id for binding in completed.component_bindings} == {
        choice.result.id, action.result_id,
    }


@pytest.mark.parametrize("program_setup", [("python_project", None)], indirect=True)
def test_program_component_cancel_retry_late_receipts_and_changed_attempts_stay_exact(
    database, session, program_composition,
):
    setup = program_composition
    assert introduce_program(session, setup)[0].status == "accepted"
    flow = setup["flow"]
    view = current_program(session, setup)
    first = flow.action(
        session.token, view.conversation_id, view.id, run_program(session, setup, wrong=True),
    )
    old_claim = owned_claim(database, session, first.result_id)
    old_report = receipt(database, old_claim, wrong=True)
    running = current_program(session, setup)
    flow.action(session.token, view.conversation_id, view.id, CompositionCancelRunAction(
        action="cancel_component_run", component_id="editor", expected_attempt_id=first.result_id,
        client_action_id=uuid4(), expected_artifact_revision=running.revision,
    ))
    assert current_program(session, setup).component_bindings[0].allowed_actions == ["run", "retry"]
    second = flow.action(
        session.token, view.conversation_id, view.id,
        run_program(session, setup, wrong=True, parent=first.result_id, retry=True),
    )
    JourneyWorkflow(database).report(old_claim.job_id, old_report)
    assert current_program(session, setup).component_bindings[0].result.id == second.result_id
    claim = owned_claim(database, session, second.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, wrong=True))
    third = flow.action(
        session.token, view.conversation_id, view.id,
        run_program(session, setup, parent=second.result_id),
    )
    claim = owned_claim(database, session, third.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    completed = current_program(session, setup)
    assert completed.component_bindings[0].result.status == "passed"
    assert len(completed.component_bindings[0].attempts.attempts) == 3
    assert setup["programs"].attempt(session.token, first.result_id).status == "error"
    assert setup["programs"].attempt(session.token, first.result_id).sample_result is None
    assert setup["programs"].attempt(session.token, second.result_id).status == "not_passed"


def test_program_source_cannot_upgrade_old_runs_or_be_delivered_as_legacy_candidate(
    database, session, program_composition,
):
    setup = program_composition
    with pytest.raises(BusinessError):
        setup["flow"].candidate(session.token, setup["conversation"].id, LearningCandidateInput(
            pack_id=setup["pack"].pack_id, slot="practice_1",
        ))
    with pytest.raises(BusinessError, match="program-capable"):
        setup["tutor"].submit(
            session.token, setup["conversation"].id, str(uuid4()), TurnInput(
                text="Legacy direct delivery must be rejected.", focus=setup["focus"],
                learning_candidate_id=UUID(setup["source"]["id"]),
            ),
        )
    old = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()),
        TurnInput(text="Legacy turn", focus=setup["focus"]),
    )
    with database.transaction() as connection:
        frozen = Runs(connection).lock(old.run_id)["tool_contracts"]
        assert "list_learning_program_candidates" not in frozen
        assert "prepare_learning_program_composition" not in frozen
    setup["tutor"].cancel(session.token, old.run_id)


def test_unlisted_program_source_is_not_accepted_by_preparation(session, program_composition):
    setup = program_composition

    def mutate(args):
        args["owner_bindings"][0]["candidate_id"] = str(uuid4())

    task, _, preparations, _, _, _ = introduce_program(session, setup, mutate=mutate)
    assert task.status == "accepted" and preparations[0]["status"] != "completed"
    assert not setup["flow"].list_v2(session.token, setup["conversation"].id)


@pytest.mark.parametrize("program_setup", [
    ("sql_query", "sqlite"), ("python_project", None),
], indirect=True)
def test_preparation_cannot_modify_published_query_or_protected_project(
    session, program_composition,
):
    setup = program_composition

    def mutate(args):
        state = args["definition"]["states"]["editor"]
        if state["type"] == "code":
            state["value"] = "SELECT 999 AS answer"
        else:
            state["files"][0]["content"] = "print(999)"

    task, _, preparations, _, _, _ = introduce_program(session, setup, mutate=mutate)
    assert task.status == "accepted" and preparations[0]["status"] != "completed"
    assert not setup["flow"].list_v2(session.token, setup["conversation"].id)


def test_program_atomic_delivery_cas_conflict_has_no_artifact_or_owner_assignment(
    database, session, program_composition,
):
    setup = program_composition

    def conflict():
        with database.transaction() as connection:
            connection.execute(
                "UPDATE tutor.conversations SET teaching_revision=teaching_revision+1 WHERE id=%s",
                (setup["conversation"].id,),
            )

    task, _, preparations, _, _, _ = introduce_program(session, setup, conflict=conflict)
    assert task.status == "superseded" and preparations[0]["status"] == "completed"
    assert not setup["flow"].list_v2(session.token, setup["conversation"].id)


def test_program_result_and_component_callback_roll_back_together(
    database, session, program_composition, monkeypatch,
):
    setup = program_composition
    assert introduce_program(session, setup)[0].status == "accepted"
    view = current_program(session, setup)
    command = setup["flow"].action(
        session.token, view.conversation_id, view.id, run_program(session, setup),
    )
    claim = owned_claim(database, session, command.result_id)
    actual = receipt(database, claim)
    original = LearningArtifactWorkflow.event

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Original component callback unavailable.")

    monkeypatch.setattr(LearningArtifactWorkflow, "event", unavailable)
    with pytest.raises(RuntimeError, match="callback unavailable"):
        JourneyWorkflow(database).report(claim.job_id, actual)
    pending = current_program(session, setup)
    assert pending.state == "running"
    assert pending.component_bindings[0].result.status == "queued"
    assert pending.component_bindings[0].result.sample_result is None
    monkeypatch.setattr(LearningArtifactWorkflow, "event", original)
    JourneyWorkflow(database).report(claim.job_id, actual)
    assert current_program(session, setup).component_bindings[0].result.status == "passed"


@pytest.mark.skipif(os.environ.get("LEORNIAN_TEST_DOCKER") != "1", reason="Real bound program run")
@pytest.mark.parametrize("program_setup", [
    ("sql_query", "sqlite"), ("python_project", None),
], indirect=True)
def test_real_program_composition_action_uses_original_runner_and_sample_projection(
    database, session, workflow, program_composition, runner,
):
    setup = program_composition
    assert introduce_program(session, setup)[0].status == "accepted"
    view = current_program(session, setup)
    previous = None
    if setup["source"]["kind"] == "project_workspace":
        raw = run_program(session, setup).model_dump(mode="json")
        raw["payload"]["answer"]["files"][1]["content"] = (
            "def calculate(xs):\n    return 10**100 + 3\n"
        )
        huge = setup["flow"].action(session.token, view.conversation_id, view.id,
                                    CompositionProgramRunAction.model_validate(raw))
        claim = owned_claim(database, session, huge.result_id)
        JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, runner))
        actual = current_program(session, setup).component_bindings[0].result
        assert actual.status == "not_passed" and actual.passed_cases == 0
        assert actual.sample_result.output is None
        assert actual.sample_result.integer_text == str(10**100 + 3)
        previous = actual.id
    action = setup["flow"].action(
        session.token, view.conversation_id, view.id, run_program(session, setup, parent=previous),
    )
    claim = owned_claim(database, session, action.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, runner))
    completed = current_program(session, setup)
    assert completed.component_bindings[0].result.status == "passed"
    assert completed.component_bindings[0].result.sample_result.output is not None
    client = TestClient(create_app(setup["settings"]))
    path = f"/v2/conversations/{view.conversation_id}/learning-artifacts/{view.id}/example-runs"
    headers = {"Authorization": "Bearer " + session.token}
    sample = client.post(path, headers=headers, json={
        "command_id": str(uuid4()), "component_id": "editor",
        "expected_artifact_revision": completed.revision,
        "answer": completed.component_bindings[0].result.answer.model_dump(mode="json"),
    })
    assert sample.status_code == 202, sample.text
    job = claim_sample(database, session)
    actual_report = receipt(database, job, runner)
    assert len(actual_report.cases) == 1
    JourneyWorkflow(database).report(job.job_id, actual_report)
    output = client.get(path + "/" + sample.json()["command_id"], headers=headers).json()["output"]
    assert output["exit_code"] == 0 and output["stdout"] == actual_report.cases[0].stdout
    assert not workflow.snapshot(session.token).execution_progress
    with pytest.raises(BusinessError, match="自由练习"):
        setup["flow"].action(session.token, view.conversation_id, view.id, CancelAction(
            action="cancel", client_action_id=uuid4(),
            expected_artifact_revision=completed.revision,
        ))
    assert current_program(session, setup) == completed


def test_program_file_budget_does_not_silently_expand_legacy_display_readers():
    definition = LearningCompositionV2.model_validate({
        "schema_version": "learning_composition.v2", "title": "Bound large file",
        "states": {"files": {"type": "files", "files": [
            {"path": "main.py", "content": "x" * 20001},
        ]}},
        "components": [
            {"id": "editor", "component": "CodeEditor", "props": {
                "label": "Source", "state": "files",
            }},
        ],
    })
    with pytest.raises(BusinessError, match="20,000"):
        CompositionWorkflow.validate_file_scope(definition, programs=False)
    CompositionWorkflow.validate_file_scope(definition, programs=True)


