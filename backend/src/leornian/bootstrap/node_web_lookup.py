import json
from urllib.parse import urlsplit

from pydantic import ValidationError

from leornian.agent_runtime.contracts import ToolCall
from leornian.agent_runtime.repository import Runs
from leornian.agent_runtime.tools import NODE_WEB_TOOL, REGISTRY
from leornian.agent_runtime.web_lookup import lookup_evidence, lookup_request, supported_binding
from leornian.bootstrap.tutor_activity import TutorActivity
from leornian.modules.knowledge.source_catalog import catalog_resources
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


def public_scope(connection, actor, goal_id):
    scope = Learning(PgGoalStore(connection)).get_goal(actor, goal_id).material_scope
    return scope if scope and scope.authorized_public_sources else None


def available_tools(connection, settings, actor, goal_id):
    if not public_scope(connection, actor, goal_id):
        return ()
    try:
        binding = UserModels(connection, settings).binding(actor, "tutor.v1")
    except BusinessError as error:
        if error.code != "model_unavailable":
            raise
        return ()
    return (NODE_WEB_TOOL,) if supported_binding(binding) else ()


def begin_lookup(connection, actor, conversation, row, call, decision):
    tool = decision.tools[0]
    runs = Runs(connection)
    binding = call.context_manifest.get("model_binding")
    scope = public_scope(connection, actor, conversation.goal_id)
    if not scope or not supported_binding(binding):
        return {"status": "completed", "outcome": "not_enabled", "sources": []}
    try:
        args = REGISTRY[NODE_WEB_TOOL].validate(tool.arguments)
    except ValidationError:
        args = None
    tutor = Tutor(PgTutorStore(connection))
    turn = tutor.get_turn(conversation.id, row["input_ref"])
    if not args or turn.teaching_intent_id or any(
        not part.strip() or part not in turn.user_text for part in args.excerpts
    ):
        return {"status": "rejected", "code": "invalid_question",
                "next_action": "Copy the subject, parameter and question verbatim from the learner "
                               "into excerpts; use separate excerpts if they are not contiguous."}
    prior = next((result for result in runs.tool_outputs(row["id"], NODE_WEB_TOOL)
                  if result.get("lookup_call_id")), None)
    if prior:
        return prior
    excerpts = "\n".join(dict.fromkeys(args.excerpts))
    symbol = args.symbol if args.symbol and args.symbol not in excerpts and (
        args.symbol in turn.user_text or any(
            prior.context_focus == turn.context_focus
            and args.symbol in (prior.assistant_text or "")
            for prior in tutor.turns(conversation.id)
        )
    ) else None
    subject = " ".join(filter(None, [scope.language, scope.language_version,
                                     scope.framework, scope.framework_version, symbol]))
    host = next((urlsplit(item["url"]).hostname for item in
                 catalog_resources(scope.language, scope.framework)
                 if item["origin"] == "official" and (scope.framework or not item["frameworks"])),
                None) if scope.language or scope.framework else None
    host_hint = f"Course documentation host: {host}" if host else ""
    question = "\n".join(filter(None, [subject, host_hint, excerpts]))
    request, policy = lookup_request(binding, call.policy_snapshot, question)
    runs.messages(row["id"], [*row["messages"], decision.assistant_message])
    runs.applied(call.id)
    runs.prepare(row["id"], call.endpoint, request, policy, {
        "model_binding": binding, "node_web_lookup": {
            "goal_id": str(conversation.goal_id), "author_call_id": str(call.id),
            "tool": tool.model_dump(mode="json"),
        },
    })
    return None


def finish_lookup(connection, row, call, *, not_authorized=False):
    origin = call.context_manifest["node_web_lookup"]
    tool = ToolCall(**origin["tool"])
    sources = lookup_evidence(call.response_body) if call.status == "result_recorded" else []
    result = {
        "status": "completed", "lookup_call_id": str(call.id),
        "outcome": ("not_authorized" if not_authorized else "provider_rejected"
                    if call.status == "failed_known" else "found" if sources else "no_sources"),
        "sources": sources,
    }
    runs = Runs(connection)
    activity = runs.tool(row["id"], origin["author_call_id"], tool, result)
    TutorActivity.tool(connection, row, activity, tool, result, 0)
    runs.messages(row["id"], [*row["messages"], {
        "role": "tool", "tool_call_id": tool.id, "content": json.dumps(result, ensure_ascii=False),
    }])
    runs.applied(call.id)
