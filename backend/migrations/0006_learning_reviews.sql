CREATE TABLE learning.review_cards (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    track_id uuid NOT NULL UNIQUE REFERENCES learning.tracks(id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'paused')),
    next_due_at timestamptz NOT NULL DEFAULT now() + interval '1 day',
    last_rating text CHECK (last_rating IN ('again', 'good', 'easy')),
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE learning.review_responses (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    card_id uuid NOT NULL REFERENCES learning.review_cards(id),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    rating text NOT NULL CHECK (rating IN ('again', 'good', 'easy')),
    expected_revision integer NOT NULL CHECK (expected_revision > 0),
    answered_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, idempotency_key)
);

-- These are real completed local lessons, not imported Aearn progress.
INSERT INTO learning.review_cards(id, actor_id, track_id, next_due_at)
SELECT id, actor_id, id, completed_at + interval '1 day'
FROM learning.tracks WHERE status = 'completed';

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (
    event_type IN ('job.queued', 'goal.created', 'job.succeeded', 'job.failed',
        'tutor.queued', 'tutor.running', 'tutor.tool_completed', 'tutor.succeeded',
        'tutor.failed', 'tutor.cancelled', 'tutor.blocked_unknown', 'tutor.result_available',
        'learning.plan_drafted', 'learning.plan_confirmed', 'assessment.queued',
        'assessment.completed', 'learning.lesson_completed',
        'knowledge.created', 'knowledge.revised', 'knowledge.admitted', 'knowledge.revoked',
        'learning.review_scheduled', 'learning.review_recorded', 'learning.review_status_changed')
);
