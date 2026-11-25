import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import rag as rag
from test_material_sources_and_goals import start_goal_search

from leornian.agent_runtime.gateway import ChatCompletionsGateway, ModelProtocolError
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_goal_coverage import (
    MaterialGoalCoverageWorkflow,
    validate_repaired_assessment,
)
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.knowledge.goal_coverage_contracts import (
    MATERIAL_GOAL_SUMMARY_LIMIT,
    MaterialGoalVerdict,
)
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.knowledge.retrieval_contracts import MaterialCoverage

PRIVATE_REASONING = "PRIVATE_REASONING_MUST_STAY_IN_THE_ORIGINAL_LEDGER"


@pytest.mark.parametrize(("receipt", "expected"), [
    ("result_recorded", "node_material_review_failed"), ("unknown", "external_result_unknown"),
])
def test_node_aggregate_after_format_repair_distinguishes_known_and_unknown_receipts(
    monkeypatch, receipt, expected,
):
    monkeypatch.setattr(Runs, "lock", lambda *_: {
        "status": "failed", "error_code": "invalid_material_goal_output", "cancel_requested": False,
    })
    monkeypatch.setattr(Runs, "latest", lambda *_: SimpleNamespace(status=receipt))
    part = {"state": "waiting_dependency", "run_id": "same-run", "child_ids": ["first", "next"]}
    demand = SimpleNamespace(consumer_ref="node-material:route:node")
    assert MaterialGoalCoverageWorkflow.blockage(None, part, demand) == expected


def test_material_goal_summary_schema_prompt_and_validation_share_the_same_limit():
    role = MaterialGoalCoverageWorkflow.make_role("Learn grouping", [])
    payload = json.loads(role.messages[1]["content"])
    assert MATERIAL_GOAL_SUMMARY_LIMIT == 4000
    assert payload["schema"]["properties"]["summary"]["maxLength"] == MATERIAL_GOAL_SUMMARY_LIMIT
    synopsis_schema = MaterialCoverage.model_json_schema()["properties"]["synopsis"]
    assert synopsis_schema["anyOf"][0]["maxLength"] == MATERIAL_GOAL_SUMMARY_LIMIT
    assert f"summary <={MATERIAL_GOAL_SUMMARY_LIMIT} characters" in role.messages[0]["content"]
    assert f"about {MATERIAL_GOAL_SUMMARY_LIMIT // 2} characters" in role.messages[0]["content"]
    data = {
        "status": "missing", "summary": "x" * MATERIAL_GOAL_SUMMARY_LIMIT, "evidence_refs": []
    }
    assert len(MaterialGoalVerdict(**data).summary) == MATERIAL_GOAL_SUMMARY_LIMIT
    with pytest.raises(ValidationError):
        MaterialGoalVerdict(**{**data, "summary": data["summary"] + "x"})


def test_protocol_correction_cannot_drop_a_negative_assessment_or_upgrade_it():
    previous = {"status": "missing", "issues": ["irrelevant"], "findings": []}
    valid = MaterialGoalVerdict(
        status="missing", summary="No relevant explanation.", evidence_refs=[],
        issues=["irrelevant"],
    )
    validate_repaired_assessment(valid, previous)
    for changed in (
        valid.model_copy(update={"issues": []}),
        valid.model_copy(update={"status": "partial"}),
        valid.model_copy(update={"status": "supported"}),
    ):
        with pytest.raises(ModelProtocolError):
            validate_repaired_assessment(changed, previous)


@pytest.fixture
def repair_case(database, session, rag, monkeypatch):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings, demand, searcher, search, original = start_goal_search(database, session, rag)
    searcher.execute(search.id, rag["transport"])
    with database.transaction() as connection:
        part = connection.execute(
            "SELECT * FROM knowledge.material_goal_coverage_parts WHERE search_id=%s",
            (search.id,),
        ).fetchone()
        admission = Runs(connection).admission_snapshot(session.actor.id, part["run_id"])
    return {
        "settings": settings, "demand": demand, "searcher": searcher, "search": search,
        "original": original, "part": part, "admission": admission,
        "tutor": TutorWorkflow(database, settings), "transport": rag["transport"],
    }


