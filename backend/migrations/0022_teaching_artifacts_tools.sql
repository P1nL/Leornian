-- Freeze permissions for historical runs; deployment does not upgrade old requests.
ALTER TABLE runtime.runs ADD COLUMN tool_contracts jsonb NOT NULL
    DEFAULT '{"learning_get_context":1}';
ALTER TABLE runtime.tool_invocations ADD COLUMN contract_version integer NOT NULL DEFAULT 1;
ALTER TABLE runtime.tool_invocations ADD COLUMN outcome text NOT NULL DEFAULT 'completed';
ALTER TABLE runtime.tool_invocations ADD COLUMN duration_ms integer NOT NULL DEFAULT 0;

ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CHECK (policy_version IN (
    'tutor.v1','planner.v1','lesson.v1','item_author.v1','item_blind.v1','item_review.v1',
    'gate_relation.v1','transfer_relation.v1','evaluation.v1','artifact.v1'));
ALTER TABLE tutor.delivery_tasks DROP CONSTRAINT delivery_tasks_kind_check;
ALTER TABLE tutor.delivery_tasks ADD CHECK (kind IN ('teaching','planning','lesson','artifact'));

CREATE TABLE tutor.artifacts (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    focus jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tutor.artifact_requests (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    artifact_id uuid NOT NULL REFERENCES tutor.artifacts(id),
    intent_scope text NOT NULL,
    command_key text NOT NULL,
    instruction text NOT NULL,
    session_digest text NOT NULL,
    expected_revision integer NOT NULL CHECK (expected_revision >= 0),
    parent_run_id uuid REFERENCES runtime.runs(id),
    run_id uuid UNIQUE REFERENCES runtime.runs(id),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','accepted','cancelled','superseded','waiting_config')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, intent_scope, command_key)
);
CREATE TABLE tutor.artifact_versions (
    artifact_id uuid NOT NULL REFERENCES tutor.artifacts(id),
    revision integer NOT NULL CHECK (revision > 0),
    request_id uuid NOT NULL UNIQUE REFERENCES tutor.artifact_requests(id),
    document jsonb NOT NULL,
    sources jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_id, revision)
);
CREATE INDEX artifacts_scope ON tutor.artifacts(actor_id, goal_id, created_at DESC, id DESC);
CREATE INDEX artifact_requests_pending ON tutor.artifact_requests(status, created_at);

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CHECK (event_type IN (
    'job.queued','goal.created','job.succeeded','job.failed',
    'tutor.queued','tutor.running','tutor.tool_completed','tutor.succeeded','tutor.failed',
    'tutor.cancelled','tutor.blocked_unknown','tutor.result_available',
    'learning.plan_drafted','learning.plan_confirmed','assessment.queued','assessment.completed',
    'learning.lesson_completed','knowledge.created','knowledge.revised','knowledge.admitted',
    'knowledge.revoked','learning.review_scheduled','learning.review_recorded',
    'learning.review_status_changed','learning.dynamic_plan_drafted',
    'learning.dynamic_plan_confirmed','learning.lesson_document_created','item_bank.updated',
    'assessment.choice_recorded','assessment.remediation_updated','assessment.gate_updated',
    'learning.node_completed','assessment.transfer_updated','tutor.artifact_updated'
));
