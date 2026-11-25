from uuid import UUID

from leornian.bootstrap.compositions import CompositionWorkflow
from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.modules.assessment.contracts import Submission
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import (
    ExecutionClaim,
    ProgramExecutionClaim,
    ProjectProgram,
)
from leornian.modules.execution.environments import Environments
from leornian.modules.execution.example_contracts import ExampleRunInput, ExampleRunResult
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.learning_artifact_contracts import PracticeSampleRunInput
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.shared_kernel.errors import BusinessError

ENTRYPOINTS = {
    "python": "main.py", "javascript": "main.js", "typescript": "main.ts",
    "java": "Main.java", "go": "main.go", "csharp": "Program.cs",
}


class ExampleRuns:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def editors(presentation):
        definition = presentation["definition"]
        bound = {
            binding["component_id"] for name in ("owner_bindings", "review_bindings")
            for binding in presentation.get(name, [])
        }
        reserved = {
            node["props"].get("state") for node in definition["components"] if node["id"] in bound
        } | {
            node["props"].get(key) for node in definition["components"]
            if node["component"] == "IsolatedPreview" for key in ("html_state", "css_state")
        }
        return [
            node["id"] for node in definition["components"]
            if node["component"] in {"CodeEditor", "CodeDiff"}
            and (key := node["props"]["state"]) not in reserved
            and (state := definition["states"][key])["type"] == "code"
            and not state.get("read_only")
        ]

    @staticmethod
    def environments(connection, actor, focus):
        if focus["kind"] != "node":
            return {}
        plan = Plans(connection).get(actor, UUID(str(focus["plan_id"])))
        revision = focus["expected_plan_revision"]
        if not plan.active or plan.active.revision != revision:
            raise BusinessError("stale_version", "路线已更新，请打开当前示例。")
        manifest = ExecutionEnvironmentWorkflow.route_manifest_in(connection, actor, plan, revision)
        result = {}
        environments = Environments(connection)
        for requirement in manifest.requirements:
            if requirement.profile != "project-stdio.v1":
                continue
            language = requirement.language
            result.setdefault(language, None)
            if manifest.engine.status != "ready":
                continue
            for demand in manifest.demands:
                if not demand.release or not (
                    environments.same_requirement(demand.requirement, requirement)
                    or environments.satisfies_base(demand, requirement)
                ):
                    continue
                try:
                    release = environments.require_release(
                        actor, demand.release.id, profile=requirement.profile, language=language,
                        plan_id=plan.id, plan_revision=revision,
                    )
                except BusinessError as error:
                    if error.code not in {"not_found", "stale_version", "precondition_failed"}:
                        raise
                    continue
                result[language] = release
                break
        return result

    @staticmethod
    def controls_in(connection, actor, focus, presentation, *, workspace=None):
        editors = ExampleRuns.editors(presentation)
        choices = ExampleRuns.environments(connection, actor, focus) if editors else {}
        languages = sorted(language for language, release in choices.items() if release)
        controls = dict.fromkeys(editors, languages) if choices else {}
        if workspace and workspace.editor in editors:
            controls[workspace.editor] = [lang for lang in languages if lang == workspace.language]
        return controls

    @staticmethod
    def sample(connection, actor, conversation_id, artifact, command):
        candidate = artifact
        if artifact["kind"] == "learning_composition":
            presentation, _, _ = CompositionWorkflow.current(
                connection, actor, conversation_id, artifact,
            )
            binding = next((binding for binding in presentation["owner_bindings"]
                            if binding["component_id"] == command.component_id), None)
            if not binding:
                raise BusinessError("not_found", "找不到这个组件绑定的公开题目。")
            candidate = LearningArtifacts(connection).candidate(
                actor, conversation_id, UUID(binding["source"]["id"]),
            )
        elif command.component_id != "editor":
            raise BusinessError("not_found", "找不到这个题目的编辑器。")
        if candidate["kind"] not in {"code_workspace", "sql_workspace", "project_workspace"}:
            raise BusinessError("precondition_failed", "这个组件不是可运行的题目。")
        _, public, item = LearningArtifactWorkflow.current(
            connection, actor, conversation_id, candidate,
            require_unanswered=False, allow_programs=True,
        )
        if public.language == "python_io":
            if not isinstance(command.answer, Submission):
                raise BusinessError("precondition_failed", "请提供这道题的 Python 代码。")
            return None, {"code": command.answer.code, "inputs": [public.sample.input]}
        try:
            program = item.execution(command.answer, sample_only=True)
        except ValueError as error:
            raise BusinessError("precondition_failed", str(error)) from error
        return public.environment.model_dump(mode="json"), {"program": program}

    @staticmethod
    def resolve(connection, actor, conversation_id, artifact_id, command, *, original_env=None):
        artifact = LearningArtifacts(connection).row(actor, conversation_id, artifact_id, lock=True)
        if (artifact["revision"] != command.expected_artifact_revision
                or artifact["state"] in {"cancelled", "superseded"}):
            raise BusinessError("stale_version", "请在当前可编辑的示例中运行。")
        practice = LearningArtifactWorkflow.practice_only(connection, actor, artifact)
        if isinstance(command, PracticeSampleRunInput):
            if not practice:
                raise BusinessError("precondition_failed", "当前工件尚未进入自由练习。")
            env, payload = ExampleRuns.sample(connection, actor, conversation_id, artifact, command)
            return env, payload, True
        if artifact["kind"] != "learning_composition" or (
            artifact["state"] != "ready" and not practice
        ):
            raise BusinessError("stale_version", "请在当前可编辑的示例中运行。")
        presentation, _, _ = CompositionWorkflow.current(
            connection, actor, conversation_id, artifact,
        )
        if command.component_id not in ExampleRuns.editors(presentation):
            raise BusinessError("precondition_failed", "这个组件不是独立的示例编辑器。")
        workspace = presentation["context_manifest"].get("example_workspace")
        if (workspace and workspace["editor"] == command.component_id
                and workspace["language"] != command.language):
            raise BusinessError("precondition_failed", "请使用这个示例声明的语言。")
        focus = artifact["focus"]
        if original_env is None:
            release = ExampleRuns.environments(connection, actor, focus).get(command.language)
            if release is None:
                raise BusinessError("precondition_failed", "本机语言环境尚未就绪。")
        else:
            release = Environments(connection).require_release(
                actor, UUID(original_env["environment_release_id"]), profile="project-stdio.v1",
                language=command.language, runtime_version=original_env["runtime_version"],
                plan_id=UUID(focus["plan_id"]), plan_revision=focus["expected_plan_revision"],
            )
        env = release.environment()
        filename = ENTRYPOINTS[command.language]
        program = ProjectProgram(
            **env, files=[{"path": filename, "content": command.code}],
            entrypoint=filename, inputs=[command.stdin],
        )
        payload = {"program": program, "interactive": True if command.interactive else None}
        return env, payload, practice

    @staticmethod
    def result(row):
        report = row["report"] or {}
        cases = report.get("cases") or []
        terminal = row.get("example_terminal")
        return ExampleRunResult(
            command_id=row["example_input"]["command_id"], status=row["status"],
            compilation=report.get("compilation"), output=cases[0] if cases else None,
            error_code=report.get("error_code"),
            terminal={
                "transcript": terminal["transcript"],
                "accepting_input": (
                    row["status"] == "running" and terminal["ready"] and not terminal["stopping"]
                ),
                "stopping": row["status"] == "running" and terminal["stopping"],
            } if terminal else None,
        )

    def submit(self, token, conversation_id, artifact_id, command):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            execution = Execution(connection)
            example = {
                **command.model_dump(mode="json"),
                "conversation_id": str(conversation_id), "artifact_id": str(artifact_id),
            }
            existing = execution.example(actor, command.command_id)
            if existing:
                if {key: value for key, value in existing["example_input"].items()
                    if key != "practice_only"} != example:
                    raise BusinessError("idempotency_conflict", "该运行请求已用于不同的草稿。")
                return self.result(existing)
            environment, _, practice = self.resolve(
                connection, actor, conversation_id, artifact_id, command,
            )
            if practice:
                example["practice_only"] = True
            return self.result(execution.enqueue_example(
                actor, Identity.digest(token), example, environment,
            ))

    @staticmethod
    def owned(execution, actor, conversation_id, artifact_id, command_id, *, lock=False):
        row = execution.example(actor, command_id, lock=lock)
        if not row or row["example_input"]["conversation_id"] != str(conversation_id) or (
            row["example_input"]["artifact_id"] != str(artifact_id)
        ):
            raise BusinessError("not_found", "没有找到这次示例运行。")
        return row

    def get(self, token, conversation_id, artifact_id, command_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = self.owned(Execution(connection), actor, conversation_id, artifact_id, command_id)
            return self.result(row)

    def control(self, token, conversation_id, artifact_id, command_id, *, line=None):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            execution = Execution(connection)
            identity = (execution, actor, conversation_id, artifact_id, command_id)
            row = self.owned(*identity)
            if not row["example_terminal"]:
                raise BusinessError("precondition_failed", "这次运行没有交互终端。")
            if line is not None:
                self.authorize(connection, row)
            row = self.owned(*identity, lock=True)
            if line is None:
                execution.stop_terminal(row)
            else:
                execution.send_terminal_line(row, line)
            return self.result(row)

    def exchange(self, job_id, data):
        with self.database.transaction() as connection:
            return Execution(connection).terminal_exchange(job_id, data)

    @staticmethod
    def authorize(connection, work):
        actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate_digest(
            work["session_digest"],
        )
        if actor.id != work["actor_id"]:
            raise BusinessError("unauthorized", "示例运行的账号已变更。")
        example = work["example_input"]
        schema = PracticeSampleRunInput if "answer" in example else ExampleRunInput
        command = schema(**{
            key: example[key] for key in schema.model_fields if key in example
        })
        environment, payload, practice = ExampleRuns.resolve(
            connection, actor, UUID(example["conversation_id"]),
            UUID(example["artifact_id"]), command, original_env=work["program_environment"],
        )
        if environment != work["program_environment"]:
            raise BusinessError("stale_version", "本次试跑的环境已变更。")
        return payload, practice

    @staticmethod
    def claim_in(connection, work):
        try:
            with connection.transaction():
                payload, _ = ExampleRuns.authorize(connection, work)
        except BusinessError as error:
            Execution(connection).abandon(work["id"], error.code)
            return None
        claim = ProgramExecutionClaim if "program" in payload else ExecutionClaim
        return claim(job_id=work["id"], claim_token=work["claim_token"], **payload)
