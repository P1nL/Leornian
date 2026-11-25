import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_composition_delivery import composition_provider
from test_execution_environments import claim, ready_engine
from test_multilanguage_runner import engineering_release
from test_multilanguage_runner import runner as runner
from test_node_teaching_pacing import node_scene as node_scene
from test_teaching_delivery import drain
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.contracts import TurnAccepted
from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.modules.execution.contracts import (
    ExecutionVerificationInput,
    ProjectEnvironment,
    RunnerReport,
)
from leornian.modules.execution.environment_contracts import (
    EnvironmentPreparationReport,
    EnvironmentReleaseVerificationInput,
)
from leornian.modules.tutor.artifact_templates import PrepareLearningTemplate


def deliver_template(scene, session, content, description):
    client, _, focus, conversation, tutor, settings = scene
    endpoint = f"/v1/conversations/{conversation.id}/turns"
    accepted = client.post(endpoint, headers={"Idempotency-Key": str(uuid4())}, json={
        "text": "用这个工件演示。", "focus": focus, "teaching_session_revision": 1,
        "node_pacing": True, "presentation_capabilities": {
            "versions": ["learning_composition.v2"],
            "actions": ["learning_templates.v1", "learning_example_runs.v1"],
        },
    })
    assert accepted.status_code == 202, accepted.text
    gateway, calls, _ = composition_provider(
        settings, preparation="prepare_learning_template",
        template={"title": "教学示例", "description": description, "content": content},
        reply_text=description, pacing={"next_step": "wait_for_action", "resume_at": "示例"},
    )
    task = drain(tutor, settings, TurnAccepted(**accepted.json()), gateway, session.token)
    assert task.status == "accepted", task
    assert "prepare_learning_template" in [tool["function"]["name"] for tool in calls[0]["tools"]]
    evidence = json.loads(calls[-1]["messages"][-1]["content"])["turn_evidence"]
    selected = evidence["selected_artifact"]
    root = f"/v2/conversations/{conversation.id}/learning-artifacts"
    root += "/" + client.get(root).json()[0]["id"]
    card = client.get(root + "?example_capability=learning_example_runs.v1").json()
    assert not card.get("component_bindings")
    assert selected["candidate"]["content_ref"] == card["content_ref"]
    return root, card, selected


@pytest.mark.parametrize(("content", "component"), [
    ({"kind": "choice", "options": ["先读", "先写"]}, "ChoiceAnswer"),
    ({"kind": "ordering", "items": ["观察", "修改"]}, "OrderingAnswer"),
    ({"kind": "reflection"}, "TextAnswer"),
    ({"kind": "code_annotation", "code": "value = 3"}, "LineRangeAnswer"),
    ({"kind": "web_preview", "html": "<p>Hello</p>", "css": "p {color:red}"}, "IsolatedPreview"),
    ({"kind": "walkthrough", "steps": ["观察", "修改"]}, "StepPlayer"),
])
def test_template_content_is_delivered_without_question_or_submit(
    node_scene, session, content, component,
):
    root, card, _ = deliver_template(node_scene, session, content, "先自行探索。")
    ports = card["presentation"]["definition"]["components"]
    assert component in [port["component"] for port in ports]
    assert not any(port["props"].get("event") in {"check_code", "submit_answer", "submit_review"}
                   for port in ports)
    assert not card.get("example_runners")
    if content["kind"] == "choice":
        rejected = node_scene[0].post(root + "/actions", json={
            "action": "respond_component", "component_id": "activity",
            "client_action_id": str(uuid4()), "expected_artifact_revision": card["revision"],
            "payload": {"selected_key": "A"},
        })
        assert rejected.status_code in (404, 409), rejected.text


def test_template_does_not_accept_an_answer_key_or_an_owner():
    for extra in ({"correct": "item1"}, {"owner_bindings": []}):
        with pytest.raises(ValidationError):
            PrepareLearningTemplate.model_validate({
                "title": "选择", "description": "做个预测", "command_key": "example-choice",
                "content": {"kind": "choice", "options": ["甲", "乙"], **extra},
            })


@pytest.mark.parametrize("node_scene", ["python-standard.v1"], indirect=True)
def test_template_sample_runs_on_the_local_runner_without_a_pack(
    node_scene, database, workflow, session, runner,
):
    client, _, _, _, _, _ = node_scene
    local = engineering_release("python")
    environments = ExecutionEnvironmentWorkflow(database)
    ready_engine(environments)
    work = claim(environments)
    release = environments.report(work.job_id, EnvironmentPreparationReport(
        claim_token=work.claim_token, outcome="ready",
        **{key: local[key] for key in (
            "runtime_version", "image_id", "image_ids", "toolchains", "verification",
        )},
    ))
    code = ('while (value := input()) != "q":\n    hours, left = divmod(int(value), 60)\n'
            '    print(f"{hours} 小时 {left:02d} 分钟")\nprint("再见！")')
    root, card, selected = deliver_template(node_scene, session, {
        "kind": "code_workspace", "filename": "minutes.py", "code": code,
        "language": "python", "stdin": "65\nq\n",
    }, "可以改动标准输入再运行。")
    workspace = card["presentation"]["example_workspace"]
    assert workspace == selected["candidate"]["presentation"]["example_workspace"]
    assert selected["example_runners"] == card["example_runners"] == {"editor": ["python"]}
    command = {"command_id": str(uuid4()), "component_id": workspace["editor"],
               "expected_artifact_revision": card["revision"], "language": workspace["language"],
               "code": card["presentation"]["definition"]["states"]["code"]["value"],
               "stdin": workspace["stdin"]}
    endpoint = root + "/example-runs"
    assert client.post(endpoint, json={**command, "language": "java"}).status_code == 409
    assert client.post(endpoint, json=command).status_code == 202
    journey = JourneyWorkflow(database)
    runtime = ProjectEnvironment(**release.environment())
    job = journey.claim("template-test", [runtime])
    assert job is not None
    job_auth = ExecutionVerificationInput(claim_token=job.claim_token)
    release_auth = EnvironmentReleaseVerificationInput(
        profile=runtime.profile, language=runtime.language, runtime_version=runtime.runtime_version,
    )
    compilation, cases = runner.execute_stdio(
        job.program.model_dump(mode="json"), {**local, "id": str(release.id)},
        authorize=lambda: (journey.verify_execution(job.job_id, job_auth)["allowed"]
                           and environments.verify_release(release.id, release_auth)["allowed"]),
    )
    journey.report(job.job_id, RunnerReport(
        claim_token=job.claim_token, compilation=compilation, cases=cases,
    ))
    output = client.get(endpoint + "/" + command["command_id"]).json()["output"]
    assert output["exit_code"] == 0
    assert output["stdout"].splitlines() == ["1 小时 05 分钟", "再见！"]
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.python_attempts and not snapshot.node_progress
