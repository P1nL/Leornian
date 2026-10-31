CREATE SCHEMA item_bank;
CREATE SCHEMA assessment;
CREATE SCHEMA execution;

CREATE TABLE learning.tracks (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    course_version text NOT NULL CHECK (course_version = 'python-even-sum.v1'),
    revision integer NOT NULL DEFAULT 1 CHECK (revision = 1),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed', 'completed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    confirmed_at timestamptz,
    completed_at timestamptz,
    UNIQUE (actor_id, goal_id, course_version)
);

CREATE TABLE assessment.attempts (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    track_id uuid NOT NULL REFERENCES learning.tracks(id),
    course_revision integer NOT NULL CHECK (course_revision = 1),
    item_version text NOT NULL CHECK (item_version = 'python-even-sum.v1'),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    code text NOT NULL CHECK (octet_length(code) BETWEEN 1 AND 12000),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'passed', 'not_passed', 'error')),
    feedback text,
    passed_cases integer,
    total_cases integer NOT NULL DEFAULT 3 CHECK (total_cases = 3),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (actor_id, idempotency_key)
);

CREATE TABLE execution.jobs (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    input_ref uuid NOT NULL UNIQUE REFERENCES assessment.attempts(id),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'reported', 'expired')),
    claim_token uuid,
    runner_id text,
    lease_until timestamptz,
    report jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    reported_at timestamptz
);

CREATE TABLE learning.assessment_inbox (
    attempt_id uuid PRIMARY KEY REFERENCES assessment.attempts(id),
    track_id uuid NOT NULL REFERENCES learning.tracks(id),
    applied_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (
    event_type IN ('job.queued', 'goal.created', 'job.succeeded', 'job.failed',
        'tutor.queued', 'tutor.running', 'tutor.tool_completed', 'tutor.succeeded',
        'tutor.failed', 'tutor.cancelled', 'tutor.blocked_unknown', 'tutor.result_available',
        'learning.plan_drafted', 'learning.plan_confirmed', 'assessment.queued',
        'assessment.completed', 'learning.lesson_completed')
);
