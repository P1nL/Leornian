"""Trusted host controller operations. Learner sources never enter this preparation path."""

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from leornian.modules.execution.environment_recipes import recipe


class PreparationStopped(RuntimeError):
    pass


class EnvironmentCleanupError(RuntimeError):
    pass


class UnsupportedDockerEndpoint(RuntimeError):
    pass


def local_docker_endpoint(endpoint):
    parsed = urlparse(endpoint)
    if parsed.query or parsed.fragment:
        return False
    if parsed.scheme == "unix":
        return not parsed.netloc and parsed.path.startswith("/")
    if parsed.scheme == "npipe":
        return (
            not parsed.netloc and parsed.path.lower().startswith("//./pipe/")
        ) or (
            parsed.netloc == "." and parsed.path.lower().startswith("/pipe/")
        )
    return False


def pin_local_engine():
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = None if context else os.environ.get("DOCKER_HOST")
    if not endpoint:
        result = subprocess.run(
            ["docker", "context", "inspect", *([context] if context else []),
             "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True,
            timeout=8,
        )
        if result.returncode:
            raise OSError("Cannot resolve the local Docker endpoint.")
        endpoint = result.stdout.decode("utf-8").strip()
    if not local_docker_endpoint(endpoint):
        raise UnsupportedDockerEndpoint("Select a local Docker named pipe or Unix socket.")
    # Keep execution and cleanup on the same device even if the user switches context.
    os.environ["DOCKER_HOST"] = endpoint
    os.environ.pop("DOCKER_CONTEXT", None)
    return endpoint


def engine_observation(runner_id="local-docker"):
    base = {"runner_id": runner_id, "version": None, "operating_system": None}
    if not shutil.which("docker"):
        return {**base, "status": "missing", "detail": "未找到 Docker；请先明确安装本机隔离引擎。"}
    try:
        pin_local_engine()
        result = subprocess.run(
            ["docker", "info", "--format", "{{json .}}"],
            capture_output=True,
            timeout=8,
        )
        if result.returncode:
            return {**base, "status": "stopped", "detail": "Docker 已安装；请启动本机隔离引擎。"}
        data = json.loads(result.stdout)
        linux = data.get("OSType") == "linux"
        return {
            **base,
            "status": "ready" if linux else "unsupported",
            "version": data.get("ServerVersion"),
            "operating_system": data.get("OSType"),
            "detail": "本机 Linux 隔离引擎已就绪。" if linux else "课程环境需要 Linux 容器模式。",
        }
    except UnsupportedDockerEndpoint:
        return {
            **base, "status": "unsupported",
            "detail": "请选择本机 Docker 的命名管道或 Unix 套接字；此应用不连接远程执行引擎。",
        }
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {**base, "status": "stopped", "detail": "本机隔离引擎未响应；请检查 Docker 状态。"}


class EnvironmentInstaller:
    def __init__(self, cache_directory=None, verify_sql=None):
        root = Path(__file__).resolve().parents[5]
        self.context = Path(
            os.environ.get(
                "LEORNIAN_RUNNER_RECIPE_DIRECTORY",
                root / "services" / "runner",
            )
        )
        self.directory = Path(
            cache_directory
            or os.environ.get(
                "LEORNIAN_RUNNER_CACHE_DIRECTORY",
                root / ".local" / "execution-environments",
            )
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.directory / "cache.json"
        self.verify_sql = verify_sql
        self.cache = {"recipes": {}, "releases": {}}
        if self.cache_file.exists():
            self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    def save(self):
        temporary = self.cache_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.cache, ensure_ascii=True), encoding="utf-8")
        temporary.replace(self.cache_file)

    @staticmethod
    def image(name):
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", name],
            capture_output=True,
            timeout=10,
        )
        return result.stdout.decode().strip() if result.returncode == 0 else None

    @staticmethod
    def operation(arguments, progress, phase, timeout=900):
        # Only a bounded tail of maintained public dependency output enters an error receipt.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                ["docker", *arguments],
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + timeout
            next_heartbeat = 0.0
            try:
                while process.poll() is None:
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        if not progress(phase):
                            raise PreparationStopped("Environment authorization changed.")
                        next_heartbeat = now + 10
                    if now >= deadline:
                        raise PreparationStopped("Environment preparation timed out.")
                    time.sleep(0.2)
                if process.returncode:
                    output.seek(0, 2)
                    output.seek(max(0, output.tell() - 3000))
                    raise RuntimeError(output.read().decode("utf-8", errors="replace"))
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)

    def _ensure_image(self, name, progress):
        found = self.image(name)
        if not found:
            self.operation(["pull", name], progress, "downloading")
            found = self.image(name)
        if not found:
            raise RuntimeError("Downloaded dependency image is unavailable.")
        return found

    @staticmethod
    def _run(
        image, arguments, *, user="65534:65534", timeout=25, stdin=None, should_continue=None
    ):
        name = "leornian-env-verify-" + secrets.token_hex(8)
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            "leornian.environment.verification=true",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=192",
            "--memory=768m",
            "--memory-swap=768m",
            "--cpus=1",
            "--user=" + user,
            "--tmpfs",
            "/tmp:rw,exec,nosuid,size=256m,mode=1777",
            "--env",
            "HOME=/tmp",
            "--env",
            "DOTNET_CLI_HOME=/tmp/dotnet",
            "--env",
            "DOTNET_CLI_TELEMETRY_OPTOUT=1",
        ]
        if stdin is not None:
            command.append("-i")
        process = None
        try:
            if should_continue and not should_continue():
                raise PreparationStopped("Environment verification is no longer authorized.")
            process = subprocess.Popen(
                [*command, image, *arguments],
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            deadline = time.monotonic() + timeout
            while True:
                if should_continue and not should_continue():
                    raise PreparationStopped("Environment verification is no longer authorized.")
                if time.monotonic() >= deadline:
                    raise PreparationStopped("Environment verification timed out.")
                try:
                    stdout, stderr = process.communicate(input=stdin, timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    stdin = None
            if process.returncode:
                raise RuntimeError(stderr.decode("utf-8", errors="replace")[-2000:])
            return stdout.decode("utf-8").strip()
        finally:
            try:
                try:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=8)
                finally:
                    removed = subprocess.run(
                        ["docker", "rm", "--force", name],
                        capture_output=True,
                        timeout=10,
                    )
                    if removed.returncode:
                        absent = subprocess.run(
                            ["docker", "inspect", name],
                            capture_output=True,
                            timeout=8,
                        )
                        if absent.returncode == 0 or b"No such object" not in absent.stderr:
                            raise EnvironmentCleanupError(
                                "Could not confirm that the verification container stopped."
                            )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise EnvironmentCleanupError(
                    "Could not confirm that the environment verification container stopped."
                ) from error

    def verify(self, maintained, images, should_continue=None):
        def run(image, arguments, **options):
            return self._run(image, arguments, should_continue=should_continue, **options)

        language = maintained.requirement.language
        image = images["runtime"]
        commands = {
            "python": [
                "python",
                "-I",
                "-B",
                "-c",
                "import sys; print(sys.version.split()[0]); assert 2+3==5",
            ],
            "javascript": ["node", "-e", "console.log(process.versions.node);if(2+3!==5)throw 1"],
            "typescript": [
                "node",
                "-e",
                "const t=require('/opt/leornian/node_modules/typescript');"
                "const s=t.transpileModule('const x:number=5;console.log(x)',"
                "{compilerOptions:{strict:true}}).outputText;"
                "if(!s.includes('console.log'))throw 1;console.log(process.versions.node)",
            ],
            "java": [
                "sh",
                "-ceu",
                "cd /tmp; printf 'class Main { public static void main(String[] a) "
                "{System.out.print(5);} }' > Main.java; javac Main.java; "
                'test "$(java Main)" = 5; java -version 2>&1',
            ],
            "go": [
                "sh",
                "-ceu",
                "cd /tmp; printf 'package main\\nimport \"fmt\"\\nfunc main(){fmt.Print(5)}' "
                "> main.go; GOCACHE=/tmp/cache GO111MODULE=off GOPROXY=off "
                'go build -o /tmp/smoke main.go; test "$(/tmp/smoke)" = 5; go version',
            ],
            "csharp": [
                "sh",
                "-ceu",
                "dotnet new console --no-restore -o /tmp/smoke >/dev/null; "
                "printf 'System.Console.Write(5);' > /tmp/smoke/Program.cs; "
                "dotnet restore /tmp/smoke --ignore-failed-sources >/dev/null; "
                "dotnet build /tmp/smoke --no-restore -v:q >/dev/null; "
                'test "$(dotnet /tmp/smoke/bin/Debug/net10.0/smoke.dll)" = 5; '
                "dotnet --version",
            ],
            "html-css": [
                "python",
                "-I",
                "-B",
                "-c",
                "from playwright.sync_api import sync_playwright\n"
                "with sync_playwright() as p:\n"
                " b=p.chromium.launch(headless=True,chromium_sandbox=False,"
                "args=['--disable-dev-shm-usage'])\n"
                " page=b.new_page();page.set_content('<p id=\"x\">ready</p>')\n"
                " assert page.locator('#x').inner_text()=='ready'\n"
                " print(b.version);b.close()",
            ],
        }
        if language == "sql":
            dialect = maintained.requirement.dialect
            if dialect == "sqlite":
                text = run(
                    image,
                    [
                        "python",
                        "-I",
                        "-B",
                        "-c",
                        "import sqlite3; c=sqlite3.connect(':memory:');"
                        "assert c.execute('select 2+3').fetchone()[0]==5;"
                        "print(sqlite3.sqlite_version)",
                    ],
                )
            else:
                binary = "postgres" if dialect == "postgresql" else "mysqld"
                text = run(images["server"], [binary, "--version"], user="999:999")
                run(image, ["python", "-I", "-B", "-c", "import psycopg,pymysql;print('ok')"])
        else:
            text = run(
                image,
                commands[language],
                timeout=90 if language in {"go", "csharp"} else 40,
            )
        match = re.search(r"(?<![0-9])([0-9]+\.[0-9]+(?:\.[0-9]+){0,2})", text)
        if match is None:
            raise RuntimeError("The isolated runtime did not report an exact version.")
        runtime = match.group(1)
        toolchains = {language: runtime}
        if language == "java":
            toolchains["java_observed"] = text[:800]
        if language == "typescript":
            toolchains["typescript"] = run(image, ["tsc", "--version"]).split()[-1]
            toolchains["node"] = runtime
        if language == "csharp":
            text = run(image, ["dotnet", "--list-runtimes"])
            toolchains["dotnet_runtime"] = next(
                line.split()[1]
                for line in text.splitlines()
                if line.startswith("Microsoft.NETCore.App ")
            )
        python_dependencies = maintained.requirement.dependency_lock
        if python_dependencies and all("==" in item for item in python_dependencies):
            expected = dict(item.split("==", 1) for item in python_dependencies)
            actual = json.loads(
                run(
                    image,
                    [
                        "python",
                        "-I",
                        "-B",
                        "-c",
                        "import importlib.metadata as m,json;"
                        "expected=" + repr(expected) + ";"
                        "actual={key:m.version(key) for key in expected};"
                        "assert actual==expected;print(json.dumps(actual))",
                    ],
                )
            )
            toolchains.update(actual)
        if maintained.requirement.recipe_id == "python-flask.v1":
            run(
                image,
                [
                    "python",
                    "-I",
                    "-B",
                    "-c",
                    "from flask import Flask; app=Flask(__name__);"
                    "app.add_url_rule('/',view_func=lambda:'ready');"
                    "assert app.test_client().get('/').data==b'ready';print('ok')",
                ],
            )
        if language == "sql" and maintained.requirement.dialect != "sqlite":
            if self.verify_sql is None:
                raise RuntimeError("SQL environment verification needs the local SQL controller.")
            self.verify_sql(
                images, maintained.requirement.dialect, runtime, authorize=should_continue
            )
        return runtime, toolchains

    def prepare(self, claim, progress, should_continue=None):
        from leornian.modules.execution.environment_contracts import CourseEnvironment

        declared = claim["requirement"].get("course_environment")
        course = CourseEnvironment.model_validate(declared) if declared is not None else None
        maintained = recipe(claim["requirement"]["recipe_id"], course)
        if maintained.requirement.model_dump(mode="json") != claim["requirement"]:
            raise PreparationStopped("The maintained recipe or requirement revision changed.")
        if not progress("downloading"):
            raise PreparationStopped("Environment installation is not authorized.")
        if course is not None:
            from leornian.modules.execution.course_dependencies import prepare_course

            return prepare_course(self, maintained, progress, should_continue)
        cached = self.cache["recipes"].get(maintained.requirement.recipe_id)
        if (
            cached
            and (
                cached["verification"].get("recipe_revision")
                == maintained.requirement.recipe_revision
                and cached["verification"].get("dependency_lock")
                == maintained.requirement.dependency_lock
            )
            and all(self.image(image) == image for image in cached["image_ids"].values())
        ):
            images = cached["image_ids"]
        else:
            base = self._ensure_image(maintained.base_image, progress)
            images = {"runtime": base, "base": base}
            for key, source in maintained.companion_images:
                images[key] = self._ensure_image(source, progress)
            if maintained.dockerfile:
                if not progress("building"):
                    raise PreparationStopped("Environment installation is no longer authorized.")
                pinned = "leornian-env-base:" + base.split(":")[1][:24]
                self.operation(["tag", base, pinned], progress, "building", timeout=15)
                tag = "leornian-env:" + maintained.requirement.recipe_id + "-r1"
                self.operation(
                    [
                        "build",
                        "--pull=false",
                        "--network=default",
                        "--build-arg",
                        "BASE_IMAGE=" + pinned,
                        "--label",
                        "leornian.environment.recipe=" + maintained.requirement.recipe_id,
                        "--label",
                        "leornian.environment.revision=1",
                        "--tag",
                        tag,
                        "--file",
                        str(self.context / maintained.dockerfile),
                        str(self.context),
                    ],
                    progress,
                    "building",
                )
                images["runtime"] = self.image(tag)
                if not images["runtime"]:
                    raise RuntimeError("Built course image was not registered.")
        if not progress("verifying"):
            raise PreparationStopped("Environment verification is no longer authorized.")
        version, toolchains = self.verify(maintained, images, should_continue)
        result = {
            "outcome": "ready",
            "runtime_version": version,
            "image_id": images["runtime"],
            "image_ids": images,
            "toolchains": toolchains,
            "verification": {
                "isolated": True,
                "smoke": True,
                "learner_network": "none",
                "recipe_id": maintained.requirement.recipe_id,
                "recipe_revision": maintained.requirement.recipe_revision,
                "dependency_lock": maintained.requirement.dependency_lock,
            },
        }
        self.cache["recipes"][maintained.requirement.recipe_id] = result
        self.save()
        return result

    def register_release(self, release):
        self.cache["releases"][release["id"]] = release
        self.save()

    def release(self, release_id):
        release = self.cache["releases"].get(str(release_id))
        if not release or any(
            self.image(image) != image for image in release["image_ids"].values()
        ):
            return None
        return release

    def program_environments(self):
        result, missing = [], []
        for release_id, release in self.cache["releases"].items():
            if not self.release(release_id):
                missing.append(release_id)
                continue
            value = {
                "profile": release["profile"],
                "runtime_version": release["runtime_version"],
                "environment_release_id": release_id,
            }
            if release["profile"] == "sql-query.v1":
                value["dialect"] = release["dialect"]
            else:
                value["language"] = release["language"]
            result.append(value)
        return result[-60:], missing
