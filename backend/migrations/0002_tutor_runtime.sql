CREATE SCHEMA tutor;
CREATE SCHEMA runtime;

CREATE TABLE tutor.conversations (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, goal_id)
);

CREATE TABLE tutor.turns (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    user_text text NOT NULL CHECK (length(user_text) BETWEEN 1 AND 4000),
    assistant_text text CHECK (length(assistant_text) BETWEEN 1 AND 16000),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (conversation_id, idempotency_key)
);

CREATE TABLE runtime.runs (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    scope_id uuid NOT NULL REFERENCES tutor.conversations(id),
    input_ref uuid NOT NULL UNIQUE REFERENCES tutor.turns(id),
    session_digest text NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'tutor.v1'),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'blocked_unknown')),
    cancel_requested boolean NOT NULL DEFAULT false,
    lease_token uuid,
    lease_until timestamptz,
    messages jsonb NOT NULL DEFAULT '[]',
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE UNIQUE INDEX one_active_teaching_turn ON runtime.runs(scope_id)
    WHERE status IN ('queued', 'running', 'blocked_unknown');
CREATE INDEX runs_actor_created ON runtime.runs(actor_id, created_at DESC);

CREATE TABLE runtime.wakeups (
    run_id uuid PRIMARY KEY REFERENCES runtime.runs(id),
    published_at timestamptz,
    delivery_count integer NOT NULL DEFAULT 0
);

CREATE TABLE runtime.external_calls (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runtime.runs(id),
    step integer NOT NULL CHECK (step BETWEEN 1 AND 3),
    status text NOT NULL CHECK (
        status IN ('prepared', 'dispatching', 'result_recorded', 'failed_known', 'unknown', 'not_sent')
    ),
    endpoint text NOT NULL,
    request jsonb NOT NULL,
    response_body text,
    http_status integer,
    provider_request_id text,
    usage jsonb,
    error_code text,
    applied boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    dispatched_at timestamptz,
    recorded_at timestamptz,
    UNIQUE (run_id, step)
);

CREATE TABLE runtime.tool_invocations (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runtime.runs(id),
    external_call_id uuid NOT NULL REFERENCES runtime.external_calls(id),
    provider_tool_id text NOT NULL,
    name text NOT NULL,
    arguments jsonb NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (external_call_id, provider_tool_id)
);

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (
    event_type IN ('job.queued', 'goal.created', 'job.succeeded', 'job.failed',
        'tutor.queued', 'tutor.running', 'tutor.tool_completed', 'tutor.succeeded',
        'tutor.failed', 'tutor.cancelled', 'tutor.blocked_unknown')
);
