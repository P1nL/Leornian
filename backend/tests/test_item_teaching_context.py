import json
from uuid import uuid4

from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import practice
from test_item_supply import document, request_data, run_model
from test_item_supply import supply_setup as supply_setup

from leornian.modules.item_bank.supply_contracts import SLOTS


def test_author_and_review_get_delivered_teaching_but_blind_stays_public_only(
    database, session, gate_setup
):
    _, _, (supply, tutor, settings, plan, source) = gate_setup
    practice(session, gate_setup)
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    value = document(source)
    for item in value["items"]:
        item["prompt"] = "New application: " + item["prompt"]
    authored = []
    run_model(tutor, settings, accepted.run_id, value, observe=authored.append)
    context = json.loads(authored[0]["messages"][1]["content"])
    delivered = context["delivered_learning_context"]
    assert delivered["saved_lessons"]
    assert delivered["confirmed_plan"]["revision"] == 1
    assert len(delivered["actual_exposures"]) == 2
    assert all(entry.get("feedback") for entry in delivered["actual_exposures"])
    assert "Private explanation for assessment" not in json.dumps(delivered)
    pack = supply.get(session.token, accepted.pack_id)
    blind = []
    run_model(
        tutor,
        settings,
        pack.pending_run_id,
        {"answers": [{"slot": slot, "selected_key": "A"} for slot in SLOTS]},
        observe=blind.append,
    )
    public = json.loads(blind[0]["messages"][1]["content"])
    assert "delivered_learning_context" not in public
    assert "correct_key" not in json.dumps(public) and "explanation" not in json.dumps(public)
    pack = supply.get(session.token, accepted.pack_id)
    from leornian.bootstrap.item_supply import ItemSupply
    from leornian.modules.identity.application import Identity
    from leornian.modules.identity.infrastructure import PgIdentityStore
    from leornian.modules.item_bank.supply import Packs

    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection)).authenticate(session.token)
        row = Packs(connection).row(actor, pack.id)
        role = ItemSupply.role(connection, actor, row, {"role": "curriculum"})
        technical = ItemSupply.role(connection, actor, row, {"role": "technical"})
    review = json.loads(role.messages[1]["content"])
    assert review["delivered_learning_context"] == delivered
    assert "blind_answers" not in review and "review_feedback" not in review
    assert role.messages[0] == technical.messages[0]
    assert role.messages[1]["content"].split(',"review_role":')[0] == (
        technical.messages[1]["content"].split(',"review_role":')[0]
    )
    assert review["review_focus"] != json.loads(technical.messages[1]["content"])["review_focus"]
