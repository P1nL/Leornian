CREATE SCHEMA identity;
CREATE SCHEMA learning;
CREATE SCHEMA delivery;

CREATE TABLE identity.learners (
    id uuid PRIMARY KEY,
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 60),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE identity.sessions (
    token_digest text PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);

CREATE TABLE learning.goal_requests (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    title text NOT NULL CHECK (length(title) BETWEEN 3 AND 120),
    motivation text NOT NULL CHECK (length(motivation) <= 1200),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, idempotency_key)
);

CREATE TABLE learning.goals (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL UNIQUE REFERENCES learning.goal_requests(id),
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    title text NOT NULL CHECK (length(title) BETWEEN 3 AND 120),
    motivation text NOT NULL CHECK (length(motivation) <= 1200),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX goals_actor_created ON learning.goals(actor_id, created_at DESC);

CREATE TABLE platform.jobs (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    kind text NOT NULL CHECK (kind = 'learning.create_goal'),
    input_ref uuid NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'succeeded', 'failed')),
    result_ref uuid,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (kind, input_ref),
    CHECK (
        (status = 'queued' AND result_ref IS NULL AND completed_at IS NULL AND error_code IS NULL)
        OR (status = 'succeeded' AND result_ref IS NOT NULL
            AND completed_at IS NOT NULL AND error_code IS NULL)
        OR (status = 'failed' AND result_ref IS NULL
            AND completed_at IS NOT NULL AND error_code IS NOT NULL)
    )
);
CREATE INDEX jobs_actor_created ON platform.jobs(actor_id, created_at DESC);

CREATE TABLE platform.outbox (
    event_id uuid PRIMARY KEY,
    job_id uuid NOT NULL UNIQUE REFERENCES platform.jobs(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    delivery_count integer NOT NULL DEFAULT 0
);

CREATE TABLE platform.inbox (
    consumer text NOT NULL,
    event_id uuid NOT NULL REFERENCES platform.outbox(event_id),
    consumed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer, event_id)
);

CREATE TABLE delivery.streams (
    actor_id uuid PRIMARY KEY REFERENCES identity.learners(id),
    last_sequence bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0)
);

CREATE TABLE delivery.events (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_id uuid NOT NULL UNIQUE,
    event_type text NOT NULL CHECK (
        event_type IN ('job.queued', 'goal.created', 'job.succeeded', 'job.failed')
    ),
    aggregate_id uuid NOT NULL,
    correlation_id uuid NOT NULL,
    causation_id uuid,
    schema_version integer NOT NULL CHECK (schema_version = 1),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL,
    PRIMARY KEY (actor_id, sequence)
);
