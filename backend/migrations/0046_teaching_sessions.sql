CREATE TABLE tutor.teaching_sessions (
    conversation_id uuid PRIMARY KEY REFERENCES tutor.conversations(id),
    revision integer NOT NULL CHECK (revision > 0),
    generation integer NOT NULL CHECK (generation > 0),
    mode text NOT NULL CHECK (mode IN ('guided', 'free_reading')),
    paused boolean NOT NULL DEFAULT false,
    focus jsonb NOT NULL,
    active_branch_id uuid,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tutor.teaching_branches (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES tutor.teaching_sessions(conversation_id),
    generation integer NOT NULL CHECK (generation > 0),
    anchor_artifact_id uuid NOT NULL REFERENCES tutor.learning_artifacts(id),
    anchor_revision integer NOT NULL CHECK (anchor_revision > 0),
    content_identity text NOT NULL,
    focus jsonb NOT NULL,
    state text NOT NULL CHECK (state IN ('active', 'closed', 'superseded')),
    opened_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz
);
CREATE UNIQUE INDEX teaching_one_active_branch
    ON tutor.teaching_branches(conversation_id) WHERE state = 'active';
ALTER TABLE tutor.teaching_sessions ADD FOREIGN KEY (active_branch_id)
    REFERENCES tutor.teaching_branches(id);
ALTER TABLE tutor.turns ADD COLUMN teaching_branch_id uuid
    REFERENCES tutor.teaching_branches(id);
CREATE INDEX teaching_branch_turns ON tutor.turns(teaching_branch_id, created_at, id)
    WHERE teaching_branch_id IS NOT NULL;

CREATE TABLE tutor.teaching_turn_bindings (
    turn_id uuid PRIMARY KEY REFERENCES tutor.turns(id),
    generation integer NOT NULL CHECK (generation > 0),
    request_payload jsonb NOT NULL
);
CREATE TABLE tutor.teaching_session_commands (
    conversation_id uuid NOT NULL REFERENCES tutor.teaching_sessions(conversation_id),
    client_action_id uuid NOT NULL,
    command jsonb NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (conversation_id, client_action_id)
);

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CHECK (event_type IN (
    'job.queued','goal.created','job.succeeded','job.failed',
    'tutor.queued','tutor.running','tutor.tool_completed','tutor.succeeded','tutor.failed',
    'tutor.cancelled','tutor.blocked_unknown','tutor.result_available',
    'learning.plan_drafted','learning.plan_confirmed','assessment.queued','assessment.completed',
    'learning.lesson_completed','knowledge.created','knowledge.revised','knowledge.admitted',
    'knowledge.revoked','knowledge.material_permission_changed',
    'learning.review_scheduled','learning.review_recorded','learning.review_status_changed',
    'learning.dynamic_plan_drafted','learning.dynamic_plan_confirmed','learning.lesson_document_created',
    'item_bank.updated','assessment.choice_recorded','assessment.response_recorded',
    'assessment.remediation_updated','assessment.gate_updated','learning.node_completed',
    'assessment.transfer_updated','tutor.artifact_updated','tutor.learning_artifact_updated',
    'tutor.teaching_session_updated'
));
