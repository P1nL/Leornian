import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_learning_artifacts import selected
from test_python_execution import owned_claim, program, publish_python, receipt
from test_python_execution import python_setup as python_setup
from test_runner import runner as runner
from test_teaching_delivery import body, drain, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.example_runs import ExampleRuns
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.python_contracts import PythonPracticeSubmission, PythonTraining
from leornian.modules.execution.contracts import RunnerReport
from leornian.modules.item_bank.supply_contracts import ChoiceInput
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionCancelRunAction,
    CompositionRespondAction,
    CompositionRunAction,
)
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.learning_artifact_contracts import CancelAction, PracticeSampleRunInput
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def owned_setup(database, session, request):
    if request.param == "knowledge_check":
        return request.getfixturevalue("learning_setup")
    python, pack, gate = request.getfixturevalue("python_setup")
    real = (
        request.getfixturevalue("runner") if os.environ.get("LEORNIAN_TEST_DOCKER") == "1" else None
    )
    publish_python(database, session, (python, pack, gate), runner=real)
    settings = replace(
        gate[2][2], delivery_enabled=True,
        model_context_tokens=128000, model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    return {
        "tutor": tutor, "settings": settings, "pack": pack, "python": python, "runner": real,
        "choice_pack": gate[1], "source": gate[2][4],
        "conversation": tutor.conversation(session.token, gate[2][3].goal_id),
        "flow": LearningArtifactWorkflow(database),
    }


def definition_for(source):
    choice = source["kind"] == "knowledge_check"
    presentation = source["presentation"]
    return {
        "schema_version": "learning_composition.v2", "title": "Practice with original feedback",
        "states": {
            "response": {"type": "choice"} if choice else {
                "type": "code", "value": presentation["task"]["starter_code"],
            },
        },
        "components": [
            {"id": "response", "component": "ChoiceAnswer" if choice else "CodeDiff", "props": {
                "label": "Your answer" if choice else "Your program", "state": "response",
                **({
                    "options": [
                        {"id": option["key"], "text": option["text"]}
                        for option in presentation["question"]["options"]
                    ],
                } if choice else {"before": presentation["task"]["starter_code"]}),
            }},
            {"id": "feedback", "component": "AnswerFeedback" if choice else "ResultFeedback",
             "props": {"label": "Original assessment result", "for_component": "response"}},
            {"id": "submit", "component": "ArtifactAction", "props": {
                "label": "Submit answer" if choice else "Run program",
                "event": "submit_answer" if choice else "check_code",
                "for_component": "response", "primary": True,
            }},
        ],
    }


def practice_provider(
    settings, source_id, *, mutate=None, conflict=None, extra_source_id=None,
    preparation="prepare_learning_practice_composition",
):
    calls, preparations = [], []

    def tool(name, args):
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "role": "assistant", "content": None, "tool_calls": [{
                        "id": name, "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })

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
            return tool("list_learning_artifact_candidates", {})
        value = json.loads(wire["messages"][-1]["content"])
        if "items" in value:
            source = next(item for item in value["items"] if item["id"] == str(source_id))
            args = {
                "command_key": "owned-practice-composition", "definition": definition_for(source),
                "owner_bindings": [{"component_id": "response", "candidate_id": source["id"]}],
            }
            if extra_source_id:
                extra = next(item for item in value["items"] if item["id"] == str(extra_source_id))
                additional = definition_for(extra)
                args["definition"]["states"]["second_response"] = additional["states"]["response"]
                for node in additional["components"]:
                    node["id"] = "second_" + node["id"]
                    for port in ("state", "for_component"):
                        if port in node["props"]:
                            node["props"][port] = "second_" + node["props"][port]
                args["definition"]["components"].extend(additional["components"])
                args["owner_bindings"].append({
                    "component_id": "second_response", "candidate_id": extra["id"],
                })
            if mutate:
                mutate(args)
            return tool(preparation, args)
        preparations.append(value)
        reply = (
            {
                "type": "artifact", "exact_handle": value["candidate"]["id"],
                "intent": "introduce_only",
            }
            if value["status"] == "completed" else {"type": "none"}
        )
        return httpx.Response(200, json=body(json.dumps({
            "text": "Work on the supplied practice; completion is not a formal Gate.",
            "interaction": reply,
        })))

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), calls, preparations


def introduce_owned(session, setup, *, mutate=None, conflict=None, extra_source_id=None):
    source = selected(session, setup)
    key = str(uuid4())
    data = TurnInput(
        text="Compose this exact ordinary practice with its original assessment feedback.",
        focus=source.focus,
        presentation_capabilities={
            "versions": ["learning_composition.v2"], "actions": ["learning_practice.v2"],
        },
    )
    accepted = setup["tutor"].submit(session.token, setup["conversation"].id, key, data)
    gateway, calls, preparations = practice_provider(
        setup["settings"], source.id, mutate=mutate, conflict=conflict,
        extra_source_id=extra_source_id,
    )
    task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
    return task, accepted, preparations, calls, key, data


def current(session, setup):
    flow, conversation = setup["flow"], setup["conversation"].id
    summary = flow.list_v2(session.token, conversation)[0]
    return flow.get_v2(session.token, conversation, summary.id)


@pytest.mark.parametrize("owned_setup", ["knowledge_check"], indirect=True)
def test_choice_composition_is_checked_atomic_and_delegates_to_original_once_only_owner(
    database, workflow, session, owned_setup,
):
    setup = owned_setup
    task, accepted, prepared, calls, key, turn = introduce_owned(session, setup)
    assert task.status == "accepted" and len(calls) == 4
    assert prepared[0]["status"] == "completed"
    view = current(session, setup)
    binding = view.component_bindings[0]
    assert binding.source.presentation.question.prompt
    assert binding.state == "ready" and binding.allowed_actions == ["respond"]
    assert not binding.result and not binding.action_id
    assert "correct_key" not in view.model_dump_json()
    assert setup["tutor"].submit(session.token, view.conversation_id, key, turn) == accepted
    with pytest.raises(BusinessError, match="support changed"):
        setup["tutor"].submit(
            session.token, view.conversation_id, key,
            turn.model_copy(update={
                "presentation_capabilities": turn.presentation_capabilities.model_copy(
                    update={"actions": []}
                ),
            }),
        )
    data = CompositionRespondAction(
        action="respond_component", component_id="response",
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
        payload={"selected_key": "A"},
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: setup["flow"].action(session.token, view.conversation_id, view.id, data),
            range(2),
        ))
    assert results[0] == results[1]
    assert results[0].schema_version == "learning_action.v2"
    assert results[0].component_state == results[0].state == "completed"
    old = setup["supply"].answer(
        session.token, setup["pack"].pack_id, str(data.client_action_id),
        ChoiceInput(slot="practice_1", selected_key="A"),
    )
    assert old.id == results[0].result_id
    final = current(session, setup)
    assert final.component_bindings[0].result == old
    assert final.component_bindings[0].action_id == data.client_action_id
    assert final.practice_only and not final.allowed_actions
    assert not final.component_bindings[0].allowed_actions
    assert not workflow.snapshot(session.token).node_progress
    client = TestClient(create_app(setup["settings"]))
    path = f"/v2/conversations/{view.conversation_id}/learning-artifacts/{view.id}"
    headers = {"Authorization": "Bearer " + session.token}
    assert client.get(path, headers=headers).json()["component_bindings"][0]["result"]["correct"]
    recovered = client.get(path + f"/actions/{data.client_action_id}", headers=headers)
    assert recovered.json()["schema_version"] == "learning_action.v2"
    assert recovered.json()["result_id"] == str(old.id)
    replay = client.post(path + "/actions", headers=headers, json=data.model_dump(mode="json"))
    assert replay.status_code == 200
    assert replay.json()["schema_version"] == "learning_action.v2"
    with database.transaction() as connection:
        run = Runs(connection).lock(accepted.run_id)
        assert run["tool_contracts"]["prepare_learning_practice_composition"] == 1
        assert connection.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE run_id=%s",
            (accepted.run_id,),
        ).fetchone()["n"] == 4
        assert connection.execute(
            "SELECT count(*) AS n FROM assessment.choice_results WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"] == 1


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_python_composition_revisions_cancel_retry_and_late_receipt_keep_original_attempts(
    database, workflow, session, owned_setup,
):
    setup = owned_setup
    assert introduce_owned(session, setup)[0].status == "accepted"
    flow = setup["flow"]

    def run(code, previous=None, retry=False):
        view = current(session, setup)
        return flow.action(
            session.token, view.conversation_id, view.id, CompositionRunAction(
                action="run_component", component_id="response",
                client_action_id=uuid4(), expected_artifact_revision=view.revision,
                payload={"code": code, "previous_attempt_id": previous, "retry": retry},
            ),
        )

    first = run("print(0)")
    claim = owned_claim(database, session, first.result_id)
    JourneyWorkflow(database).report(
        claim.job_id, receipt(database, claim, setup["runner"], wrong=True)
    )
    after_first = current(session, setup)
    assert after_first.component_bindings[0].result.status == "not_passed"
    assert after_first.component_bindings[0].allowed_actions == ["run"]
    third = run("print(-1)", first.result_id)
    late = owned_claim(database, session, third.result_id)
    view = current(session, setup)
    cancel = CompositionCancelRunAction(
        action="cancel_component_run", component_id="response", client_action_id=uuid4(),
        expected_artifact_revision=view.revision, expected_attempt_id=third.result_id,
    )
    cancelled = flow.action(session.token, view.conversation_id, view.id, cancel)
    assert cancelled.component_state == "completed"
    assert current(session, setup).component_bindings[0].allowed_actions == ["run", "retry"]
    with pytest.raises(BusinessError, match="explicitly retry"):
        run("print(-1)", third.result_id)
    fourth = run("print(-1)", third.result_id, retry=True)
    JourneyWorkflow(database).report(late.job_id, receipt(database, late, setup["runner"]))
    latest = current(session, setup).component_bindings[0]
    assert latest.result.id == fourth.result_id and latest.result.status == "queued"
    assert len(latest.attempts.items) == 3
    assert latest.attempts.items[1].status == "error"
    view = current(session, setup)
    flow.action(session.token, view.conversation_id, view.id, CancelAction(
        action="cancel", client_action_id=uuid4(), expected_artifact_revision=view.revision,
    ))
    final = current(session, setup)
    assert final.state == final.component_bindings[0].state == "cancelled"
    assert final.component_bindings[0].result.status == "error"
    assert not final.allowed_actions and not final.component_bindings[0].allowed_actions
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.node_progress and not snapshot.execution_progress


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_passed_python_workbench_runs_only_the_public_sample(
    database, workflow, session, owned_setup,
):
    setup = owned_setup
    assert introduce_owned(session, setup)[0].status == "accepted"
    flow, examples, journey = setup["flow"], ExampleRuns(database), JourneyWorkflow(database)
    view = current(session, setup)
    path = (session.token, view.conversation_id, view.id)
    sample = PracticeSampleRunInput(
        command_id=uuid4(), component_id="response",
        expected_artifact_revision=view.revision, answer={"code": "print(17)"},
    )
    with pytest.raises(BusinessError, match="尚未进入"):
        examples.submit(*path, sample)
    action = CompositionRunAction(
        action="run_component", component_id="response", client_action_id=uuid4(),
        expected_artifact_revision=view.revision, payload={"code": program("practice_1")},
    )
    original = flow.action(*path, action)
    job = owned_claim(database, session, original.result_id)
    journey.report(job.job_id, receipt(database, job, setup["runner"]))
    completed = current(session, setup)
    assert completed.practice_only and not completed.component_bindings[0].allowed_actions
    with pytest.raises(BusinessError, match="自由练习"):
        flow.action(*path, action.model_copy(update={
            "client_action_id": uuid4(), "expected_artifact_revision": completed.revision,
        }))
    sample = sample.model_copy(update={"expected_artifact_revision": completed.revision})
    assert examples.submit(*path, sample).status == "queued"
    job = owned_claim(database, session)
    assert job.code == "print(17)"
    assert job.inputs == [completed.component_bindings[0].source.presentation.task.sample.input]
    output = (setup["runner"].execute_case(job.code, job.inputs[0]) if setup["runner"] else
              {"outcome": "completed", "exit_code": 0, "stdout": "17\n", "stderr": ""})
    journey.report(job.job_id, RunnerReport(claim_token=job.claim_token, cases=[output]))
    assert examples.submit(*path, sample).output.stdout.strip() == "17"
    assert current(session, setup) == completed and flow.action(*path, action) == original
    snapshot = workflow.snapshot(session.token)
    assert [attempt.id for attempt in snapshot.python_attempts] == [original.result_id]
    assert not snapshot.node_progress and not snapshot.execution_progress


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_multiple_original_owners_keep_independent_locks_and_one_aggregate_artifact(
    database, workflow, session, owned_setup,
):
    from leornian.modules.tutor.learning_artifact_contracts import LearningCandidateInput

    setup = owned_setup
    source = setup["flow"].candidate(
        session.token, setup["conversation"].id,
        LearningCandidateInput(pack_id=setup["choice_pack"].pack_id, slot="practice_1"),
    )
    assert introduce_owned(session, setup, extra_source_id=source.id)[0].status == "accepted"
    view = current(session, setup)
    assert len(view.component_bindings) == 2
    run = setup["flow"].action(
        session.token, view.conversation_id, view.id, CompositionRunAction(
            action="run_component", component_id="response", client_action_id=uuid4(),
            expected_artifact_revision=view.revision, payload={"code": program("practice_1")},
        ),
    )
    view = current(session, setup)
    assert view.state == "running"
    choice = next(
        item for item in view.component_bindings if item.component_id == "second_response"
    )
    assert choice.allowed_actions == ["respond"]
    setup["flow"].action(
        session.token, view.conversation_id, view.id, CompositionRespondAction(
            action="respond_component", component_id="second_response", client_action_id=uuid4(),
            expected_artifact_revision=view.revision, payload={"selected_key": "A"},
        ),
    )
    pending = current(session, setup)
    assert pending.state == "running"
    assert pending.component_bindings[1].result.correct
    assert not pending.component_bindings[1].allowed_actions
    claim = owned_claim(database, session, run.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, setup["runner"]))
    final = current(session, setup)
    assert final.state == "completed" and final.content_ref == view.content_ref
    assert final.component_bindings[0].result.status == "passed"
    assert final.component_bindings[1].result == pending.component_bindings[1].result
    assert final.component_bindings[1].action_id == pending.component_bindings[1].action_id
    assert not workflow.snapshot(session.token).node_progress


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_direct_owner_revision_has_no_fabricated_artifact_action_identity(
    database, session, owned_setup,
):
    setup = owned_setup
    assert introduce_owned(session, setup)[0].status == "accepted"
    view = current(session, setup)
    first = setup["flow"].action(
        session.token, view.conversation_id, view.id, CompositionRunAction(
            action="run_component", component_id="response", client_action_id=uuid4(),
            expected_artifact_revision=view.revision, payload={"code": "print(0)"},
        ),
    )
    claim = owned_claim(database, session, first.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, wrong=True))
    second = setup["python"].submit_practice(
        session.token, setup["pack"].pack_id, str(uuid4()), PythonPracticeSubmission(
            slot="practice_1", code=program("practice_1"), previous_attempt_id=first.result_id,
        ),
    )
    latest = current(session, setup).component_bindings[0]
    assert latest.result.id == second.id and latest.action_id is None
    assert latest.allowed_actions == ["cancel_run"]


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_legacy_running_owner_can_close_composition_without_upgrading_original_execution_policy(
    database, session, owned_setup,
):
    setup = owned_setup
    assert introduce_owned(session, setup)[0].status == "accepted"
    attempt = setup["python"].submit_training(
        session.token, setup["pack"].pack_id, str(uuid4()),
        PythonTraining(slot="practice_1", code=program("practice_1")),
    )
    claim = owned_claim(database, session, attempt.id)
    view = current(session, setup)
    binding = view.component_bindings[0]
    assert binding.result.policy_version == "python-io-attempt.v1"
    assert binding.result.id == attempt.id and not binding.allowed_actions
    setup["flow"].action(session.token, view.conversation_id, view.id, CancelAction(
        action="cancel", client_action_id=uuid4(), expected_artifact_revision=view.revision,
    ))
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    assert setup["python"].practice_attempt(session.token, attempt.id).status == "passed"
    assert current(session, setup).state == "cancelled"


