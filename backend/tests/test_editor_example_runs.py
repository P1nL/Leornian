import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from test_composition_delivery import composition_provider
from test_execution_environments import claim, decide, ready_engine, release_report
from test_multilanguage_runner import engineering_release
from test_multilanguage_runner import runner as runner
from test_node_teaching_pacing import deliver, greeting_editor
from test_node_teaching_pacing import node_scene as node_scene
from test_teaching_delivery import body, drain, provider, report
from test_tutor_runtime import response
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.contracts import TurnAccepted
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.bootstrap.example_runs import ExampleRuns
from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.teaching_context import CONTEXT_PREFIX, TeachingContext
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import (
    ExecutionVerificationInput,
    ProjectEnvironment,
    RunnerReport,
)
from leornian.modules.execution.environment_contracts import (
    EnvironmentPreparationReport,
    EnvironmentReleaseVerificationInput,
)
from leornian.modules.execution.example_contracts import ExampleTerminalExchange, example_surface
from leornian.modules.tutor.deliveries import Deliveries


@pytest.fixture
def runnable_greeting(node_scene, session, database, request):
    capability = getattr(request, "param", "learning_example_runs.v1")
    client, _, focus, conversation, tutor, settings = node_scene
    envs = ExecutionEnvironmentWorkflow(database)
    ready_engine(envs)
    work = claim(envs)
    language = work.requirement.language
    report_data = release_report(work)
    if language == "javascript":
        report_data = report_data.model_copy(update={
            "runtime_version": "22.0.0", "toolchains": {"node": "22.0.0"},
        })
    release = envs.report(work.job_id, report_data)
    accepted = client.post(f"/v1/conversations/{conversation.id}/turns", headers={
        "Idempotency-Key": str(uuid4()),
    }, json={
        "text": "我想把问候改成晚上好。", "focus": focus,
        "teaching_session_revision": 1, "node_pacing": True,
        "presentation_capabilities": {
            "versions": ["learning_composition.v2"], "actions": [capability],
        },
    })
    definition = greeting_editor()
    if language == "javascript":
        definition["states"]["greeting"]["value"] = "console.log('你好')"
    definition["components"][0]["props"]["label"] = "问候语（这里只改文本，不执行）"
    gateway, calls, _ = composition_provider(
        settings, definition=definition, reply_text="改引号里的问候语。",
        pacing={"next_step": "wait_for_action", "resume_at": "问候语"},
    )
    delivered = drain(tutor, settings, TurnAccepted(**accepted.json()), gateway, session.token)
    assert delivered.status == "accepted"
    authored = json.loads(calls[0]["messages"][1]["content"].removeprefix(CONTEXT_PREFIX))
    assert authored["workspace"]["learner_example_run_languages"] == [language]
    review = json.loads(calls[-1]["messages"][-1]["content"])
    for facts in (authored, review["turn_evidence"]):
        assert facts["workspace"]["example_run_surface"] == example_surface(capability).model_dump()
    assert review["turn_evidence"]["selected_artifact"]["example_runners"] == {
        "greeting_editor": [language],
    }
    root = f"/v2/conversations/{conversation.id}/learning-artifacts"
    artifact = client.get(root).json()[0]
    root += "/" + artifact["id"]
    return envs, release, artifact, root


