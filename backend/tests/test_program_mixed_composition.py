import json
from uuid import uuid4

import pytest
from test_item_supply import run_model
from test_item_supply import supply_setup as supply_setup
from test_program_compositions import current_program, introduce_program, program_definition
from test_program_compositions import program_composition as program_composition
from test_program_items import answer_for, environment, item_document
from test_program_practice import observed_environments as observed_environments
from test_program_practice import owned_claim, publish, receipt, submission
from test_program_practice import program_setup as program_setup
from test_program_runner import runner as runner

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.compositions import CompositionWorkflow
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.modules.item_bank.supply_contracts import PackRequest
from leornian.modules.tutor.composition_delivery_contracts import CompositionCancelRunAction
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.modules.tutor.program_interaction_contracts import CompositionProgramRunAction
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def mixed_programs(database, session, program_setup, program_composition):
    setup = program_composition
    base = program_setup[2]
    supply, tutor, settings, plan, material = base
    env = environment("python_project")
    accepted = supply.submit(
        session.token, plan.id, str(uuid4()), PackRequest(
            expected_plan_revision=1, node_key="loops", kind="python_project",
            instruction="A separate multi-file project with protected files.",
            program_environment=env, automatic=False,
        ),
    )
    document = item_document(material, env)
    run_model(tutor, settings, accepted.run_id, document)
    pending = supply.get(session.token, accepted.pack_id).pending_run_id
    run_model(tutor, settings, pending, {
        "programs": [
            {"slot": item["slot"], "answer": answer_for(item)} for item in document["items"]
        ],
    })
    publish(database, session, (setup["programs"], accepted, base, document, env))
    with database.transaction() as connection:
        options = LearningArtifactWorkflow.candidates_in(
            connection, session.actor, setup["conversation"].id, setup["focus"], programs=True,
        )["items"]
    project = next(
        item for item in options
        if item["content_ref"]["id"] == str(accepted.pack_id)
        and item["content_ref"]["slot"] == "practice_1"
    )

    def compose(args):
        editor = args["definition"]["components"][0]
        editor["component"] = "CodeDiff"
        editor["props"]["before"] = setup["source"]["presentation"]["task"]["starter_query"]
        additional = program_definition(project)
        args["definition"]["states"]["project_editor"] = additional["states"]["editor"]
        for node in additional["components"]:
            node["id"] = "project_" + node["id"]
            for field in ("state", "for_component"):
                if field in node["props"]:
                    node["props"][field] = "project_" + node["props"][field]
        args["definition"]["components"].extend(additional["components"])
        args["owner_bindings"].append({
            "component_id": "project_editor", "candidate_id": project["id"],
        })

    def before_check():
        assert not setup["flow"].list_v2(session.token, setup["conversation"].id)

    task, delivery, prepared, wires, _, _ = introduce_program(
        session, setup, mutate=compose, conflict=before_check,
    )
    assert task.status == "accepted" and len(wires) == 4
    assert prepared[0]["status"] == "completed"
    listed = json.loads(wires[1]["messages"][-1]["content"])["items"]
    required = {setup["source"]["id"], project["id"]}
    assert required <= {item["id"] for item in listed}
    view = current_program(session, setup)
    assert {str(owner.source.id) for owner in view.component_bindings} == required
    turn = next(
        turn for turn in setup["tutor"].turn_history(session.token, view.conversation_id)
        if turn.id == delivery.turn_id
    )
    assert str(turn.learning_interaction.exact_handle) == prepared[0]["candidate"]["id"]
    with database.transaction() as connection:
        assert Runs(connection).lock(delivery.run_id)["tool_contracts"][
            "prepare_learning_program_composition"
        ] == 1
    setup.update(
        documents={"editor": setup["document"]["items"][0], "project_editor": document["items"][0]},
        wires=wires, commands=[],
    )
    return setup


def owners(view):
    return {owner.component_id: owner for owner in view.component_bindings}


def apply(session, setup, action):
    view = current_program(session, setup)
    result = setup["flow"].action(session.token, view.conversation_id, view.id, action)
    setup["commands"].append((action, result))
    return result


def run_action(session, setup, component, *, parent=None, retry=False, wrong=False):
    data = submission(setup["documents"][component], parent=parent, retry=retry, wrong=wrong)
    return CompositionProgramRunAction(
        action="run_program_component", component_id=component, client_action_id=uuid4(),
        expected_artifact_revision=current_program(session, setup).revision,
        payload=data.model_dump(exclude={"slot"}),
    )


def report(database, session, attempt_id, *, wrong=False):
    claim = owned_claim(database, session, attempt_id)
    assert claim is not None
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, wrong=wrong))


def assert_replay(session, setup):
    view = current_program(session, setup)
    for action, expected in setup["commands"]:
        assert setup["flow"].action(
            session.token, view.conversation_id, view.id, action,
        ) == expected
        assert setup["flow"].action_receipt(
            session.token, view.conversation_id, view.id, action.client_action_id,
        ) == expected


