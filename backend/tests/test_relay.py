from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

from leornian.platform import relay


def test_relay_cycle_expires_environments_and_continues_reconciliation(monkeypatch, caplog):
    stopped = Mock()
    stopped.is_set.side_effect = [False, True]
    monkeypatch.setattr(relay, "threading", SimpleNamespace(Event=lambda: stopped))
    monkeypatch.setattr(relay, "signal", Mock())
    monkeypatch.setattr(relay, "Database", lambda _: object())

    for name in (
        "relay_once",
        "relay_runs_once",
        "relay_materials_once",
        "relay_model_tests_once",
        "relay_material_searches_once",
        "relay_material_change_reviews_once",
        "relay_material_updates_once",
    ):
        monkeypatch.setattr(relay, name, Mock(return_value=0))
    for module, name in (
        ("material_sources", "scan_material_sources_once"),
        ("material_discovery", "scan_material_discovery_once"),
    ):
        monkeypatch.setattr(
            import_module(f"leornian.bootstrap.{module}"), name, Mock(return_value=[])
        )

    checks = []
    for module, workflow, method in (
        ("model_tests", "ModelTestWorkflow", "expire_unknowns"),
        ("material_intake", "MaterialIntakeWorkflow", "expire_retained_inputs"),
        ("journey", "JourneyWorkflow", "expire_executions"),
        ("execution_environments", "ExecutionEnvironmentWorkflow", "expire"),
        ("automatic_supply", "AutomaticSupply", "reconcile_once"),
        ("tutor", "TutorWorkflow", "reconcile_deliveries"),
        ("material_repreparations", "MaterialRepreparationWorkflow", "reconcile_once"),
        ("proactive_teaching", "ProactiveTeachingWorkflow", "scan_due_once"),
        ("teaching_continuations", "TeachingContinuationWorkflow", "reconcile_once"),
    ):
        check = Mock(return_value=0)
        service = getattr(import_module(f"leornian.bootstrap.{module}"), workflow)
        monkeypatch.setattr(service, method, check)
        checks.append(check)

    relay.main()

    for check in checks:
        check.assert_called_once_with()
    assert not [record for record in caplog.records if record.levelname == "ERROR"]