def correction_gateway(
    settings, *, problem="summary", always_invalid=False, summary_lengths=(), ref_span_steps=()
):
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        payload = json.loads(wire["messages"][1]["content"])
        refs = [item["ref"] for item in payload["source_parts"]]
        invalid = len(sent) == 1 or always_invalid
        summary = (
            "x" * summary_lengths[len(sent) - 1]
            if len(sent) <= len(summary_lengths)
            else "x" * (MATERIAL_GOAL_SUMMARY_LIMIT + 1)
            if invalid and problem == "summary"
            else "A loop visits each item in the sequence."
        )
        result = {
            "status": "supported",
            "summary": summary,
            "evidence_refs": refs,
            "reviewed_refs": refs[:-1] if invalid and problem == "refs" else refs,
            "reviewed_parts": [],
        }
        if problem == "reviewed_parts" and invalid:
            result["reviewed_parts"] = [ref["block_id"] for ref in refs]
        if problem == "defective_evidence":
            result.update(
                status="partial" if invalid else "missing",
                issues=["irrelevant"],
                findings=[{
                    "issue": "irrelevant", "scope": "document", "refs": refs[:1],
                    "topics": ["iteration"],
                    "explanation": "This document does not explain the required behavior.",
                }],
                evidence_refs=refs if invalid else [],
            )
        if (invalid and problem == "ref_span") or len(sent) in ref_span_steps:
            result["evidence_refs"] = refs[:-1] + [{
                **refs[-1],
                "span": {**refs[-1]["span"], "start": refs[-1]["span"]["start"] - 1},
            }]
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": json.dumps(result),
                    "reasoning_content": PRIVATE_REASONING,
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        })

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), sent


@pytest.mark.parametrize("problem", ["reviewed_parts", "defective_evidence"])
def test_goal_repair_explains_field_relationships_and_preserves_negative_findings(
    database, session, repair_case, problem,
):
    case = repair_case
    run_id = case["part"]["run_id"]
    gateway, sent = correction_gateway(case["settings"], problem=problem)
    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    with database.transaction() as connection:
        row = Runs(connection).lock(run_id)
        feedback = json.loads(row["messages"][-1]["content"])["material_goal_format_repair"]
        scope = json.loads(row["messages"][1]["content"])["check_scope"]
    assert scope["kind"] == "source" and scope["expected_reviewed_parts"] == []
    if problem == "reviewed_parts":
        assert feedback["issues"][0]["path"] == "reviewed_parts"
        assert feedback["issues"][0]["expected"] == []
    else:
        assert feedback["issues"][0]["code"] == "defective_evidence"
        assert feedback["preserve_assessment"]["issues"] == ["irrelevant"]
        assert feedback["issues"][0]["conflicting_findings"]
    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    search = case["searcher"].get(session.token, case["search"].id)
    assert search.status == "ready" and len(sent) == 2
    with database.transaction() as connection:
        part = connection.execute(
            "SELECT result FROM knowledge.material_goal_coverage_parts WHERE id=%s",
            (case["part"]["id"],),
        ).fetchone()
    assert part["result"]["reviewed_parts"] == []
    if problem == "defective_evidence":
        assert part["result"]["status"] == "missing"
        assert part["result"]["issues"] == ["irrelevant"]
        assert part["result"]["findings"] and part["result"]["evidence_refs"] == []
    assert all(call["status"] == "result_recorded" for call in calls_for(database, run_id))


def calls_for(database, run_id):
    with database.transaction() as connection:
        return connection.execute(
            "SELECT id,step,status,applied,request,response_body FROM runtime.external_calls "
            "WHERE run_id=%s ORDER BY step", (run_id,),
        ).fetchall()