@pytest.mark.parametrize("owned_setup", ["knowledge_check"], indirect=True)
@pytest.mark.parametrize("change", ["unlisted", "options"])
def test_practice_preparation_rejects_unlisted_handle_or_modified_owner_content(
    database, workflow, session, owned_setup, change,
):
    def mutate(args):
        if change == "unlisted":
            args["owner_bindings"][0]["candidate_id"] = str(uuid4())
        else:
            args["definition"]["components"][0]["props"]["options"][0]["text"] = "Replaced option"

    setup = owned_setup
    task, _, prepared, _, _, _ = introduce_owned(session, setup, mutate=mutate)
    assert task.status == "accepted" and prepared[0]["status"] == "waiting_dependency"
    assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
    assert not workflow.snapshot(session.token).choice_results
    with database.transaction(snapshot=True) as connection:
        assert not connection.execute(
            "SELECT 1 FROM tutor.learning_presentations WHERE actor_id=%s", (session.actor.id,)
        ).fetchone()


@pytest.mark.parametrize("owned_setup", ["knowledge_check"], indirect=True)
def test_practice_preparation_cas_conflict_does_not_expose_or_assign_owner(
    database, session, owned_setup,
):
    setup = owned_setup

    def conflict():
        with database.transaction() as connection:
            connection.execute(
                "UPDATE tutor.conversations SET teaching_revision=teaching_revision+1 WHERE id=%s",
                (setup["conversation"].id,),
            )

    task, _, prepared, _, _, _ = introduce_owned(session, setup, conflict=conflict)
    assert prepared[0]["status"] == "completed" and task.status == "superseded"
    assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
    with database.transaction(snapshot=True) as connection:
        assert not connection.execute(
            "SELECT 1 FROM tutor.learning_component_bindings b "
            "JOIN tutor.learning_artifacts a ON a.id=b.artifact_id WHERE a.actor_id=%s",
            (session.actor.id,),
        ).fetchone()
        assert not connection.execute(
            "SELECT 1 FROM item_bank.exposure_facts WHERE actor_id=%s", (session.actor.id,)
        ).fetchone()
