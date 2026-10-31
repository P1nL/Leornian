ALTER TABLE tutor.turns ADD COLUMN purpose text NOT NULL DEFAULT 'teaching'
    CHECK (purpose IN ('teaching', 'planning'));
ALTER TABLE tutor.turns ADD COLUMN plan_base_revision integer;
ALTER TABLE tutor.turns ADD CONSTRAINT turn_plan_intent CHECK (
    (purpose = 'teaching' AND plan_base_revision IS NULL) OR
    (purpose = 'planning' AND plan_base_revision >= 0 AND plan_base_revision IS NOT NULL)
);

ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CONSTRAINT runs_policy_version_check
    CHECK (policy_version IN ('tutor.v1', 'planner.v1'));

CREATE TABLE learning.plans (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    latest_revision integer NOT NULL DEFAULT 0 CHECK (latest_revision >= 0),
    active_revision integer CHECK (active_revision > 0 AND active_revision <= latest_revision),
    UNIQUE (actor_id, goal_id)
);

CREATE TABLE learning.plan_revisions (
    id uuid PRIMARY KEY,
    plan_id uuid NOT NULL REFERENCES learning.plans(id),
    revision integer NOT NULL CHECK (revision > 0),
    predecessor_revision integer NOT NULL CHECK (predecessor_revision = revision - 1),
    produced_by_run uuid NOT NULL UNIQUE REFERENCES runtime.runs(id),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    sources jsonb NOT NULL CHECK (jsonb_typeof(sources) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plan_id, revision)
);

CREATE TABLE learning.plan_confirmations (
    plan_id uuid NOT NULL,
    revision integer NOT NULL,
    confirmed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (plan_id, revision),
    FOREIGN KEY (plan_id, revision) REFERENCES learning.plan_revisions(plan_id, revision)
);

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (
    event_type IN ('job.queued', 'goal.created', 'job.succeeded', 'job.failed',
        'tutor.queued', 'tutor.running', 'tutor.tool_completed', 'tutor.succeeded',
        'tutor.failed', 'tutor.cancelled', 'tutor.blocked_unknown', 'tutor.result_available',
        'learning.plan_drafted', 'learning.plan_confirmed', 'assessment.queued',
        'assessment.completed', 'learning.lesson_completed',
        'knowledge.created', 'knowledge.revised', 'knowledge.admitted', 'knowledge.revoked',
        'learning.review_scheduled', 'learning.review_recorded', 'learning.review_status_changed',
        'learning.dynamic_plan_drafted', 'learning.dynamic_plan_confirmed')
);
