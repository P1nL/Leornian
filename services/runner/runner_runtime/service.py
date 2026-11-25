"""Task-scoped HTTP services with optional isolated writable databases."""

import json
import secrets
import subprocess

from .sandbox import (
    CleanupError,
    _bounded_container,
    _container_options,
    _docker,
    _mount,
    _new_volume,
    _project_options,
    _remove_container,
    _remove_volume,
    _stage_archive,
    _unavailable_cases,
)
from .sql import _sql_setup, _start_sql_server
from .stdio import _project_commands

_HTTP_CHECK = r"""
import http.client, json, socket, sys, time
requests = json.load(sys.stdin)
deadline = time.monotonic() + 20
while True:
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=1):
            break
    except OSError:
        if time.monotonic() >= deadline:
            raise SystemExit("The project did not listen on 127.0.0.1:8080 within 20 seconds.")
        time.sleep(.1)
responses = []
for request in requests:
    connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=3)
    try:
        body = request["body"].encode("utf-8") if request["body"] is not None else None
        connection.request(request["method"], request["path"], body=body,
                           headers={"Content-Type": request["content_type"]})
        response = connection.getresponse()
        if not 100 <= response.status <= 599:
            raise SystemExit("The service returned an invalid HTTP status.")
        content = response.read(3001)
        if len(content) > 3000:
            raise SystemExit("An HTTP response exceeded the 3000-byte response limit.")
        responses.append({"status": response.status, "body": content.decode("utf-8")})
    finally:
        connection.close()
print(json.dumps({"protocol":"http-scenario-result.v1","responses":responses},
                 ensure_ascii=False))
"""

_SQLITE_SETUP = r"""
import json, os, sqlite3, sys
sql = json.load(sys.stdin)
with sqlite3.connect("/data/course.sqlite") as database:
    database.executescript(sql)
os.chmod("/data/course.sqlite", 0o666)
"""


def _database_environment(program, scenario, release, volume, server, authorize):
    database = program["database"]
    if database is None:
        return [], []
    dialect = database["dialect"]
    data = {
        "dialect": dialect,
        "schema_definition": database["schema_definition"] or {"tables": []},
    }
    dataset = scenario["dataset"] or {
        "rows": {table["name"]: [] for table in data["schema_definition"]["tables"]},
    }
    _stage_archive(volume, [], release["image_ids"]["http_client"])
    if dialect == "sqlite":
        # Keep the bounded tmpfs mounted while seed and application containers exchange it.
        keeper = _container_options(server) + [
            "-d", "--mount", _mount(volume, "/data"), release["image_ids"]["http_client"],
            "python", "-I", "-B", "-c", "import time; time.sleep(600)",
        ]
        _docker(*keeper[1:])
        name = volume + "-seed"
        command = _container_options(name, user="0:0") + [
            "--mount", _mount(volume, "/data"), "-i", release["image_ids"]["http_client"],
            "python", "-I", "-B", "-c", _SQLITE_SETUP,
        ]
        result = _bounded_container(
            command, json.dumps(_sql_setup(data, dataset)).encode(), name, 8, authorize,
        )
        if result["outcome"] != "completed" or result["exit_code"] != 0:
            raise RuntimeError("The task's SQLite dataset could not be prepared.")
        return [
            "DATABASE_URL=sqlite:////data/course.sqlite",
            "LEORNIAN_DATABASE_PATH=/data/course.sqlite",
            "DB_DIALECT=sqlite",
        ], ["--mount", _mount(volume, "/data")]
    password = secrets.token_hex(24)
    _start_sql_server(
        data, dataset, volume, server, release["image_ids"]["database"], authorize,
        writable=True, password=password,
    )
    socket = "/database/" + (".s.PGSQL.5432" if dialect == "postgresql" else "mysql.sock")
    url = (
        f"postgresql://learner:{password}@127.0.0.1:5432/course" if dialect == "postgresql"
        else f"mysql://learner:{password}@127.0.0.1:3306/course"
    )
    return [
        "DATABASE_URL=" + url, "DB_DIALECT=" + dialect, "DB_NAME=course", "DB_USER=learner",
        "DB_HOST=127.0.0.1", "DB_PORT=" + ("5432" if dialect == "postgresql" else "3306"),
        "DB_PASSWORD=" + password, "DB_SOCKET=" + socket,
        "PGHOST=127.0.0.1", "PGPASSWORD=" + password, "PGUSER=learner", "PGDATABASE=course",
        "MYSQL_UNIX_PORT=/database/mysql.sock",
    ], ["--mount", _mount(volume, "/database", readonly=True)]