@pytest.mark.parametrize("node_scene", ["python-standard.v1"], indirect=True)
def test_edit_run_uses_only_the_current_draft_release_and_never_grades(
    node_scene, session, database, workflow, runnable_greeting,
):
    client, _, _, conversation, _, _ = node_scene
    envs, release, artifact, root = runnable_greeting
    assert {"example_run_surface", "example_runners"}.isdisjoint(client.get(root).json())
    card = client.get(root + "?example_capability=learning_example_runs.v1").json()
    assert card["example_runners"] == {"greeting_editor": ["python"]}
    assert card["example_run_surface"] == example_surface("learning_example_runs.v1").model_dump()
    request = {"command_id": str(uuid4()), "component_id": "greeting_editor",
               "expected_artifact_revision": artifact["revision"], "language": "python",
               "code": "print(input())", "stdin": "晚上好\n"}
    endpoint = root + "/example-runs"
    assert client.post(endpoint, json={**request, "language": "java"}).status_code == 409
    assert client.post(endpoint, json={**request, "component_id": "other"}).status_code == 409
    queued = client.post(endpoint, json=request)
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    assert client.post(endpoint, json=request).json() == queued.json()
    assert client.post(endpoint, json={**request, "code": "print(2)"}).status_code == 409
    other = workflow.create_session("Other learner")
    assert client.get(endpoint + "/" + request["command_id"], headers={
        "Authorization": f"Bearer {other.token}",
    }).status_code == 404
    journey = JourneyWorkflow(database)
    assert journey.claim("no-project-release") is None
    runtime = ProjectEnvironment(**release.environment())
    run = journey.claim("example-runner", [runtime])
    assert run.program.files[0].content == request["code"]
    assert run.program.inputs == [request["stdin"]]
    check = ExecutionVerificationInput(claim_token=run.claim_token)
    assert journey.verify_execution(run.job_id, check)["allowed"]
    report = RunnerReport(claim_token=run.claim_token, cases=[{
        "exit_code": 0, "outcome": "completed", "stdout": "晚上好\n", "stderr": "",
    }])
    journey.report(run.job_id, report)
    journey.report(run.job_id, report)
    result = client.get(endpoint + "/" + request["command_id"]).json()
    assert result["status"] == "reported" and result["output"]["stdout"] == "晚上好\n"
    assert not workflow.snapshot(session.token).execution_progress
    assert not workflow.snapshot(session.token).node_progress
    retry = {**request, "command_id": str(uuid4())}
    assert client.post(endpoint, json=retry).status_code == 202
    again = journey.claim("example-runner", [runtime])
    demand = next(
        item for item in envs.snapshot(session.token).demands if item.id == release.demand_id
    )
    decide(envs, session, demand, value="revoke")
    assert not journey.verify_execution(again.job_id, ExecutionVerificationInput(
        claim_token=again.claim_token,
    ))["allowed"]
    journey.report(again.job_id, report.model_copy(update={"claim_token": again.claim_token}))
    expired = ExampleRuns(database).get(session.token, conversation.id,
                                        UUID(artifact["id"]), UUID(retry["command_id"]))
    assert expired.status == "expired" and expired.output is None


@pytest.mark.parametrize("node_scene", ["python-standard.v1"], indirect=True)
@pytest.mark.parametrize("runnable_greeting", ["learning_example_runs.v2"], indirect=True)
def test_terminal_owns_lines_and_stop_until_original_runner_finishes(
    node_scene, runnable_greeting, database, workflow,
):
    client = node_scene[0]
    _, release, artifact, root = runnable_greeting
    card = client.get(root + "?example_capability=learning_example_runs.v2").json()
    assert card["example_run_surface"]["input_mode"] == "line_during_run"
    endpoint = root + "/example-runs"
    body = {"command_id": str(uuid4()), "expected_artifact_revision": artifact["revision"],
            "component_id": "greeting_editor", "language": "python", "code": "input('分钟：')",
            "interactive": True}
    assert client.post(endpoint, json={**body, "stdin": "65\nq"}).status_code == 422
    assert client.post(endpoint, json=body).json()["terminal"]["transcript"] == ""
    address = endpoint + "/" + body["command_id"]
    line = {"input_id": str(uuid4()), "text": "65"}
    assert client.post(address + "/input", json=line).status_code == 409
    late = {**body, "command_id": str(uuid4())}
    client.post(endpoint, json=late)
    assert client.post(endpoint + "/" + late["command_id"] + "/stop").json()["status"] == "expired"
    journey = JourneyWorkflow(database)
    runtime = [ProjectEnvironment(**release.environment())]
    assert journey.claim("batch-only", runtime) is None
    job = journey.claim("terminal", runtime, example_terminal=True)
    assert job.interactive and job.program.inputs == [""]
    service = ExampleRuns(database)
    def exchange(frame, text, after_input):
        return service.exchange(job.job_id, ExampleTerminalExchange(
            claim_token=job.claim_token, frame=frame, text=text, after_input=after_input,
        ))["lines"]
    assert exchange(1, "分钟：", 0) == []
    assert client.get(address).json()["terminal"]["transcript"] == "分钟："
    other = workflow.create_session("Second learner")
    for action in ("input", "stop"):
        assert client.post(address + "/" + action, json=line, headers={
            "Authorization": "Bearer " + other.token,
        }).status_code == 404
    assert client.post(address + "/input", json=line).status_code == 200
    assert client.post(address + "/input", json=line).status_code == 200
    assert client.post(address + "/input", json={**line, "text": "90"}).status_code == 409
    assert exchange(1, "", 0) == ["65"]
    assert exchange(2, "下一行：", 1) == []
    stop = client.post(address + "/stop").json()
    assert stop["terminal"] == {
        "stopping": True, "accepting_input": False, "transcript": "分钟：65\n下一行：",
    }
    rejected = client.post(address + "/input", json={**line, "input_id": str(uuid4())})
    assert rejected.status_code == 409
    assert not journey.verify_execution(job.job_id, ExecutionVerificationInput(
        claim_token=job.claim_token,
    ))["allowed"]
    journey.report(job.job_id, RunnerReport(claim_token=job.claim_token, cases=[{
        "outcome": "infrastructure_error", "exit_code": None, "stdout": "", "stderr": "",
    }]))
    result = client.get(address).json()
    assert result["status"] == "expired" and result["error_code"] == "learner_cancelled"
    assert not result["terminal"]["stopping"] and result["output"] is None


