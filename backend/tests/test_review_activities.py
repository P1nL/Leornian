from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import practice, prepare, submit_data
from test_item_supply import supply_setup as supply_setup
from test_reviews import make_due
from test_reviews import review_setup as review_setup

from leornian.bootstrap.learning_evidence import LearningEvidenceWorkflow
from leornian.bootstrap.proactive_teaching import ProactiveTeachingWorkflow
from leornian.bootstrap.reviews import ReviewsWorkflow
from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.learning.review_contracts import PresentReview, ReviewInput
from leornian.modules.learning.reviews import Reviews
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.proactive_contracts import ProactivePreferenceInput
from leornian.modules.tutor.teaching_intent_contracts import CancelTeachingIntent
from leornian.modules.tutor.teaching_session_contracts import (
    OpenTeachingSession,
    PauseTeaching,
    ResumeTeaching,
    SetTeachingMode,
)
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


def scene(database, session, review_setup):
    _, card = review_setup
    make_due(database, card)
    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection)).authenticate(session.token)
        goal_id = connection.execute(
            "SELECT goal_id FROM learning.tracks WHERE id=%s", (card.track_id,),
        ).fetchone()["goal_id"]
        conversation = Tutor(PgTutorStore(connection)).conversation(actor, goal_id)
    controls = TeachingSessionWorkflow(database)
    controls.command(session.token, conversation.id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
    ))
    return (
        card, conversation, controls, ReviewsWorkflow(database),
        ProactiveTeachingWorkflow(database),
    )


def test_activity_present_respond_replay_uses_real_fsrs_log_and_not_ability_score(
    database, session, review_setup, workflow,
):
    card, conversation, _, reviews, _ = scene(database, session, review_setup)
    activities = reviews.list(session.token)
    assert len(activities) == 1
    activity = activities[0]
    assert reviews.list(session.token)[0].id == activity.id
    key = str(uuid4())
    data = PresentReview(expected_card_revision=1, conversation_id=conversation.id)
    presented = reviews.present(session.token, activity.id, key, data)
    assert presented.state == "presented" and presented.conversation_id == conversation.id
    assert reviews.receipt(session.token, activity.id, key) == presented
    response_key = str(uuid4())
    response = ReviewInput(expected_revision=1, rating="good")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reviews.respond(
            session.token, activity.id, response_key, response,
        ), range(2)))
    assert results[0] == results[1] and results[0].state == "completed"
    assert reviews.receipt(session.token, activity.id, response_key) == results[0]
    logs = reviews.logs(session.token, card.id)
    assert len(logs) == 1 and logs[0].source_receipt == results[0].source_receipt
    assert logs[0].algorithm_version == "py-fsrs.6.3.2"
    assert logs[0].algorithm_log["rating"] == 3
    assert logs[0].evidence_kind == "self_rating"
    evidence = LearningEvidenceWorkflow(database).get(session.token)
    assert len(evidence.evidence) == 1
    assert evidence.evidence[0].evidence_kind == "baseline_execution"
    assert all(part.independent_pass_count == 0 for part in evidence.dimensions)
    assert workflow.snapshot(session.token).attempts[0].status == "passed"
    other = workflow.create_session("Other reviewer")
    with pytest.raises(BusinessError, match="not found"):
        reviews.get(other.token, activity.id)


def test_due_fact_uses_existing_intent_queue_and_pause_window_foreground_arbitration(
    database, session, review_setup,
):
    _, conversation, controls, reviews, proactive = scene(database, session, review_setup)
    key = str(uuid4())
    preference = ProactivePreferenceInput(
        expected_revision=0, enabled=True, start_minute=0, end_minute=0,
    )
    saved = proactive.set_preference(session.token, conversation.id, key, preference)
    assert proactive.preference_receipt(session.token, conversation.id, key) == saved
    proactive.scan_due_once()
    continuations = TeachingContinuationWorkflow(database, Settings(database_url=database.url))
    intent = continuations.list(session.token, conversation.id)[0]
    proactive.scan_due_once()
    assert [item.id for item in continuations.list(session.token, conversation.id)] == [intent.id]
    assert intent.trigger_kind == "review_due" and intent.review_activity_id
    current = controls.get(session.token, conversation.id)
    controls.command(session.token, conversation.id, PauseTeaching(
        action="pause", client_action_id=uuid4(), expected_session_revision=current.revision,
    ))
    continuations.reconcile_once()
    assert continuations.list(session.token, conversation.id)[0].wait_reason == "paused"
    current = controls.get(session.token, conversation.id)
    controls.command(session.token, conversation.id, ResumeTeaching(
        action="resume", client_action_id=uuid4(), expected_session_revision=current.revision,
    ))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE tutor.teaching_intents SET next_check_at=now() WHERE id=%s", (intent.id,),
        )
    continuations.reconcile_once()
    delivered = continuations.list(session.token, conversation.id)[0]
    assert delivered.state == "dispatched" and delivered.run_id is None
    activity = reviews.list(session.token, conversation.id)[0]
    assert activity.state == "presented" and activity.id == intent.review_activity_id
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM runtime.runs WHERE actor_id=%s", (session.actor.id,),
        ).fetchone()["n"] == 0
    cancelled = continuations.cancel(
        session.token, conversation.id, intent.id,
        CancelTeachingIntent(client_action_id=uuid4()),
    )
    assert cancelled.state == "cancelled"
    assert reviews.get(session.token, activity.id).state == "cancelled"
    proactive.scan_due_once()
    assert [item.id for item in continuations.list(session.token, conversation.id)] == [intent.id]


