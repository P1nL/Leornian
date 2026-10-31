CREATE SCHEMA knowledge;

CREATE TABLE knowledge.sources (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    current_revision integer NOT NULL DEFAULT 1 CHECK (current_revision > 0),
    admission text NOT NULL DEFAULT 'pending' CHECK (admission IN ('pending', 'admitted', 'revoked')),
    valid_until timestamptz,
    admitted_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, idempotency_key)
);

CREATE TABLE knowledge.source_versions (
    source_id uuid NOT NULL REFERENCES knowledge.sources(id),
    revision integer NOT NULL CHECK (revision > 0),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
    source_url text NOT NULL CHECK (length(source_url) BETWEEN 1 AND 2048),
    excerpt text NOT NULL CHECK (octet_length(excerpt) BETWEEN 1 AND 8000),
    origin text NOT NULL DEFAULT 'learner_supplied' CHECK (origin = 'learner_supplied'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, revision)
);

ALTER TABLE runtime.runs ADD COLUMN context_refs jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (
    event_type IN ('job.queued', 'goal.created', 'job.succeeded', 'job.failed',
        'tutor.queued', 'tutor.running', 'tutor.tool_completed', 'tutor.succeeded',
        'tutor.failed', 'tutor.cancelled', 'tutor.blocked_unknown', 'tutor.result_available',
        'learning.plan_drafted', 'learning.plan_confirmed', 'assessment.queued',
        'assessment.completed', 'learning.lesson_completed',
        'knowledge.created', 'knowledge.revised', 'knowledge.admitted', 'knowledge.revoked')
);