@pytest.mark.parametrize("node_scene", ["python-standard.v1"], indirect=True)
@pytest.mark.parametrize("supports_run", [True, False], ids=["connected", "legacy"])
def test_anchor_question_uses_current_controls_and_only_pre_question_run_facts(
    node_scene, runnable_greeting, session, database, supports_run,
):
    client, session_path, focus, conversation, tutor, settings = node_scene
    _, release, artifact, root = runnable_greeting
    journey = JourneyWorkflow(database)

    def run_draft(exit_code):
        command = {"command_id": str(uuid4()), "component_id": "greeting_editor",
                   "expected_artifact_revision": artifact["revision"], "language": "python",
                   "code": "print(private_draft)", "stdin": "private_input"}
        assert client.post(root + "/example-runs", json=command).status_code == 202
        job = journey.claim("example-runner", [ProjectEnvironment(**release.environment())])
        journey.report(job.job_id, RunnerReport(claim_token=job.claim_token, cases=[{
            "outcome": "completed", "exit_code": exit_code,
            "stdout": "private_output", "stderr": "private_diagnostic",
        }]))
        return command["command_id"]

    first = run_draft(0)
    second = run_draft(1)
    submitted = client.post(f"/v1/conversations/{conversation.id}/turns", headers={
        "Idempotency-Key": str(uuid4()),
    }, json={
        "text": "怎么会说这个名字没定义？", "focus": focus, "node_pacing": True,
        "teaching_session_revision": client.get(session_path).json()["revision"],
        "presentation_capabilities": {
            "versions": ["learning_composition.v2"],
            "actions": ["learning_example_runs.v1"] if supports_run else [],
        },
    })
    assert submitted.status_code == 202, submitted.text
    with database.transaction(snapshot=True) as connection:
        task = Deliveries(connection).for_run(UUID(submitted.json()["run_id"]))
        assert task["author_messages"] == []
        binding = task["context_manifest"]["teaching_session"]
        assert binding["anchor_revision"] == artifact["revision"]
    later = run_draft(0)
    wires = []

    def handle(request):
        wire = json.loads(request.content)
        wires.append(wire)
        if len(wires) == 1:
            reply = response()
        elif "Independently review" in wire["messages"][0]["content"]:
            reply = body(json.dumps(report(json.loads(wire["messages"][-1]["content"]))))
        else:
            reply = body(json.dumps({
                "text": "引号外的名字会被当作变量。", "interaction": {"type": "none"},
                "pacing": {"next_step": "wait_for_reply", "resume_at": "引号"},
            }))
        return httpx.Response(200, json=reply)

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    delivered = drain(tutor, settings, TurnAccepted(**submitted.json()), gateway, session.token)
    assert delivered.status == "accepted" and len(wires) == 3
    review = json.loads(wires[-1]["messages"][-1]["content"])
    initial = json.loads(wires[0]["messages"][1]["content"].removeprefix(CONTEXT_PREFIX))
    assert "actual_author_input" not in review and "composition_checks" not in review
    assert review["turn_evidence"]["learner_messages"] == ["怎么会说这个名字没定义？"]
    for facts in (initial, review["turn_evidence"]):
        anchor = facts["workspace"]["public_anchor"]
        assert facts["history"]["delivered_teaching"][0]["extracts"][-1]["turn_id"] == (
            artifact["source_turn_id"]
        )
        if supports_run:
            assert anchor["example_runners"] == {"greeting_editor": ["python"]}
            observed = facts["observations"]["example_runs"]
            assert (observed["anchor_artifact_id"], observed["anchor_revision"]) == (
                artifact["id"], artifact["revision"],
            )
            assert [(row["command_id"], row["phase"], row["outcome"], row["exit_code"],
                     row["report_count"]) for row in observed["by_outcome"]] == [
                (second, "execution", "completed", 1, 1), (first, "execution", "completed", 0, 1),
            ]
            assert all(row["component_id"] == "greeting_editor" and row["language"] == "python"
                       for row in observed["by_outcome"])
        else:
            assert "example_runners" not in anchor and "example_runs" not in facts["observations"]
    result = json.loads(next(msg["content"] for msg in wires[1]["messages"]
                             if msg["role"] == "tool"))
    assert result == {"relative_to": "initial_node_turn", "changes": []}
    assert "tool_observations" not in review["turn_evidence"]
    serialized = json.dumps(wires)
    assert all(value not in serialized for value in (
        "private_draft", "private_input", "private_output", "private_diagnostic", later,
    ))