@pytest.mark.parametrize("problem", ["summary", "refs", "ref_span"])
def test_complete_invalid_goal_receipt_is_corrected_on_the_same_run_and_frozen_scope(
    database, session, repair_case, problem
):
    case = repair_case
    run_id = case["part"]["run_id"]
    gateway, sent = correction_gateway(case["settings"], problem=problem)
    AgentLoop(case["tutor"], gateway).run(run_id)
    first = calls_for(database, run_id)[0]
    assert first["status"] == "result_recorded" and not first["applied"]
    assert PRIVATE_REASONING in first["response_body"]
    with database.transaction() as connection:
        assert Runs(connection).get(
            session.actor.id, run_id
        ).error_code == "invalid_material_goal_output"
    assert case["searcher"].get(session.token, case["search"].id).status == "waiting_dependency"

    case["searcher"].execute(case["search"].id, case["transport"])
    case["searcher"].execute(case["search"].id, case["transport"])
    with database.transaction() as connection:
        part = connection.execute(
            "SELECT * FROM knowledge.material_goal_coverage_parts WHERE search_id=%s",
            (case["search"].id,),
        ).fetchone()
        runs = Runs(connection)
        row = runs.lock(run_id)
        assert part["id"] == case["part"]["id"] and part["run_id"] == run_id
        assert part["refs"] == case["part"]["refs"]
        assert part["model_binding"] == case["part"]["model_binding"]
        assert part["state"] == "running" and part["result"] is None
        assert runs.get(session.actor.id, run_id).status == "queued"
        assert runs.admission_snapshot(session.actor.id, run_id) == case["admission"]
        assert PRIVATE_REASONING not in json.dumps(row["messages"])
        assert row["messages"][-2]["content"] == json.loads(
            first["response_body"]
        )["choices"][0]["message"]["content"]
        assert row["messages"][-1]["role"] == "user"
        assert "material_goal_format_repair" in row["messages"][-1]["content"]
        feedback = json.loads(row["messages"][-1]["content"])["material_goal_format_repair"]
        if problem == "summary":
            issue = feedback["issues"][0]
            assert issue["actual_length"] == MATERIAL_GOAL_SUMMARY_LIMIT + 1
            assert issue["max_length"] == MATERIAL_GOAL_SUMMARY_LIMIT
            assert issue["target_length"] == MATERIAL_GOAL_SUMMARY_LIMIT // 2
        elif problem == "ref_span":
            issue = feedback["issues"][0]
            assert issue["code"] == "exact_ref_contract"
            mismatches = issue["mismatched_evidence_refs"]
            assert len(mismatches) == 1
            actual, allowed = mismatches[0]["actual_ref"], mismatches[0]["allowed_refs"]
            assert len(allowed) == 1 and allowed[0] in case["part"]["refs"]
            assert actual["span"]["start"] == allowed[0]["span"]["start"] - 1
            assert actual["span"]["end"] == allowed[0]["span"]["end"]
            assert actual["content_digest"] == allowed[0]["content_digest"]
    assert len(sent) == 1

    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    state = case["searcher"].get(session.token, case["search"].id)
    assert state.status == "ready"
    selection = case["searcher"].selection(session.token, state.selection_id)
    assert selection.coverage.status == "sufficient"
    assert selection.coverage.required[0].facet == case["demand"].goal_text
    calls = calls_for(database, run_id)
    assert len(calls) == len(sent) == 2
    assert [call["step"] for call in calls] == [1, 2]
    assert all(call["status"] == "result_recorded" and call["applied"] for call in calls)
    assert calls[0]["id"] == first["id"] and calls[0]["response_body"] == first["response_body"]
    assert calls[0]["request"] == first["request"]
    assert PRIVATE_REASONING not in json.dumps(sent[1])
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.material_goal_coverage_parts WHERE search_id=%s",
            (case["search"].id,),
        ).fetchone()["n"] == 1


