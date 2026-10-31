ALTER TABLE tutor.turns DROP CONSTRAINT turns_purpose_check;
ALTER TABLE tutor.turns ADD CONSTRAINT turns_purpose_check
    CHECK (purpose IN ('teaching', 'planning', 'lesson'));
ALTER TABLE tutor.turns ADD COLUMN lesson_request_id uuid;
ALTER TABLE tutor.turns DROP CONSTRAINT turn_plan_intent;
ALTER TABLE tutor.turns ADD CONSTRAINT turn_plan_intent CHECK (
    (purpose = 'teaching' AND plan_base_revision IS NULL AND lesson_request_id IS NULL) OR
    (purpose = 'planning' AND plan_base_revision >= 0 AND plan_base_revision IS NOT NULL
        AND lesson_request_id IS NULL) OR
    (purpose = 'lesson' AND plan_base_revision IS NULL AND lesson_request_id IS NOT NULL)
);

ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CONSTRAINT runs_policy_version_check
    CHECK (policy_version IN ('tutor.v1', 'planner.v1', 'lesson.v1'));

CREATE TABLE learning.lesson_requests (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    plan_id uuid NOT NULL REFERENCES learning.plans(id),
    plan_revision integer NOT NULL,
    node_key text NOT NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    instruction text NOT NULL CHECK (length(instruction) BETWEEN 1 AND 4000),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES learning.plan_revisions(plan_id, revision),
    UNIQUE (actor_id, idempotency_key)
);

ALTER TABLE tutor.turns ADD CONSTRAINT lesson_intent_reference
    FOREIGN KEY (lesson_request_id) REFERENCES learning.lesson_requests(id);

CREATE TABLE learning.lesson_documents (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL UNIQUE REFERENCES learning.lesson_requests(id),
    produced_by_run uuid NOT NULL UNIQUE REFERENCES runtime.runs(id),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    sources jsonb NOT NULL CHECK (jsonb_typeof(sources) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now()
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
        'learning.dynamic_plan_drafted', 'learning.dynamic_plan_confirmed',
        'learning.lesson_document_created')
);