@pytest.mark.parametrize(("node_scene", "share"), [
    ("python-standard.v1", False), ("javascript-standard.v1", True),
], indirect=["node_scene"])
def test_next_node_uses_only_attributed_example_code(
    node_scene, runnable_greeting, session, database, workflow, share,
):
    client, session_path, _, conversation, tutor, settings = node_scene
    _, release, artifact, root = runnable_greeting
    runtime = ProjectEnvironment(**release.environment())
    journey = JourneyWorkflow(database)
    render = "print" if runtime.language == "python" else "console.log"
    starter = f"{render}('你好')"
    edited = f"{render}('kept_earlier_feature')"

    def run(code, consent=False, exit_code=0):
        command = {"command_id": str(uuid4()), "component_id": "greeting_editor",
                   "expected_artifact_revision": artifact["revision"], "language": runtime.language,
                   "code": code, "stdin": "private_stdin", "share_code_for_teaching": consent}
        queued = client.post(root + "/example-runs", json=command)
        assert queued.status_code == 202, queued.text
        job = journey.claim("continuity-runner", [runtime])
        assert job.program.files[0].content == code
        journey.report(job.job_id, RunnerReport(claim_token=job.claim_token, cases=[{
            "outcome": "completed", "exit_code": exit_code,
            "stdout": "private_stdout", "stderr": "private_stderr",
        }]))
        return command["command_id"]

    def ask(text, *, run_capable=True):
        state = client.get(session_path).json()
        result = client.post(f"/v1/conversations/{conversation.id}/turns",
                             headers={"Idempotency-Key": str(uuid4())}, json={
                                 "text": text, "focus": state["focus"], "node_pacing": True,
                                 "teaching_session_revision": state["revision"],
                                 "presentation_capabilities": {
                                     "versions": ["learning_composition.v2"],
                                     "actions": ["learning_example_runs.v1"] if run_capable else [],
                                 },
                             })
        assert result.status_code == 202, result.text
        return result.json()

    def control(action, **params):
        state = client.get(session_path).json()
        result = client.post(session_path + "/actions", json={
            "action": action, "client_action_id": str(uuid4()),
            "expected_session_revision": state["revision"], **params,
        })
        assert result.status_code == 200, result.text
        return result.json()

    shared_id = run(edited, share)
    if share:
        foreign = workflow.create_session("Another learner")
        version = {artifact["id"]: artifact["revision"]}
        with database.transaction(snapshot=True) as connection:
            lookup = Execution(connection).shared_teaching_example
            now = datetime.now(UTC)
            assert lookup(session.actor, conversation.id, version, now)["command_id"] == shared_id
            assert lookup(foreign.actor, conversation.id, version, now) is None
            assert lookup(session.actor, uuid4(), version, now) is None
            assert lookup(session.actor, conversation.id, {artifact["id"]: 2}, now) is None
    run(f"{render}('unshared_newer_edit')")
    run("failed_shared_attempt()", True, 1)
    wrapped = ask("这次练习先跳过。")
    deliver(node_scene, session, wrapped, "问候语已经讲完。", "wrap_up",
            choice={"choice": "defer", "quote": "练习先跳过"})
    state = client.get(session_path).json()
    assert state["active_branch_id"]
    returned = control("return_to_main", branch_id=state["active_branch_id"])
    assert returned["node_window"]["next_step"] == "wrap_up"
    next_node = control("finish_node", after_turn_id=wrapped["turn_id"], focus=returned["focus"])
    assert next_node["focus"]["node_key"] == "name"
    reopened = client.get(root + "?example_capability=learning_example_runs.v2").json()
    assert reopened["practice_only"] and reopened["example_runners"] == {
        "greeting_editor": [runtime.language],
    }
    practice_id = run(f"{render}('practice_after_finish')", True)
    with database.transaction(snapshot=True) as connection:
        execution = Execution(connection)
        now = datetime.now(UTC)
        reports = execution.reported_example_outcomes(
            session.actor, conversation.id, artifact["id"], artifact["revision"], now,
        )
        assert sum(row["report_count"] for row in reports) == 3
        assert all(row["command_id"] != practice_id for row in reports)
        shared = execution.shared_teaching_example(
            session.actor, conversation.id, {artifact["id"]: artifact["revision"]}, now,
        )
        assert (shared["command_id"] if shared else None) == (shared_id if share else None)
    asked = ask("在上节的问候上接着讲变量吧。", run_capable=not share)
    run(f"{render}('shared_after_this_question')", True)
    answer = {"text": "先把问候语放进一个变量。", "interaction": {"type": "none"},
              "pacing": {"next_step": "can_continue", "resume_at": "变量"}}
    gateway, sent, _ = provider(settings, author=json.dumps(answer))
    accepted = drain(tutor, settings, TurnAccepted(**asked), gateway, session.token)
    assert accepted.status == "accepted" and len(sent) == 2
    author = json.loads(sent[0]["messages"][1]["content"].removeprefix(CONTEXT_PREFIX))
    review = json.loads(sent[1]["messages"][-1]["content"])["turn_evidence"]
    work = author["observations"]["project_state"]["example_work"]
    assert work == review["observations"]["project_state"]["example_work"]
    assert all(("example_run_surface" in facts["workspace"]) == (not share)
               for facts in (author, review))
    assert (work["node_key"], work["source_turn_id"], work["artifact_id"], work["revision"],
            work["component_id"]) == (
                "text", artifact["source_turn_id"], artifact["id"], artifact["revision"],
                "greeting_editor",
            )
    assert work["code"]["text"] == (edited if share else starter) and not work["code"]["truncated"]
    if share:
        assert (work["basis"], work["command_id"], work["language"]) == (
            "shared_successful_run", shared_id, runtime.language,
        )
    else:
        assert work["basis"] == "published_example" and "command_id" not in work
    private = ["private_stdin", "private_stdout", "private_stderr", "unshared_newer_edit",
               "failed_shared_attempt", "shared_after_this_question", "practice_after_finish"]
    if not share:
        private.append("kept_earlier_feature")
    assert not any(value in json.dumps(sent) for value in private)


