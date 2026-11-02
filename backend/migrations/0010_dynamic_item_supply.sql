ALTER TABLE tutor.turns DROP CONSTRAINT turns_purpose_check;
ALTER TABLE tutor.turns ADD CONSTRAINT turns_purpose_check
    CHECK (purpose IN ('teaching', 'planning', 'lesson', 'item_supply'));
ALTER TABLE tutor.turns DROP CONSTRAINT turn_plan_intent;
ALTER TABLE tutor.turns ADD CONSTRAINT turn_plan_intent CHECK (
    (purpose IN ('teaching', 'item_supply') AND plan_base_revision IS NULL
        AND lesson_request_id IS NULL) OR
    (purpose = 'planning' AND plan_base_revision >= 0 AND plan_base_revision IS NOT NULL
        AND lesson_request_id IS NULL) OR
    (purpose = 'lesson' AND plan_base_revision IS NULL AND lesson_request_id IS NOT NULL)
);
ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CONSTRAINT runs_policy_version_check CHECK (
    policy_version IN ('tutor.v1', 'planner.v1', 'lesson.v1',
        'item_author.v1', 'item_blind.v1', 'item_review.v1')
);

CREATE TABLE item_bank.packs (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    plan_id uuid NOT NULL REFERENCES learning.plans(id),
    plan_revision integer NOT NULL,
    node_key text NOT NULL,
    idempotency_key text NOT NULL,
    instruction text NOT NULL,
    predecessor_id uuid UNIQUE REFERENCES item_bank.packs(id),
    revision integer NOT NULL CHECK (revision BETWEEN 1 AND 3),
    status text NOT NULL CHECK (status IN
        ('authoring', 'blind_solving', 'reviewing', 'changes_required', 'ready',
         'published', 'failed', 'cancelled')),
    document jsonb,
    sources jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    FOREIGN KEY (plan_id, plan_revision) REFERENCES learning.plan_revisions(plan_id, revision),
    UNIQUE (actor_id, idempotency_key)
);

CREATE TABLE item_bank.stages (
    run_id uuid PRIMARY KEY REFERENCES runtime.runs(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    role text NOT NULL CHECK (role IN ('author', 'blind', 'curriculum', 'difficulty',
        'technical', 'ambiguity', 'security', 'adversarial')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (pack_id, role)
);
CREATE TABLE item_bank.exposures (
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL CHECK (slot IN ('practice_1', 'practice_2', 'remediation_1')),
    first_exposed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_id, slot)
);
CREATE TABLE assessment.choice_results (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL,
    selected_key text NOT NULL CHECK (selected_key IN ('A', 'B', 'C', 'D')),
    idempotency_key text NOT NULL,
    correct boolean NOT NULL,
    explanation text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, idempotency_key),
    UNIQUE (pack_id, slot)
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
        'learning.lesson_document_created', 'item_bank.updated', 'assessment.choice_recorded')
);
