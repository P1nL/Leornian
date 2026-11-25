from types import SimpleNamespace
from uuid import uuid4

from leornian.bootstrap.tutor_activity import TutorActivity


def test_tool_step_details_exclude_private_preparations_and_locked_hints(monkeypatch):
    published = []
    monkeypatch.setattr(
        TutorActivity, "publish",
        lambda _connection, _row, step: published.append(step),
    )
    tool = SimpleNamespace(
        name="prepare_learning_hint_composition",
        arguments={
            "definition": {"text": "private-prepared-content"},
            "hint_bindings": [{"hint": "private-locked-hint"}],
        },
    )
    result = {
        "status": "completed",
        "candidate": {"definition": {"text": "private-prepared-content"}},
        "hint_bindings": [{"hint": "private-locked-hint"}],
    }
    activity_id = uuid4()
    TutorActivity.tool(None, {"policy_version": "tutor.v1"}, activity_id, tool, result, 125)
    step = published[0]
    assert step.id == activity_id and step.duration_ms == 125
    assert step.tool_name == tool.name and step.status == "completed"
    assert "private-prepared-content" not in step.model_dump_json()
    assert "private-locked-hint" not in step.model_dump_json()
    TutorActivity.tool(None, {"policy_version": "item_author.v1"}, uuid4(), tool, result, 5)
    assert len(published) == 1