def test_context_refresh_preserves_changed_added_and_removed_fields():
    initial = {"execution_environments": {"engine": "ready"}, "materials": ["kept"], "old": 1}
    messages = [{"role": "system", "content": CONTEXT_PREFIX + json.dumps(initial)}]
    current = {"execution_environments": {"engine": "stopped"}, "materials": ["kept"], "new": None}
    assert TeachingContext.refresh_from_prompt(messages, current) == {
        "relative_to": "initial_learning_context",
        "changed": {"execution_environments": {"engine": "stopped"}, "new": None},
        "removed": ["old"],
    }


def test_preview_read_only_and_assessed_editors_keep_their_own_actions():
    definition = greeting_editor()
    presentation = {"definition": definition}
    assert ExampleRuns.editors(presentation) == ["greeting_editor"]
    mixed = {**presentation, "owner_bindings": [{"component_id": "other"}]}
    assert ExampleRuns.editors(mixed) == ["greeting_editor"]
    bound = {**presentation, "owner_bindings": [{"component_id": "greeting_editor"}]}
    assert not ExampleRuns.editors(bound)
    definition["states"]["greeting"]["read_only"] = True
    assert not ExampleRuns.editors(presentation)
    definition["states"]["greeting"]["read_only"] = False
    definition["components"].append({
        "id": "preview", "component": "IsolatedPreview", "props": {"html_state": "greeting"},
    })
    assert not ExampleRuns.editors(presentation)