@pytest.mark.parametrize("problem", ["summary", "refs"])
def test_repeated_same_invalid_goal_diagnostic_waits_without_another_identical_correction(
    database, session, repair_case, problem
):
    case = repair_case
    run_id = case["part"]["run_id"]
    gateway, sent = correction_gateway(case["settings"], problem=problem, always_invalid=True)
    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    AgentLoop(case["tutor"], gateway).run(run_id)
    for _ in range(2):
        case["searcher"].execute(case["search"].id, case["transport"])
    assert case["searcher"].get(session.token, case["search"].id).status == "waiting_dependency"
    calls = calls_for(database, run_id)
    assert len(calls) == len(sent) == 2
    assert calls[0]["applied"] and not calls[1]["applied"]
    with database.transaction() as connection:
        assert Runs(connection).get(session.actor.id, run_id).status == "failed"


def test_previously_rejected_legal_goal_receipt_resumes_without_a_new_call(
    database, session, repair_case, monkeypatch
):
    case = repair_case
    run_id = case["part"]["run_id"]
    gateway, sent = correction_gateway(case["settings"], summary_lengths=[1248])
    original_apply = MaterialGoalCoverageWorkflow.apply

    def legacy_apply(connection, actor, part_id, content, *, call_id=None):
        if len(json.loads(content)["summary"]) > 1200:
            raise ModelProtocolError("invalid_material_goal_output")
        return original_apply(connection, actor, part_id, content, call_id=call_id)

    with monkeypatch.context() as patch:
        patch.setattr(MaterialGoalCoverageWorkflow, "apply", staticmethod(legacy_apply))
        AgentLoop(case["tutor"], gateway).run(run_id)
    first = calls_for(database, run_id)[0]
    assert first["status"] == "result_recorded" and not first["applied"]
    with database.transaction() as connection:
        runs = Runs(connection)
        assert runs.get(session.actor.id, run_id).error_code == "invalid_material_goal_output"
        frozen_call = runs.latest(run_id).model_dump()
        frozen_messages = runs.lock(run_id)["messages"]

    case["searcher"].execute(case["search"].id, case["transport"])
    with database.transaction() as connection:
        runs = Runs(connection)
        row = runs.lock(run_id)
        assert row["status"] == "queued" and row["repair_base_messages"] is None
        assert row["messages"] == frozen_messages
        assert runs.latest(run_id).model_dump() == frozen_call
        assert runs.admission_snapshot(session.actor.id, run_id) == case["admission"]
        part = connection.execute(
            "SELECT * FROM knowledge.material_goal_coverage_parts WHERE id=%s",
            (case["part"]["id"],),
        ).fetchone()
        assert part["state"] == "running" and part["result"] is None
        assert part["refs"] == case["part"]["refs"]
        assert part["model_binding"] == case["part"]["model_binding"]
    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    search = case["searcher"].get(session.token, case["search"].id)
    selection = case["searcher"].selection(session.token, search.selection_id)
    assert search.status == "ready" and selection.coverage.status == "sufficient"
    assert selection.coverage.synopsis == "x" * 1248
    calls = calls_for(database, run_id)
    assert len(calls) == len(sent) == 1 and calls[0]["applied"]
    assert calls[0]["id"] == first["id"]
    assert calls[0]["request"] == first["request"]
    assert calls[0]["response_body"] == first["response_body"]
    assert PRIVATE_REASONING in calls[0]["response_body"]
    assert PRIVATE_REASONING not in json.dumps(sent[0])


