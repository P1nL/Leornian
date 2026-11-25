"""Pinned FSRS scheduling; self-ratings never become ability evidence."""

import json
from datetime import UTC, datetime, timedelta

from fsrs import Card, Rating, Scheduler

ALGORITHM_VERSION = "py-fsrs.6.3.2"
PARAMETER_VERSION = "fsrs6-default-cold-start.v1"
RATINGS = {"again": Rating.Again, "good": Rating.Good, "easy": Rating.Easy}
PARAMETERS = (
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194,
    0.001, 1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629,
    1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
)


def scheduler():
    return Scheduler(
        parameters=PARAMETERS, desired_retention=0.9,
        learning_steps=(timedelta(minutes=1), timedelta(minutes=10)),
        relearning_steps=(timedelta(minutes=10),), maximum_interval=36500,
        enable_fuzzing=False,
    )


def initial_state(card_identity, due_at):
    return json.loads(Card(card_id=card_identity, due=due_at.astimezone(UTC)).to_json())


def schedule(state, rating, reviewed_at: datetime, card_identity: int):
    """Cold-start old cards without replaying or inventing historical ratings."""
    reviewed_at = reviewed_at.astimezone(UTC)
    card = Card.from_json(json.dumps(state)) if state else Card(
        card_id=card_identity, due=reviewed_at,
    )
    before = json.loads(card.to_json())
    engine = scheduler()
    card, log = engine.review_card(card, RATINGS[rating], review_datetime=reviewed_at)
    return before, json.loads(card.to_json()), json.loads(log.to_json()), card.due, (
        json.loads(engine.to_json())
    )