def test_mode_change_invalidates_due_intent_and_cancel_does_not_create_another(
    database, session, review_setup,
):
    _, conversation, controls, reviews, proactive = scene(database, session, review_setup)
    proactive.set_preference(session.token, conversation.id, str(uuid4()), ProactivePreferenceInput(
        expected_revision=0, enabled=True, start_minute=0, end_minute=0,
    ))
    proactive.scan_due_once()
    continuations = TeachingContinuationWorkflow(database, Settings(database_url=database.url))
    intent = continuations.list(session.token, conversation.id)[0]
    current = controls.get(session.token, conversation.id)
    controls.command(session.token, conversation.id, SetTeachingMode(
        action="set_mode", mode="free_reading", client_action_id=uuid4(),
        expected_session_revision=current.revision,
    ))
    assert continuations.list(session.token, conversation.id)[0].state == "superseded"
    proactive.scan_due_once()
    assert [item.id for item in continuations.list(session.token, conversation.id)] == [intent.id]
    activity = reviews.get(session.token, intent.review_activity_id)
    result = reviews.cancel(session.token, activity.id, str(uuid4()))
    assert result.state == "cancelled"
    proactive.scan_due_once()
    assert [item.id for item in continuations.list(session.token, conversation.id)] == [intent.id]


def test_due_intent_waits_for_user_foreground_and_time_window(database, session, review_setup):
    _, conversation, controls, _, proactive = scene(database, session, review_setup)
    proactive.set_preference(session.token, conversation.id, str(uuid4()), ProactivePreferenceInput(
        expected_revision=0, enabled=True, start_minute=0, end_minute=0,
    ))
    proactive.scan_due_once()
    settings = Settings(
        database_url=database.url, model_enabled=True,
        model_base_url="https://owned.invalid", model_name="offline-owned",
        model_api_key="offline-review-foreground",
    )
    tutor = TutorWorkflow(database, settings)
    current = controls.get(session.token, conversation.id)
    foreground = tutor.submit(session.token, conversation.id, str(uuid4()), TurnInput(
        text="Let me finish this question first.", teaching_session_revision=current.revision,
    ))
    intents = TeachingContinuationWorkflow(database, settings)
    intents.reconcile_once()
    intent = intents.list(session.token, conversation.id)[0]
    assert intent.state == "pending" and intent.wait_reason == "foreground"
    assert tutor.get(session.token, foreground.run_id).status == "queued"
    tutor.cancel(session.token, foreground.run_id)
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    minute = now.hour * 60 + now.minute
    proactive.set_preference(session.token, conversation.id, str(uuid4()), ProactivePreferenceInput(
        expected_revision=1, enabled=True,
        start_minute=(minute + 60) % 1440, end_minute=(minute + 120) % 1440,
    ))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE tutor.teaching_intents SET next_check_at=now() WHERE id=%s", (intent.id,),
        )
    intents.reconcile_once()
    assert intents.list(session.token, conversation.id)[0].wait_reason == "outside_teaching_window"
    proactive.set_preference(session.token, conversation.id, str(uuid4()), ProactivePreferenceInput(
        expected_revision=2, enabled=False, start_minute=0, end_minute=0,
    ))
    assert intents.list(session.token, conversation.id)[0].state == "cancelled"


def test_dynamic_node_gate_creates_scoped_review_and_retains_owner_evidence(
    database, session, gate_setup,
):
    gates, accepted, (_, _, _, plan, _) = gate_setup
    practice(session, gate_setup)
    gate = prepare(database, session, gate_setup)
    gates.start(session.token, gate.id)
    gates.submit(session.token, gate.id, str(uuid4()), submit_data())
    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection)).authenticate(session.token)
        cards = Reviews(connection).list(actor)
        assert len(cards) == 1
        card = cards[0]
        assert card.track_id is None and card.plan_id == plan.id
        assert card.node_key == "loops" and card.source_receipt == gate.id
        assert "整数数组" not in card.prompt and "Loops" in card.prompt
        assert not Reviews(connection).schedule_node_completed(
            actor, plan.id, 1, "loops", gate.id,
        )
        connection.execute(
            "UPDATE learning.review_cards SET next_due_at=now()-interval '1 second' WHERE id=%s",
            (card.id,),
        )
        conversation = Tutor(PgTutorStore(connection)).conversation(actor, plan.goal_id)
    reviews = ReviewsWorkflow(database)
    activity = reviews.list(session.token)[0]
    presented = reviews.present(session.token, activity.id, str(uuid4()), PresentReview(
        expected_card_revision=1, conversation_id=conversation.id,
    ))
    assert presented.card.plan_id == plan.id
    projection = LearningEvidenceWorkflow(database).get(session.token, plan.id)
    gate_facts = [fact for fact in projection.evidence if fact.source_receipt == gate.id]
    assert len(gate_facts) == 1 and gate_facts[0].outcome == "passed"
    assert gate_facts[0].independence == "independent_gate"
    assert gate_facts[0].pack_id == accepted.pack_id and gate_facts[0].material_versions
    concept, execution, transfer = projection.dimensions
    assert concept.independent_pass_count == 1
    assert execution.evidence_count == transfer.evidence_count == 0


