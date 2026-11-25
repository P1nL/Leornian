"""Compile and run the maintained command-line project profiles."""

import json
import os
import re
import secrets
import subprocess
from pathlib import PurePosixPath

from .sandbox import (
    IMAGE,
    CleanupError,
    _bounded_container,
    _container_options,
    _docker,
    _mount,
    _new_volume,
    _project_options,
    _remove_volume,
    _stage_archive,
    _stage_volume,
    _unavailable_cases,
)


def execute_case(code: str, numbers: list[int], authorize=None) -> dict:
    name = "leornian-exec-" + secrets.token_hex(10)
    command = [
        "docker", "run", "--rm", "--name", name, "--pull=never", "--network=none",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=32", "--memory=128m", "--memory-swap=128m", "--cpus=0.5",
        "--user=65534:65534", "--ulimit", "nofile=64:64", "-i", IMAGE,
        "python", "-I", "-B", "-c", code,
    ]
    return _bounded_container(
        command, (json.dumps(numbers) + "\n").encode(), name, 6, authorize,
    )



def execute_project(program, authorize=None):
    from leornian.modules.execution.contracts import PythonProjectProgram

    data = PythonProjectProgram.model_validate(program).model_dump(mode="json")
    if authorize and not authorize():
        return _unavailable_cases(len(data["inputs"]), "execution_authorization_changed")
    try:
        image = _docker("image", "inspect", "--format", "{{.Id}}", IMAGE)
        if (
            data["runtime_version"] is not None
            and _python_versions(image)[0] != data["runtime_version"]
        ):
            raise RuntimeError("The exact Python project runtime changed.")
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        if isinstance(error, CleanupError):
            raise
        return [{
            "exit_code": None, "stdout": "", "stderr": str(error)[:1000],
            "outcome": "infrastructure_error",
        } for _values in data["inputs"]]
    volume = "leornian-project-" + secrets.token_hex(10)
    _new_volume(volume)
    try:
        _stage_volume(volume, data["files"], image)
        results = []
        for values in data["inputs"]:
            name = volume + "-" + secrets.token_hex(4)
            entrypoint = PurePosixPath("/workspace") / data["entrypoint"]
            bootstrap = (
                "import runpy,sys;sys.path[:0]="
                + repr([str(entrypoint.parent), "/workspace"]) + ";runpy.run_path("
                + repr(str(entrypoint))
                + ",run_name='__main__')"
            )
            command = _container_options(name) + [
                "--mount", _mount(volume, "/workspace", readonly=True),
                "--workdir=/workspace", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m,mode=1777",
                "-i", image, "python", "-I", "-B", "-c", bootstrap,
            ]
            result = _bounded_container(
                command, (json.dumps(values) + "\n").encode(), name, 6, authorize,
            )
            results.append(result)
        return results
    finally:
        _remove_volume(volume)



def _project_commands(data, course=None):
    language, entrypoint = data["language"], "/workspace/" + data["entrypoint"]
    paths = ["/workspace/" + item["path"] for item in data["files"]]
    if language == "python":
        return None, ["python", "-I", "-B", "-c", (
            "import runpy,sys;sys.path[:0]="
            + repr([str(PurePosixPath(entrypoint).parent), "/workspace"])
            + ";runpy.run_path(" + repr(entrypoint) + ",run_name='__main__')"
        )]
    if language == "javascript":
        return None, ["node", "--no-addons", entrypoint]
    if language == "typescript":
        return [
            "tsc", "--strict", "--target", "ES2022", "--module", "commonjs",
            "--typeRoots", "/opt/leornian/node_modules/@types"
            + (",/opt/leornian/course/node_modules/@types" if course else ""),
            *(["--baseUrl", "/opt/leornian/course/node_modules"] if course else []),
            "--rootDir", "/workspace", "--outDir", "/build", "--noEmitOnError",
            *[path for path in paths if path.endswith(".ts")],
        ], ["node", "--no-addons", "/build/" + data["entrypoint"][:-3] + ".js"]
    if language == "java":
        classpath = "/opt/leornian/course/lib/*"
        return [
            "javac", "-J-Xmx256m", "-J-XX:ActiveProcessorCount=2",
            *(["-cp", classpath] if course else []),
            "-d", "/build", *[path for path in paths if path.endswith(".java")],
        ], [
            "java", "-Xmx192m", "-XX:ActiveProcessorCount=2", "-cp",
            "/build:" + classpath if course else "/build", "Main",
        ]
    if language == "go":
        return [
            "env", "GO111MODULE=on", "GOWORK=off",
            "go", "build", "-mod=readonly", "-trimpath", "-o", "/build/program",
            "./" + str(PurePosixPath(data["entrypoint"]).parent),
        ], ["/build/program"]
    return [
        "sh", "-ceu",
        "mkdir -p /build/obj; "
        "cp /opt/leornian/template/obj/project.assets.json /build/obj/; "
        "dotnet build /opt/leornian/template/Project.csproj --no-restore --nologo "
        "--verbosity quiet -o /build -p:BaseIntermediateOutputPath=/build/obj/ "
        "-p:UseSharedCompilation=false",
    ], ["dotnet", "/build/LearnerProgram.dll"]



