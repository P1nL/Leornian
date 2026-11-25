import importlib.util
import json
import os
import threading
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.bootstrap.program_execution import ProgramWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.program_contracts import ProgramPracticeSubmission
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import CaseOutput, HttpProgram, HttpRequest
from leornian.modules.execution.environment_contracts import (
    CourseEnvironment,
    EnvironmentDecisionInput,
    EnvironmentDemandInput,
)
from leornian.modules.execution.environment_recipes import course_recipe
from leornian.modules.execution.environment_runtime import EnvironmentInstaller
from leornian.modules.item_bank.program_contracts import HttpAnswer, HttpItem
from leornian.modules.item_bank.supply_contracts import SLOTS, PackRequest
from pydantic import ValidationError
from test_item_supply import finish, run_model
from test_item_supply import supply_setup as supply_setup

ROOT = Path(__file__).parents[2]
APPLICATION = '''
import json, os, sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
def connect():
    dialect = os.environ["DB_DIALECT"]
    if dialect == "sqlite":
        return sqlite3.connect(os.environ["LEORNIAN_DATABASE_PATH"]), "?"
    if dialect == "postgresql":
        import psycopg
        return psycopg.connect(host=os.environ["DB_HOST"], user="learner",
                              password=os.environ["DB_PASSWORD"], dbname="course"), "%s"
    import pymysql
    return pymysql.connect(host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
                           password=os.environ["DB_PASSWORD"],
                           user="learner", database="course"), "%s"
class Handler(BaseHTTPRequestHandler):
    def respond(self, status, value=None):
        body = json.dumps(value).encode() if value is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        database, marker = connect()
        try:
            cursor = database.cursor()
            if self.path == "/items":
                cursor.execute("SELECT COUNT(*) FROM records")
                return self.respond(200, {"count": cursor.fetchone()[0]})
            identity = int(self.path.rsplit("/", 1)[1])
            cursor.execute("SELECT value FROM records WHERE id=" + marker, (identity,))
            row = cursor.fetchone()
            self.respond(200, {"value": row[0]}) if row else self.respond(404, {})
        finally:
            database.close()
    def change(self, method):
        database, marker = connect()
        try:
            cursor = database.cursor()
            if method == "DELETE":
                identity = int(self.path.rsplit("/", 1)[1])
                cursor.execute("DELETE FROM records WHERE id=" + marker, (identity,))
                database.commit()
                return self.respond(204)
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if method == "POST":
                cursor.execute("INSERT INTO records VALUES (" + marker + "," + marker + ")",
                               (value["id"], value["value"]))
            else:
                cursor.execute("UPDATE records SET value=" + marker + " WHERE id=" + marker,
                               (value["value"], value["id"]))
            database.commit()
            self.respond(201 if method == "POST" else 200, {"id": value["id"]})
        finally:
            database.close()
    def do_POST(self): self.change("POST")
    def do_PUT(self): self.change("PUT")
    def do_DELETE(self): self.change("DELETE")
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
'''
SERVICE_SOURCES = {
    "python": ("main.py", '''
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"42")
HTTPServer(("127.0.0.1",8080),Handler).serve_forever()
'''),
    "javascript": (
        "main.js",
        "require('node:http').createServer((req,res)=>res.end('42')).listen(8080,'127.0.0.1');",
    ),
    "typescript": (
        "main.ts",
        "import {createServer} from 'node:http';"
        "createServer((req,res)=>res.end('42')).listen(8080,'127.0.0.1');",
    ),
    "java": ("Main.java", '''
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
class Main {
    public static void main(String[] args) throws Exception {
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",8080),0);
        server.createContext("/",exchange->{
            byte[] bytes="42".getBytes();
            exchange.sendResponseHeaders(200,bytes.length);
            exchange.getResponseBody().write(bytes); exchange.close();
        }); server.start();
    }
}
'''),
    "go": ("main.go", '''
package main
import ("fmt";"net/http")
func main() {
    http.HandleFunc("/",func(w http.ResponseWriter,r *http.Request){fmt.Fprint(w,"42")})
    http.ListenAndServe("127.0.0.1:8080",nil)
}
'''),
    "csharp": ("Program.cs", '''
var server=new System.Net.HttpListener();
server.Prefixes.Add("http://127.0.0.1:8080/"); server.Start();
while(true) {
    var request=server.GetContext();
    var bytes=System.Text.Encoding.UTF8.GetBytes("42");
    request.Response.ContentLength64=bytes.Length;
    request.Response.OutputStream.Write(bytes); request.Response.Close();
}
'''),
}


