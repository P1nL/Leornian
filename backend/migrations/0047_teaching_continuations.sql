ALTER TABLE tutor.teaching_sessions
    ADD COLUMN continuation_policy text NOT NULL DEFAULT 'manual'
        CHECK (continuation_policy IN ('manual','after_result.v1')),
    ADD COLUMN continuation_generation integer NOT NULL DEFAULT 1
        CHECK (continuation_generation > 0);

CREATE TABLE tutor.teaching_intents (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    generation integer NOT NULL CHECK (generation > 0),
    focus jsonb NOT NULL,
    artifact_id uuid NOT NULL REFERENCES tutor.learning_artifacts(id),
    content_identity text NOT NULL,
    source_run_id uuid NOT NULL REFERENCES runtime.runs(id),
    trigger_kind text NOT NULL
        CHECK (trigger_kind IN ('artifact_action','expected_result','interaction_event')),
    trigger_ref text NOT NULL,
    priority smallint NOT NULL CHECK (priority IN (10,20,30)),
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','dispatched','cancelled','superseded')),
    wait_reason text,
    run_id uuid UNIQUE REFERENCES runtime.runs(id),
    next_check_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (artifact_id,trigger_kind,trigger_ref),
    CHECK ((state='dispatched') = (run_id IS NOT NULL) OR state IN ('cancelled','superseded'))
);
CREATE INDEX teaching_intent_pending
    ON tutor.teaching_intents(next_check_at,priority,created_at,id) WHERE state='pending';
ALTER TABLE tutor.turns ADD COLUMN teaching_intent_id uuid UNIQUE
    REFERENCES tutor.teaching_intents(id);

CREATE TABLE tutor.teaching_intent_cancellations (
    intent_id uuid NOT NULL REFERENCES tutor.teaching_intents(id),
    client_action_id uuid NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (intent_id,client_action_id)
);