def test_due_intent_yields_to_a_started_real_gate(database, session, review_setup, gate_setup):
    _, conversation, _, _, proactive = scene(database, session, review_setup)
    proactive.set_preference(session.token, conversation.id, str(uuid4()), ProactivePreferenceInput(
        expected_revision=0, enabled=True, start_minute=0, end_minute=0,
    ))
    proactive.scan_due_once()
    practice(session, gate_setup)
    gate = prepare(database, session, gate_setup)
    gates = gate_setup[0]
    gates.start(session.token, gate.id)
    continuations = TeachingContinuationWorkflow(database, Settings(database_url=database.url))
    assert continuations.reconcile_once() == 0
    intent = continuations.list(session.token, conversation.id)[0]
    assert intent.state == "pending" and intent.wait_reason == "active_exam"
    gates.submit(session.token, gate.id, str(uuid4()), submit_data())
    continuations.cancel(
        session.token, conversation.id, intent.id,
        CancelTeachingIntent(client_action_id=uuid4()),
    )


def test_legacy_three_rating_facts_stay_unchanged_and_cold_start_does_not_fabricate_logs(
    database, session, review_setup,
):
    journey, card = review_setup
    old_response = uuid4()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO learning.review_responses(id,actor_id,card_id,idempotency_key,"
            "rating,expected_revision) VALUES(%s,%s,%s,%s,'good',1)",
            (old_response, session.actor.id, card.id, str(uuid4())),
        )
        connection.execute(
            "UPDATE learning.review_cards SET revision=2,last_rating='good',"
            "scheduling_state=NULL,algorithm_version='legacy-fixed.v1',"
            "parameter_version='legacy-fixed.v1',next_due_at=now()-interval '1 second' WHERE id=%s",
            (card.id,),
        )
        old = connection.execute(
            "SELECT * FROM learning.review_responses WHERE id=%s", (old_response,),
        ).fetchone()
    result = journey.review(session.token, card.id, str(uuid4()), ReviewInput(
        expected_revision=2, rating="easy",
    ))
    assert result.algorithm_version == "py-fsrs.6.3.2" and result.last_rating == "easy"
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT * FROM learning.review_responses WHERE id=%s", (old_response,),
        ).fetchone() == old
    logs = ReviewsWorkflow(database).logs(session.token, card.id)
    assert len(logs) == 1 and logs[0].rating == "easy"
    assert logs[0].algorithm_log["rating"] == 4
    assert logs[0].previous_state["last_review"] is None


def test_review_and_proactive_http_contracts_preserve_command_receipts(
    database, session, review_setup, workflow,
):
    _, conversation, _, _, _ = scene(database, session, review_setup)
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": f"Bearer {session.token}"}
    root = f"/v1/conversations/{conversation.id}/proactive-preference"
    initial = client.get(root, headers=headers)
    assert initial.status_code == 200 and initial.json() is None
    key = str(uuid4())
    saved = client.post(root, headers={**headers, "Idempotency-Key": key}, json={
        "expected_revision": 0, "enabled": True, "timezone": "UTC",
        "start_minute": 0, "end_minute": 0,
    })
    assert saved.status_code == 200
    assert client.get(f"{root}/commands/{key}", headers=headers).json() == saved.json()
    activity = client.get("/v1/review-activities", headers=headers).json()[0]
    key = str(uuid4())
    presented = client.post(
        f"/v1/review-activities/{activity['id']}/present",
        headers={**headers, "Idempotency-Key": key},
        json={"expected_card_revision": 1, "conversation_id": str(conversation.id)},
    )
    assert presented.status_code == 200 and presented.json()["kind"] == "memory_review"
    read = client.get(
        f"/v1/review-activities/{activity['id']}/commands/{key}", headers=headers,
    )
    assert read.json() == presented.json()
    other = workflow.create_session("Other HTTP review reader")
    assert client.get(
        f"/v1/review-activities/{activity['id']}/commands/{key}",
        headers={"Authorization": f"Bearer {other.token}"},
    ).status_code == 404