def http_item(environment=None, dialect="sqlite", source_id=None):
    tests = []
    for identity in (1, 2, 3):
        original, changed = f"item-{identity}", f"updated-{identity}"
        requests = [
            {"path": "/items"},
            {"method": "POST", "path": "/items", "body": json.dumps({
                "id": identity, "value": original,
            })},
            {"method": "PUT", "path": f"/items/{identity}", "body": json.dumps({
                "id": identity, "value": changed,
            })},
            {"path": f"/items/{identity}"},
            {"method": "DELETE", "path": f"/items/{identity}"},
            {"path": f"/items/{identity}"},
        ]
        expected = [
            {"status": 200, "body": '{"count":0}'},
            {"status": 201, "body": json.dumps({"id": identity})},
            {"status": 200, "body": json.dumps({"id": identity})},
            {"status": 200, "body": json.dumps({"value": changed})},
            {"status": 204, "body": ""},
            {"status": 404, "body": "{}"},
        ]
        if identity != 1:
            requests = [requests[1], requests[3]]
            expected = [expected[1], {"status": 200, "body": json.dumps({"value": original})}]
        tests.append({"scenario": {"requests": requests}, "expected": expected})
    return HttpItem(
        slot="practice_1", title="Records API",
        prompt="Create, update, fetch and delete a record using the declared task database.",
        difficulty=1, source_refs=[{"source_id": source_id or uuid4(), "revision": 1}],
        environment=environment or {
            "language": "python", "runtime_version": "3.12.0", "environment_release_id": uuid4(),
        },
        files=[{"path": "main.py", "content": "# Implement the records service.\n"}],
        entrypoint="main.py", database={
            "dialect": dialect, "schema_definition": {"tables": [{
                "name": "records", "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "value", "type": "text", "nullable": False},
                ],
            }]},
        },
        sample=tests[0], tests=tests, explanation="Each scenario observes actual database changes.",
    )


def test_http_program_keeps_private_gold_out_of_execution_and_preserves_manifest():
    item = http_item()
    execution = item.execution(HttpAnswer(files=[{"path": "main.py", "content": APPLICATION}]))
    assert isinstance(execution, HttpProgram) and len(execution.scenarios) == 3
    assert "expected" not in execution.model_dump_json()
    assert "tests" not in item.public().model_dump()
    with pytest.raises(ValueError, match="manifest"):
        item.execution(HttpAnswer(files=[{"path": "other.py", "content": APPLICATION}]))
    with pytest.raises(ValidationError):
        HttpRequest(path="//external.invalid/api")


def test_http_assessment_checks_status_and_body_and_exposes_only_the_selected_sample():
    item = http_item()
    row = {
        "id": uuid4(), "status": "queued", "purpose": "training",
        "comparison_profile": "http-response.v1", "comparison_order": None,
        "sample_case_index": 2,
        "test_cases": [case.model_dump(mode="json") for case in item.tests],
    }
    cases = [CaseOutput(
        stdout=json.dumps({"responses": case["expected"]}),
        stderr="", exit_code=0, outcome="completed",
    ) for case in row["test_cases"]]
    scorer = ProgramAssessment(Mock())
    passed = scorer.complete(row, cases)
    assert passed["status"] == "passed" and passed["passed_cases"] == 3
    assert passed["sample_result"]["output"]["responses"] == row["test_cases"][2]["expected"]
    changed = deepcopy(row["test_cases"][0]["expected"])
    changed[0]["status"] = 201
    cases[0] = cases[0].model_copy(update={"stdout": json.dumps({"responses": changed})})
    failed = scorer.complete(row, cases)
    assert failed["status"] == "not_passed" and failed["passed_cases"] == 2


