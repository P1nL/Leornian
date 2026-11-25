from datetime import UTC, datetime
from uuid import uuid4

from fsrs import Card, Rating, Scheduler

from leornian.modules.assessment.contracts import OwnedEvidence
from leornian.modules.learning.evidence import project_evidence
from leornian.modules.learning.fsrs_schedule import PARAMETERS, schedule
from leornian.modules.tutor.proactive_contracts import (
    ProactivePreferenceInput,
    within_window,
)


def fact(dimension, outcome, independence="practice"):
    return OwnedEvidence(
        source_receipt=uuid4(), evidence_kind="owned_result", dimension=dimension,
        outcome=outcome, occurred_at=datetime(2026, 11, 7, tzinfo=UTC),
        item_version="pack:1", policy_version="test-owner-policy.v1",
        independence=independence,
    )


def test_projection_separates_dimensions_and_retains_failures_and_assisted_successes():
    facts = [
        fact("concept", "passed", "independent_gate"),
        fact("concept", "not_passed", "independent_gate"),
        fact("execution", "passed", "assisted"),
        fact("execution", "error"),
    ]
    result = project_evidence(facts)
    concept, execution, transfer = result.dimensions
    assert concept.status == "demonstrated" and concept.failed_count == 1
    assert execution.status == "practicing" and execution.assisted_count == 1
    assert execution.independent_pass_count == 0 and execution.error_count == 1
    assert transfer.status == "unobserved" and transfer.evidence_count == 0
    assert result.evidence == facts


def test_fsrs_is_the_pinned_official_algorithm_and_logs_actual_three_rating_values():
    import json

    from leornian.modules.learning.fsrs_schedule import scheduler

    at = datetime(2026, 11, 7, tzinfo=UTC)
    state = None
    for rating, official in [("again", Rating.Again), ("good", Rating.Good), ("easy", Rating.Easy)]:
        previous, state, log, due, config = schedule(state, rating, at, 53)
        reference = Scheduler.from_json(json.dumps(config))
        expected, expected_log = reference.review_card(
            Card.from_json(json.dumps(previous)), official, review_datetime=at,
        )
        assert state == json.loads(expected.to_json())
        assert log == json.loads(expected_log.to_json())
        assert log["rating"] == int(official) and due == expected.due
        assert config["parameters"] == list(PARAMETERS)
        assert config == json.loads(scheduler().to_json())
        at = due


def test_teaching_window_handles_local_time_overnight_and_end_boundary():
    preference = ProactivePreferenceInput(
        expected_revision=0, enabled=True, timezone="Asia/Shanghai",
        start_minute=23 * 60, end_minute=60,
    )
    assert within_window(preference, datetime(2026, 11, 7, 15, tzinfo=UTC))
    assert within_window(preference, datetime(2026, 11, 7, 16, 59, tzinfo=UTC))
    assert not within_window(preference, datetime(2026, 11, 7, 17, tzinfo=UTC))
    assert not within_window(preference, datetime(2026, 11, 7, 14, 59, tzinfo=UTC))