def _execute_scenario(program, scenario, release, source, build, runtime, authorize):
    prefix = "leornian-http-" + secrets.token_hex(10)
    app, server, volume = prefix + "-app", prefix + "-database", prefix + "-data"
    database = program["database"]
    if database:
        _new_volume(volume, temporary=database["dialect"] == "sqlite")
    try:
        environment, mounts = _database_environment(
            program, scenario, release, volume, server, authorize,
        )
        if authorize and not authorize():
            return _unavailable_cases(1, "execution_authorization_changed")[0]
        shared_database = database and database["dialect"] != "sqlite"
        command = _project_options(
            app, network="container:" + server if shared_database else "none",
        ) + [
            "-d", "--log-driver=local", "--log-opt=max-size=64k", "--log-opt=max-file=1",
            "--log-opt=compress=false",
            "--mount", _mount(source, "/workspace", readonly=True),
            "--mount", _mount(build, "/build", readonly=True), "--workdir=/workspace",
            "--env", "PORT=8080", "--env", "HOST=127.0.0.1", *mounts,
        ]
        for value in environment:
            command += ["--env", value]
        _docker(*command[1:], release["image_id"], *runtime)
        client = prefix + "-client"
        command = _container_options(
            client, network="container:" + (server if shared_database else app),
        ) + [
            "-i", release["image_ids"]["http_client"], "python", "-I", "-B", "-c",
            _HTTP_CHECK,
        ]
        return _bounded_container(
            command, json.dumps(scenario["requests"]).encode(), client, 40, authorize,
        )
    finally:
        try:
            _remove_container(app)
        finally:
            if database:
                try:
                    _remove_container(server)
                finally:
                    _remove_volume(volume)


def execute_http(program, release, authorize=None):
    from leornian.modules.execution.contracts import HttpProgram, HttpScenarioResult

    data = HttpProgram.model_validate(program).model_dump(mode="json")
    course = release.get("verification", {}).get("course_environment") if release else None
    if (
        not release or release["id"] != data["environment_release_id"]
        or release["profile"] != data["profile"] or release["language"] != data["language"]
        or release["runtime_version"] != data["runtime_version"]
        or not course or course["build"] != "http"
        or course.get("database") != (
            data["database"]["dialect"] if data["database"] else None
        )
        or "http_client" not in release["image_ids"]
    ):
        return None, _unavailable_cases(len(data["scenarios"]), "runner_environment_unavailable")
    if authorize and not authorize():
        return None, _unavailable_cases(len(data["scenarios"]), "execution_authorization_changed")
    source = "leornian-http-source-" + secrets.token_hex(10)
    build = source + "-build"
    _new_volume(source)
    try:
        _new_volume(build)
        try:
            files = data["files"]
            if data["language"] == "go" and not course.get("dependencies"):
                files = [*files, {
                    "path": "go.mod", "content": "module learner.local/project\n\ngo 1.26\n",
                }]
            _stage_archive(source, files, release["image_id"], course)
            _stage_archive(
                build, [], release["image_id"],
                course if data["language"] in {"javascript", "typescript"} else None,
            )
            compiler, runtime = _project_commands(data, course)
            compilation = None
            if compiler:
                name = build + "-compile"
                command = _project_options(name, memory="768m") + [
                    "--mount", _mount(source, "/workspace", readonly=True),
                    "--mount", _mount(build, "/build"), "--workdir=/workspace",
                    release["image_id"], *compiler,
                ]
                compilation = _bounded_container(command, b"", name, 90, authorize)
                if compilation["outcome"] != "completed" or compilation["exit_code"] != 0:
                    return compilation, []
            cases = []
            for scenario in data["scenarios"]:
                if authorize and not authorize():
                    cases.extend(_unavailable_cases(
                        len(data["scenarios"]) - len(cases), "execution_authorization_changed",
                    ))
                    break
                try:
                    result = _execute_scenario(
                        data, scenario, release, source, build, runtime, authorize,
                    )
                    if result["outcome"] == "completed" and result["exit_code"] == 0:
                        observations = HttpScenarioResult.model_validate_json(result["stdout"])
                        if len(observations.responses) != len(scenario["requests"]):
                            result = _unavailable_cases(1, "invalid_http_check_result")[0]
                    cases.append(result)
                except (RuntimeError, subprocess.TimeoutExpired) as error:
                    if isinstance(error, CleanupError):
                        raise
                    cases.append(_unavailable_cases(1, str(error))[0])
            return compilation, cases
        finally:
            _remove_volume(build)
    finally:
        _remove_volume(source)
