ALTER TABLE learning.review_cards
    ALTER COLUMN track_id DROP NOT NULL,
    ADD COLUMN goal_id uuid REFERENCES learning.goals(id),
    ADD COLUMN plan_id uuid,
    ADD COLUMN plan_revision integer,
    ADD COLUMN node_key text,
    ADD COLUMN source_receipt uuid,
    ADD COLUMN prompt text NOT NULL DEFAULT
        '不看课文，回忆如何遍历整数数组、筛选偶数并累加；空数组应输出什么？',
    ADD COLUMN scheduling_state jsonb,
    ADD COLUMN algorithm_version text NOT NULL DEFAULT 'legacy-fixed.v1',
    ADD COLUMN parameter_version text NOT NULL DEFAULT 'legacy-fixed.v1',
    ADD FOREIGN KEY(plan_id,plan_revision) REFERENCES learning.plan_revisions(plan_id,revision),
    ADD UNIQUE(actor_id,plan_id,plan_revision,node_key),
    ADD UNIQUE(actor_id,source_receipt),
    ADD CONSTRAINT review_card_scope CHECK(
        (track_id IS NOT NULL AND plan_id IS NULL AND plan_revision IS NULL
            AND node_key IS NULL AND source_receipt IS NULL)
        OR (track_id IS NULL AND plan_id IS NOT NULL AND plan_revision IS NOT NULL
            AND node_key IS NOT NULL AND source_receipt IS NOT NULL)
    );
UPDATE learning.review_cards c SET goal_id=t.goal_id FROM learning.tracks t WHERE t.id=c.track_id;
ALTER TABLE learning.review_cards ALTER COLUMN goal_id SET NOT NULL;

CREATE TABLE learning.review_logs (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    card_id uuid NOT NULL REFERENCES learning.review_cards(id),
    response_id uuid NOT NULL UNIQUE REFERENCES learning.review_responses(id),
    evidence_kind text NOT NULL CHECK (evidence_kind='self_rating'),
    source_receipt uuid NOT NULL,
    rating text NOT NULL CHECK (rating IN ('again','good','easy')),
    rating_contract text NOT NULL CHECK (rating_contract='self-rating-three.v1'),
    algorithm_version text NOT NULL CHECK (algorithm_version='py-fsrs.6.3.2'),
    parameter_version text NOT NULL CHECK (parameter_version='fsrs6-default-cold-start.v1'),
    scheduler jsonb NOT NULL,
    previous_state jsonb NOT NULL,
    next_state jsonb NOT NULL,
    algorithm_log jsonb NOT NULL,
    reviewed_at timestamptz NOT NULL,
    due_at timestamptz NOT NULL,
    CHECK (source_receipt=response_id)
);
CREATE INDEX review_log_history ON learning.review_logs(actor_id,card_id,reviewed_at,id);

CREATE TABLE learning.review_activities (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    card_id uuid NOT NULL REFERENCES learning.review_cards(id),
    card_revision integer NOT NULL CHECK (card_revision>0),
    due_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'due' CHECK (state IN ('due','presented','completed','cancelled')),
    conversation_id uuid REFERENCES tutor.conversations(id),
    presented_at timestamptz,
    source_receipt uuid REFERENCES learning.review_responses(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(card_id,card_revision),
    CHECK ((state='completed')=(source_receipt IS NOT NULL)),
    CHECK ((conversation_id IS NULL)=(presented_at IS NULL))
);
CREATE INDEX review_activity_owner ON learning.review_activities(actor_id,created_at,id);

CREATE TABLE learning.review_activity_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    activity_id uuid NOT NULL REFERENCES learning.review_activities(id),
    request jsonb NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY(actor_id,command_key)
);

CREATE TABLE tutor.proactive_preferences (
    conversation_id uuid PRIMARY KEY REFERENCES tutor.conversations(id),
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
    enabled boolean NOT NULL DEFAULT false,
    timezone text NOT NULL DEFAULT 'UTC',
    start_minute integer NOT NULL DEFAULT 540 CHECK(start_minute BETWEEN 0 AND 1439),
    end_minute integer NOT NULL DEFAULT 1260 CHECK(end_minute BETWEEN 0 AND 1439),
    session_digest text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tutor.proactive_preference_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    request jsonb NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY(actor_id,command_key)
);

ALTER TABLE tutor.teaching_intents
    ALTER COLUMN artifact_id DROP NOT NULL,
    ALTER COLUMN source_run_id DROP NOT NULL,
    ADD COLUMN review_activity_id uuid UNIQUE REFERENCES learning.review_activities(id),
    ADD COLUMN session_digest text;
ALTER TABLE tutor.teaching_intents DROP CONSTRAINT teaching_intents_trigger_kind_check;
ALTER TABLE tutor.teaching_intents ADD CONSTRAINT teaching_intents_trigger_kind_check
    CHECK(trigger_kind IN ('artifact_action','expected_result','interaction_event','review_due'));
ALTER TABLE tutor.teaching_intents DROP CONSTRAINT teaching_intents_priority_check;
ALTER TABLE tutor.teaching_intents ADD CONSTRAINT teaching_intents_priority_check
    CHECK(priority IN (10,20,30,40));
ALTER TABLE tutor.teaching_intents DROP CONSTRAINT teaching_intents_check;
ALTER TABLE tutor.teaching_intents ADD CONSTRAINT teaching_intents_dispatch CHECK (
    state IN ('pending','cancelled','superseded')
    OR (state='dispatched' AND (run_id IS NOT NULL OR review_activity_id IS NOT NULL))
);
ALTER TABLE tutor.teaching_intents ADD CONSTRAINT teaching_intents_source CHECK (
    (trigger_kind='review_due' AND review_activity_id IS NOT NULL
        AND artifact_id IS NULL AND source_run_id IS NULL AND session_digest IS NOT NULL)
    OR (trigger_kind<>'review_due' AND review_activity_id IS NULL
        AND artifact_id IS NOT NULL AND source_run_id IS NOT NULL)
);