@pytest.mark.parametrize("last_extra", [196, 296])
def test_shorter_oversized_goal_summaries_continue_until_length_stops_decreasing(
    database, session, repair_case, last_extra
):
    case = repair_case
    run_id = case["part"]["run_id"]
    lengths = [MATERIAL_GOAL_SUMMARY_LIMIT + extra for extra in (596, 396, 196, last_extra)]
    gateway, sent = correction_gateway(case["settings"], summary_lengths=lengths)
    for index, length in enumerate(lengths):
        AgentLoop(case["tutor"], gateway).run(run_id)
        calls = calls_for(database, run_id)
        assert len(calls) == len(sent) == index + 1
        assert not calls[-1]["applied"]
        case["searcher"].execute(case["search"].id, case["transport"])
        with database.transaction() as connection:
            row = Runs(connection).lock(run_id)
            if index == len(lengths) - 1:
                assert row["status"] == "failed"
            else:
                assert row["status"] == "queued"
                feedback = json.loads(
                    row["messages"][-1]["content"]
                )["material_goal_format_repair"]
                assert feedback["issues"][0]["actual_length"] == length
                assert feedback["issues"][0]["max_length"] == MATERIAL_GOAL_SUMMARY_LIMIT
                assert feedback["issues"][0]["target_length"] == MATERIAL_GOAL_SUMMARY_LIMIT // 2
                assert case["demand"].goal_text in row["messages"][1]["content"]
                assert PRIVATE_REASONING not in json.dumps(row["messages"])
    case["searcher"].execute(case["search"].id, case["transport"])
    AgentLoop(case["tutor"], gateway).run(run_id)
    calls = calls_for(database, run_id)
    assert len(calls) == len(sent) == len(lengths)
    assert all(call["applied"] for call in calls[:-1]) and not calls[-1]["applied"]
    assert case["searcher"].get(session.token, case["search"].id).status == "waiting_dependency"