def execute_stdio(program, release, authorize=None, *, terminal=None):
    from leornian.modules.execution.contracts import ProjectProgram

    data = ProjectProgram.model_validate(program).model_dump(mode="json")
    if (
        not release or release["id"] != data["environment_release_id"]
        or release["runtime_version"] != data["runtime_version"]
        or release["language"] != data["language"] or release["profile"] != data["profile"]
    ):
        return None, _unavailable_cases(len(data["inputs"]), "runner_environment_unavailable")
    if authorize and not authorize():
        return None, _unavailable_cases(len(data["inputs"]), "environment_authorization_changed")
    image = release["image_id"]
    course = release.get("verification", {}).get("course_environment")
    source, build = (
        "leornian-project-" + secrets.token_hex(10),
        "leornian-build-" + secrets.token_hex(10),
    )
    _new_volume(source)
    try:
        _new_volume(build)
        try:
            files = data["files"]
            if data["language"] == "go" and not course:
                files = [*files, {
                    "path": "go.mod",
                    "content": "module learner.local/project\n\ngo 1.26\n",
                }]
            _stage_archive(source, files, image, course)
            _stage_archive(
                build, [], image,
                course if course and data["language"] in {"javascript", "typescript"} else None,
            )
            compiler, runtime = _project_commands(data, course)
            if terminal and data["language"] == "python":
                runtime.insert(1, "-u")
            compilation = None
            if compiler:
                name = build + "-compile"
                command = _project_options(name, memory="768m") + [
                    "--mount", _mount(source, "/workspace", readonly=True),
                    "--mount", _mount(build, "/build"), "--workdir=/workspace", image, *compiler,
                ]
                compilation = _bounded_container(command, b"", name, 90, authorize)
                if compilation["outcome"] != "completed" or compilation["exit_code"] != 0:
                    return compilation, []
            results = []
            for stdin in data["inputs"]:
                if authorize and not authorize():
                    results.extend(_unavailable_cases(
                        len(data["inputs"]) - len(results), "environment_authorization_changed",
                    ))
                    break
                name = source + "-" + secrets.token_hex(4)
                command = _project_options(name) + [
                    "--mount", _mount(source, "/workspace", readonly=True),
                    "--mount", _mount(build, "/build", readonly=True),
                    "--workdir=/workspace", "-i", image, *runtime,
                ]
                if terminal:
                    results.append(_bounded_container(
                        command, b"", name, 180, authorize, terminal=terminal,
                    ))
                    break
                results.append(_bounded_container(
                    command, stdin.encode("utf-8"), name, 8, authorize,
                ))
            return compilation, results
        finally:
            _remove_volume(build)
    finally:
        _remove_volume(source)



def _python_versions(image):
    name = "leornian-env-" + secrets.token_hex(10)
    command = _container_options(name) + [
        image, "python", "-I", "-B", "-c",
        "import json,sys,sqlite3;"
        "print(json.dumps([sys.version.split()[0],sqlite3.sqlite_version]))",
    ]
    result = _bounded_container(command, b"", name, 6)
    if result["outcome"] != "completed" or result["exit_code"]:
        raise RuntimeError("Cannot inspect the isolated Python runtime.")
    return json.loads(result["stdout"])



def program_environments():
    """Advertise only present local images and their observed exact runtime versions."""
    try:
        from leornian.modules.execution.contracts import ProgramExecutionClaim  # noqa: F401

        python, sqlite = _python_versions(IMAGE)
    except ImportError:
        return []  # The historical stdlib-only controller may still serve legacy Python.
    except RuntimeError as error:
        if isinstance(error, CleanupError):
            raise
        return []
    environments = [
        {"profile": "python-project-io.v1", "runtime_version": python},
        {"profile": "sql-query.v1", "dialect": "sqlite", "runtime_version": sqlite},
    ]
    client = os.environ.get("LEORNIAN_RUNNER_SQL_CLIENT_IMAGE", "leornian-sql-client:dev")
    present = subprocess.run(["docker", "image", "inspect", client], capture_output=True, timeout=8)
    if present.returncode:
        return environments
    for dialect, variable, default, binary in (
        ("postgresql", "LEORNIAN_RUNNER_POSTGRES_IMAGE", "postgres:15", "postgres"),
        ("mysql", "LEORNIAN_RUNNER_MYSQL_IMAGE", "mysql:8.0", "mysqld"),
    ):
        image = os.environ.get(variable, default)
        name = "leornian-env-" + secrets.token_hex(10)
        command = _container_options(name, user="999:999") + [
            "--entrypoint", binary, image, "--version",
        ]
        result = _bounded_container(command, b"", name, 6)
        match = re.search(r"\b[0-9]+\.[0-9]+(?:\.[0-9]+)?\b", result["stdout"])
        if result["outcome"] == "completed" and result["exit_code"] == 0 and match:
            environments.append({
                "profile": "sql-query.v1", "dialect": dialect,
                "runtime_version": match.group(),
            })
    return environments