def wait_for(read, predicate, *, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = read()
        if predicate(result):
            return result
        time.sleep(.2)
    raise AssertionError(f"Timed out waiting for the actual owner state: {result!r}")


def http_course(language, dialect=None):
    packages = []
    if dialect == "postgresql":
        packages = [{"name": name, "version": "3.3.8"} for name in ("psycopg", "psycopg-binary")]
    elif dialect == "mysql":
        packages = [
            {"name": "PyMySQL", "version": "1.1.2"},
            {"name": "cryptography", "version": "50.0.2"},
        ]
    return CourseEnvironment(
        language=language, title=f"HTTP / {language} / {dialect or 'no database'}",
        dependencies=packages, build="http", database=dialect,
    )


@pytest.mark.skipif(os.environ.get("LEORNIAN_TEST_DOCKER") != "1", reason="Real local Runner test")
@pytest.mark.parametrize(("language", "dialect"), [
    *[(language, None) for language in SERVICE_SOURCES],
    ("python", "postgresql"), ("python", "mysql"),
])
def test_actual_http_languages_and_database_drivers(tmp_path, language, dialect):
    source = ROOT / "services" / "runner" / "controller.py"
    spec = importlib.util.spec_from_file_location("http_language_controller", source)
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    installer = EnvironmentInstaller(tmp_path, verify_sql=controller.verify_sql_environment)
    existing = json.loads((ROOT / ".local/execution-environments/cache.json").read_text("utf-8"))
    installer.cache["recipes"].update(existing["recipes"])
    course = http_course(language, dialect)
    requirement = course_recipe(course).requirement
    prepared = installer.prepare(
        {"requirement": requirement.model_dump(mode="json")}, lambda _phase: True,
    )
    release = {
        **prepared, "id": str(uuid4()), "profile": "project-http.v1", "language": language,
    }
    if dialect:
        item = http_item({
            "language": language, "runtime_version": release["runtime_version"],
            "environment_release_id": release["id"],
        }, dialect)
        program = item.execution(
            HttpAnswer(files=[{"path": "main.py", "content": APPLICATION}]),
        ).model_dump(mode="json")
    else:
        entrypoint, code = SERVICE_SOURCES[language]
        program = {
            "profile": "project-http.v1", "language": language,
            "runtime_version": release["runtime_version"], "environment_release_id": release["id"],
            "files": [{"path": entrypoint, "content": code}], "entrypoint": entrypoint,
            "scenarios": [{"requests": [{"path": "/answer"}]}],
        }
    compilation, cases = controller.execute_http(program, release)
    if compilation is not None:
        assert compilation["outcome"] == "completed" and compilation["exit_code"] == 0, compilation
    assert len(cases) == len(program["scenarios"])
    assert all(case["outcome"] == "completed" and case["exit_code"] == 0 for case in cases), cases
    if dialect:
        assert all(ProgramAssessment.matches_http(case["stdout"], test.model_dump(mode="json"))
                   for case, test in zip(cases, item.tests, strict=True))
    else:
        assert json.loads(cases[0]["stdout"])["responses"] == [{"status": 200, "body": "42"}]
    record = ROOT / ".runtime/runner-service-20261117" / f"{language}-{dialect or 'http'}.json"
    record.parent.mkdir(exist_ok=True)
    record.write_text(json.dumps({
        "release": release, "compilation": compilation, "cases": cases,
    }, ensure_ascii=False, indent=2), "utf-8")


@pytest.mark.skipif(os.environ.get("LEORNIAN_TEST_DOCKER") != "1", reason="Real local Runner test")
def test_actual_controller_preparation_qualification_and_http_database_practice(
    database, session, supply_setup, monkeypatch, tmp_path,
):
    dialect = "sqlite"
    source = ROOT / "services" / "runner" / "controller.py"
    spec = importlib.util.spec_from_file_location("http_test_controller", source)
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    from runner_runtime import api_client, sandbox
    supply, tutor, settings, plan, material = supply_setup
    settings = replace(settings, runner_token="http-test-runner")
    cache = tmp_path / "cache"
    cache.mkdir()
    existing = json.loads((ROOT / ".local/execution-environments/cache.json").read_text("utf-8"))
    (cache / "cache.json").write_text(
        json.dumps({"recipes": existing["recipes"], "releases": {}}), "utf-8",
    )
    stop = tmp_path / "stop"
    monkeypatch.setenv("LEORNIAN_RUNNER_TOKEN", settings.runner_token)
    monkeypatch.setenv("LEORNIAN_RUNNER_CACHE_DIRECTORY", str(cache))
    monkeypatch.setattr(sandbox, "STOP_FILE", str(stop))
    failures = []
    with TestClient(create_app(settings=settings)) as client:
        def request(path, token, payload, *, timeout=10):
            response = client.post(path, json=payload, headers={"Authorization": "Bearer " + token})
            response.raise_for_status()
            return response.json()

        monkeypatch.setattr(api_client, "api", request)
        monkeypatch.setattr(controller, "api", request)

        def run():
            try:
                controller.main()
            except BaseException as error:
                failures.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        environments = ExecutionEnvironmentWorkflow(database)
        try:
            course = http_course("python", dialect)
            demand = environments.request(session.token, str(uuid4()), EnvironmentDemandInput(
                recipe_id=course_recipe(course).requirement.recipe_id, course_environment=course,
            ))
            assert demand.status == "waiting_authorization"
            environments.decide(session.token, demand.id, str(uuid4()), EnvironmentDecisionInput(
                decision="allow", expected_requirement_revision=1, expected_decision_revision=0,
            ))

            def current_demand():
                assert not failures, failures
                return next(value for value in environments.snapshot(session.token).demands
                            if value.id == demand.id)

            ready = wait_for(current_demand, lambda value: value.status in {
                "ready", "failed", "blocked_unknown",
            })
            assert ready.status == "ready", ready
            environment = ready.release.environment()
            base = http_item(environment, dialect, material.id)
            document = {"items": [base.model_copy(update={
                "slot": slot, "prompt": f"{base.prompt} Required scenario {index}.",
            }).model_dump(mode="json", exclude_defaults=True) for index, slot in enumerate(SLOTS)]}
            accepted = supply.submit(session.token, plan.id, str(uuid4()), PackRequest(
                expected_plan_revision=1, node_key="loops", instruction="HTTP records practice",
                kind="http_project", program_environment=environment, automatic=False,
            ))
            run_model(tutor, settings, accepted.run_id, document)
            pack = supply.get(session.token, accepted.pack_id)
            assert pack.status == "blind_solving", pack
            run_model(tutor, settings, pack.pending_run_id, {"programs": [{
                "slot": slot, "answer": {"type": "http", "files": [{
                    "path": "main.py", "content": APPLICATION,
                }]},
            } for slot in SLOTS]})
            qualified = wait_for(
                lambda: supply.get(session.token, accepted.pack_id),
                lambda value: value.status in {"reviewing", "failed"},
                seconds=600,
            )
            assert qualified.status == "reviewing", qualified
            finish(database, supply_setup, accepted)
            supply.publish(session.token, accepted.pack_id)
            flow = ProgramWorkflow(database)
            flow.training(session.token, accepted.pack_id)
            answer = HttpAnswer(files=[{"path": "main.py", "content": APPLICATION}])
            attempt = flow.submit_practice(
                session.token, accepted.pack_id, str(uuid4()),
                ProgramPracticeSubmission(slot="practice_1", answer=answer),
            )
            result = wait_for(lambda: flow.attempt(session.token, attempt.id),
                              lambda value: value.status != "queued")
            assert result.status == "passed" and result.passed_cases == 3, result
            assert len(result.sample_result.output.responses) == 6
            wrong = APPLICATION.replace('"value": row[0]', '"value": "wrong"')
            negative = flow.submit_practice(
                session.token, accepted.pack_id, str(uuid4()), ProgramPracticeSubmission(
                    slot="practice_1", previous_attempt_id=result.id,
                    answer=HttpAnswer(files=[{"path": "main.py", "content": wrong}]),
                ),
            )
            failed = wait_for(lambda: flow.attempt(session.token, negative.id),
                              lambda value: value.status != "queued")
            assert failed.status == "not_passed" and failed.passed_cases == 0, failed
            slow = APPLICATION.replace(
                "def do_GET(self):",
                'def do_GET(self):\n        __import__("time").sleep(60)',
            )
            pending = flow.submit_practice(
                session.token, accepted.pack_id, str(uuid4()), ProgramPracticeSubmission(
                    slot="practice_1", previous_attempt_id=failed.id,
                    answer=HttpAnswer(files=[{"path": "main.py", "content": slow}]),
                ),
            )
            wait_for(lambda: sandbox._docker(
                "ps", "--filter", "name=^/leornian-http-.*-app$", "--format", "{{.Names}}",
            ), bool, seconds=45)
            cancelled = flow.cancel(session.token, pending.id)
            assert cancelled.status == "error" and cancelled.error_code == "learner_cancelled"

            def temporary_resources():
                containers = sandbox._docker(
                    "ps", "-a", "--filter", "name=leornian-http-", "--format", "{{.Names}}",
                )
                volumes = sandbox._docker(
                    "volume", "ls", "--filter", "label=leornian.execution", "--format", "{{.Name}}",
                )
                return containers, [
                    name for name in volumes.splitlines() if name.startswith("leornian-http-")
                ]

            wait_for(temporary_resources, lambda values: not any(values), seconds=30)
            assert flow.attempt(session.token, pending.id).status == "error"
            output = ROOT / ".runtime" / "runner-service-20261117"
            output.mkdir(exist_ok=True)
            (output / f"{dialect}-queue.json").write_text(json.dumps({
                "environment": ready.model_dump(mode="json"),
                "pack": supply.get(session.token, accepted.pack_id).model_dump(mode="json"),
                "passed_attempt": result.model_dump(mode="json"),
                "failed_attempt": failed.model_dump(mode="json"),
                "cancelled_attempt": cancelled.model_dump(mode="json"),
            }, ensure_ascii=False, indent=2), "utf-8")
        finally:
            stop.touch()
            thread.join(timeout=55)
            assert not thread.is_alive(), "The original Runner did not stop and clean up."
            with database.transaction() as connection:
                pending = connection.execute(
                    "SELECT id,program_input_ref FROM execution.jobs WHERE actor_id=%s "
                    "AND status IN ('queued','running')", (session.actor.id,),
                ).fetchall()
                for work in pending:
                    Execution(connection).abandon(work["id"], "test_fixture_closed")
                    ProgramAssessment(connection).fail(
                        work["program_input_ref"], "Acceptance fixture stopped.",
                        "test_fixture_closed",
                    )
            assert not failures, failures