def test_legacy_generic_summary_feedback_allows_one_new_length_specific_correction(
    database, session, repair_case, monkeypatch
):
    case = repair_case
    run_id = case["part"]["run_id"]
    lengths = [MATERIAL_GOAL_SUMMARY_LIMIT + extra for extra in (596, 396)]
    gateway, sent = correction_gateway(case["settings"], summary_lengths=lengths)
    AgentLoop(case["tutor"], gateway).run(run_id)
    original_repair = Runs.repair

    def legacy_repair(self, row, digest, messages, call):
        feedback = json.loads(messages[-1]["content"])["material_goal_format_repair"]
        for issue in feedback["issues"]:
            for key in ("actual_length", "max_length", "target_length"):
                issue.pop(key, None)
        feedback["instruction"] = "Correct the final JSON using the supplied schema."
        messages[-1]["content"] = json.dumps({"material_goal_format_repair": feedback})
        return original_repair(self, row, digest, messages, call)

    with monkeypatch.context() as patch:
        patch.setattr(Runs, "repair", legacy_repair)
        case["searcher"].execute(case["search"].id, case["transport"])
    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    with database.transaction() as connection:
        runs = Runs(connection)
        row = runs.lock(run_id)
        assert row["status"] == "queued"
        feedback = json.loads(row["messages"][-1]["content"])["material_goal_format_repair"]
        assert feedback["issues"][0]["actual_length"] == lengths[-1]
        assert feedback["issues"][0]["max_length"] == MATERIAL_GOAL_SUMMARY_LIMIT
        assert feedback["issues"][0]["target_length"] == MATERIAL_GOAL_SUMMARY_LIMIT // 2
        assert str(lengths[-1]) in feedback["instruction"]
        assert str(MATERIAL_GOAL_SUMMARY_LIMIT // 2) in feedback["instruction"]
        assert runs.admission_snapshot(session.actor.id, run_id) == case["admission"]
        assert PRIVATE_REASONING not in json.dumps(row["messages"])
    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    assert case["searcher"].get(session.token, case["search"].id).status == "ready"
    calls = calls_for(database, run_id)
    assert len(calls) == len(sent) == 3 and all(call["applied"] for call in calls)


def test_ref_correction_omits_superseded_summary_feedback_without_changing_old_receipts(
    database, session, repair_case, monkeypatch
):
    case = repair_case
    run_id = case["part"]["run_id"]
    gateway, sent = correction_gateway(
        case["settings"], summary_lengths=[MATERIAL_GOAL_SUMMARY_LIMIT + 1, 1248, 1248],
        ref_span_steps=(2,),
    )
    AgentLoop(case["tutor"], gateway).run(run_id)
    original_repair = Runs.repair
    old_feedback = {
        "material_goal_format_repair": {
            "issue_codes": [["summary", "string_too_long"]],
            "issues": [{
                "path": "summary", "code": "string_too_long",
                "actual_length": 1546, "max_length": 1200, "target_length": 600,
            }],
            "instruction": "Old summary limit 1200; rewrite to about 600 characters.",
        }
    }

    def legacy_history_repair(self, row, digest, messages, call):
        messages = messages[:-2] + [
            {"role": "user", "content": json.dumps(old_feedback)}, *messages[-2:]
        ]
        return original_repair(self, row, digest, messages, call)

    with monkeypatch.context() as patch:
        patch.setattr(Runs, "repair", legacy_history_repair)
        case["searcher"].execute(case["search"].id, case["transport"])
    AgentLoop(case["tutor"], gateway).run(run_id)
    old_calls = calls_for(database, run_id)
    assert len(old_calls) == len(sent) == 2
    assert any(
        message.get("role") == "user" and message["content"] == json.dumps(old_feedback)
        for message in old_calls[-1]["request"]["messages"]
    )
    case["searcher"].execute(case["search"].id, case["transport"])
    with database.transaction() as connection:
        messages = Runs(connection).lock(run_id)["messages"]
    schema = json.loads(messages[1]["content"])["schema"]
    assert schema["properties"]["summary"]["maxLength"] == 4000
    assert "summary <=4000 characters" in messages[0]["content"]
    feedbacks = [
        json.loads(message["content"])["material_goal_format_repair"]
        for message in messages
        if message.get("role") == "user" and "material_goal_format_repair" in message["content"]
    ]
    assert len(feedbacks) == 2
    assert feedbacks[0]["issues"][0]["max_length"] == 4000
    assert feedbacks[0]["issues"][0]["target_length"] == 2000
    assert feedbacks[1]["issue_codes"] == [["refs", "exact_ref_contract"]]
    assert len(feedbacks[1]["issues"][0]["mismatched_evidence_refs"]) == 1
    assert all(
        "1200" not in feedback["instruction"] and "600" not in feedback["instruction"]
        for feedback in feedbacks
    )
    AgentLoop(case["tutor"], gateway).run(run_id)
    case["searcher"].execute(case["search"].id, case["transport"])
    assert case["searcher"].get(session.token, case["search"].id).status == "ready"
    calls = calls_for(database, run_id)
    assert len(calls) == len(sent) == 3
    for old, current in zip(old_calls, calls[:2], strict=True):
        for field in ("id", "step", "request", "response_body"):
            assert current[field] == old[field]
    assert PRIVATE_REASONING not in json.dumps(sent[-1])


@pytest.mark.parametrize("stop", ["revoked", "cancelled"])
def test_known_goal_format_correction_requires_current_material_permission_and_scope(
    database, session, rag, repair_case, stop
):
    case = repair_case
    run_id = case["part"]["run_id"]
    gateway, sent = correction_gateway(case["settings"])
    AgentLoop(case["tutor"], gateway).run(run_id)
    if stop == "revoked":
        original = case["original"]
        rag["materials"].revoke(
            session.token, original.document_id, original.document_revision,
            DocumentPermissionAction(expected_revision=1, action="revoke"),
        )
    else:
        case["searcher"].cancel(session.token, case["search"].id)
    case["searcher"].execute(case["search"].id, case["transport"])
    calls = calls_for(database, run_id)
    assert len(calls) == len(sent) == 1 and not calls[0]["applied"]
    with database.transaction() as connection:
        row = Runs(connection).lock(run_id)
        assert row["repair_base_messages"] is None
        assert row["status"] != "queued"