@pytest.mark.skipif(os.getenv("LEORNIAN_TEST_DOCKER") != "1", reason="Real local C# runtime")
@pytest.mark.parametrize("node_scene", ["csharp-standard.v1"], indirect=True)
def test_csharp_greeting_draft_and_compiler_error_use_the_ungraded_runner(
    node_scene, session, database, workflow, runner,
):
    client, _, focus, conversation, tutor, settings = node_scene
    local = engineering_release("csharp")
    environments = ExecutionEnvironmentWorkflow(database)
    ready_engine(environments)
    work = claim(environments)
    release = environments.report(work.job_id, EnvironmentPreparationReport(
        claim_token=work.claim_token, outcome="ready",
        **{key: local[key] for key in (
            "runtime_version", "image_id", "image_ids", "toolchains", "verification",
        )},
    ))
    starter = 'string name = "小雨";\nConsole.WriteLine($"你好，{name}！欢迎开始学 C#。");\n'
    definition = greeting_editor()
    definition["states"]["greeting"]["value"] = starter
    accepted = client.post(f"/v1/conversations/{conversation.id}/turns", headers={
        "Idempotency-Key": str(uuid4()),
    }, json={
        "text": "我想把问候换成晚上好。", "focus": focus, "node_pacing": True,
        "teaching_session_revision": 1, "presentation_capabilities": {
            "versions": ["learning_composition.v2"], "actions": ["learning_example_runs.v1"],
        },
    })
    gateway, _, _ = composition_provider(
        settings, definition=definition, reply_text="把第二行的「你好」改成「晚上好」。",
        pacing={"next_step": "wait_for_action", "resume_at": "问候语"},
    )
    delivered = drain(tutor, settings, TurnAccepted(**accepted.json()), gateway, session.token)
    assert delivered.status == "accepted"
    root = f"/v2/conversations/{conversation.id}/learning-artifacts"
    card = client.get(root).json()[0]
    endpoint = root + "/" + card["id"] + "/example-runs"
    runtime = ProjectEnvironment(**release.environment())
    local = {**local, "id": str(release.id)}
    journey = JourneyWorkflow(database)

    def run(code):
        command = {"command_id": str(uuid4()), "component_id": "greeting_editor",
                   "expected_artifact_revision": card["revision"], "language": "csharp",
                   "code": code}
        assert client.post(endpoint, json=command).status_code == 202
        job = journey.claim("local-example-verification", [runtime])
        job_auth = ExecutionVerificationInput(claim_token=job.claim_token)
        release_auth = EnvironmentReleaseVerificationInput(
            profile=runtime.profile, language=runtime.language,
            runtime_version=runtime.runtime_version,
        )

        def authorize():
            return (
                journey.verify_execution(job.job_id, job_auth)["allowed"]
                and environments.verify_release(release.id, release_auth)["allowed"]
            )

        compilation, cases = runner.execute_stdio(
            job.program.model_dump(mode="json"), local, authorize=authorize,
        )
        journey.report(job.job_id, RunnerReport(
            claim_token=job.claim_token, compilation=compilation, cases=cases,
        ))
        return client.get(endpoint + "/" + command["command_id"]).json()

    edited = starter.replace("小雨", "阿岚").replace("你好", "晚上好")
    output = run(edited)
    assert output["status"] == "reported" and output["compilation"]["exit_code"] == 0
    assert output["output"]["stdout"].strip() == "晚上好，阿岚！欢迎开始学 C#。"
    broken = run(edited.replace(";", "", 1))
    assert broken["compilation"]["exit_code"] != 0 and broken["output"] is None
    assert not workflow.snapshot(session.token).execution_progress