def test_sql_diff_and_project_keep_fixed_sources_and_independent_results_and_attempts(
    database, workflow, session, mixed_programs,
):
    setup = mixed_programs
    initial = current_program(session, setup)
    sql, project = owners(initial).values()
    definition = initial.presentation.definition
    editor = definition.components[0]
    assert editor.component == "CodeDiff"
    assert editor.props.before == sql.source.presentation.task.starter_query
    assert definition.states["editor"].value == editor.props.before
    files = definition.states["project_editor"].files
    assert [file.model_dump() for file in files] == [
        file.model_dump() for file in project.source.presentation.task.files
    ]
    assert len(files) == 3 and sum(file.read_only for file in files) == 2
    altered = definition.model_dump(mode="json")
    altered["components"][0]["props"]["before"] = "SELECT 999 AS answer"
    invalid = LearningCompositionV2.model_validate(altered)
    with pytest.raises(BusinessError, match="fixed public task"):
        CompositionWorkflow.validate_program_node(
            invalid, invalid.components[0], sql.source.presentation.task,
        )
    stale_project = run_action(session, setup, "project_editor")
    first = apply(session, setup, run_action(session, setup, "editor", wrong=True))
    with pytest.raises(BusinessError) as stale:
        apply(session, setup, stale_project)
    assert stale.value.code == "stale_version"
    assert owners(current_program(session, setup))["project_editor"] == project
    project_run = apply(session, setup, run_action(session, setup, "project_editor"))
    report(database, session, first.result_id, wrong=True)
    partial = current_program(session, setup)
    assert partial.state == "running"
    assert owners(partial)["editor"].result.status == "not_passed"
    assert owners(partial)["project_editor"].result.status == "queued"
    report(database, session, project_run.result_id)
    completed = current_program(session, setup)
    assert completed.state == "completed"
    project_result = owners(completed)["project_editor"]
    assert project_result.result.status == "passed"
    second = apply(
        session, setup, run_action(session, setup, "editor", parent=first.result_id),
    )
    assert owners(current_program(session, setup))["project_editor"] == project_result
    report(database, session, second.result_id)
    final = current_program(session, setup)
    assert final.state == "completed" and final.content_ref == initial.content_ref
    assert final.presentation == initial.presentation
    assert owners(final)["editor"].result.status == "passed"
    assert [attempt.id for attempt in owners(final)["editor"].attempts.attempts] == [
        second.result_id, first.result_id,
    ]
    assert owners(final)["project_editor"] == project_result
    protected = run_action(
        session, setup, "project_editor", parent=project_run.result_id,
    ).model_dump(mode="json")
    protected["payload"]["answer"]["files"][0]["content"] = "print(999)"
    with pytest.raises(BusinessError):
        apply(session, setup, CompositionProgramRunAction.model_validate(protected))
    assert current_program(session, setup) == final
    assert setup["programs"].attempt(session.token, first.result_id).status == "not_passed"
    assert_replay(session, setup)
    snapshot = workflow.snapshot(session.token)
    assert {attempt.id for attempt in snapshot.program_attempts} == {
        first.result_id, second.result_id, project_run.result_id,
    }
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert len(setup["wires"]) == 4


def test_one_program_cancel_retry_and_late_receipts_do_not_finish_or_overwrite_the_other(
    database, workflow, session, mixed_programs,
):
    setup = mixed_programs
    first = apply(session, setup, run_action(session, setup, "editor"))
    sql_claim = owned_claim(database, session, first.result_id)
    project = apply(session, setup, run_action(session, setup, "project_editor"))
    project_claim = owned_claim(database, session, project.result_id)
    assert sql_claim is not None and project_claim is not None
    view = current_program(session, setup)
    cancel = CompositionCancelRunAction(
        action="cancel_component_run", component_id="editor", expected_attempt_id=first.result_id,
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
    )
    apply(session, setup, cancel)
    cancelled_one = current_program(session, setup)
    assert cancelled_one.state == "running"
    assert owners(cancelled_one)["editor"].result.status == "error"
    assert owners(cancelled_one)["project_editor"].state == "running"
    assert owners(cancelled_one)["project_editor"].result.status == "queued"
    with pytest.raises(BusinessError, match="explicitly retry"):
        apply(session, setup, run_action(session, setup, "editor", parent=first.result_id))
    second = apply(
        session, setup, run_action(session, setup, "editor", parent=first.result_id, retry=True),
    )
    sql_retry = owned_claim(database, session, second.result_id)
    assert sql_retry is not None
    late_first = receipt(database, sql_claim)
    JourneyWorkflow(database).report(sql_claim.job_id, late_first)
    pending = current_program(session, setup)
    assert pending.state == "running"
    assert owners(pending)["editor"].result.id == second.result_id
    assert owners(pending)["editor"].result.status == "queued"
    assert owners(pending)["project_editor"].result.status == "queued"
    JourneyWorkflow(database).report(
        project_claim.job_id, receipt(database, project_claim),
    )
    project_completed = current_program(session, setup)
    assert project_completed.state == "running"
    project_result = owners(project_completed)["project_editor"].result
    assert project_result.status == "passed"
    apply(session, setup, CancelAction(
        action="cancel", client_action_id=uuid4(),
        expected_artifact_revision=project_completed.revision,
    ))
    final = current_program(session, setup)
    assert final.state == "cancelled" and not final.allowed_actions
    assert owners(final)["project_editor"].result == project_result
    assert owners(final)["editor"].result.status == "error"
    late_second = receipt(database, sql_retry)
    JourneyWorkflow(database).report(sql_retry.job_id, late_second)
    assert current_program(session, setup) == final
    assert [attempt.id for attempt in owners(final)["editor"].attempts.attempts] == [
        second.result_id, first.result_id,
    ]
    assert not any(owner.allowed_actions for owner in final.component_bindings)
    assert_replay(session, setup)
    with database.transaction() as connection:
        for claim, actual in ((sql_claim, late_first), (sql_retry, late_second)):
            row = connection.execute(
                "SELECT status,report FROM execution.jobs WHERE id=%s AND actor_id=%s",
                (claim.job_id, session.actor.id),
            ).fetchone()
            assert row["status"] == "expired"
            assert row["report"]["late_receipt"] == actual.model_dump(mode="json")
    snapshot = workflow.snapshot(session.token)
    assert {attempt.id for attempt in snapshot.program_attempts} == {
        first.result_id, second.result_id, project.result_id,
    }
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert len(setup["wires"]) == 4
