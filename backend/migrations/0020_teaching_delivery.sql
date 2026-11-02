-- New requests use durable delivery; historical runs are not adopted or replayed.
ALTER TABLE tutor.turns ADD COLUMN context_focus jsonb NOT NULL DEFAULT '{"kind":"goal"}';
ALTER TABLE tutor.turns DROP CONSTRAINT turns_assistant_text_check;
ALTER TABLE tutor.turns ADD CHECK (assistant_text IS NULL OR length(assistant_text) > 0);
ALTER TABLE runtime.external_calls ADD COLUMN policy_snapshot jsonb NOT NULL DEFAULT '{}';
ALTER TABLE runtime.external_calls ADD COLUMN context_manifest jsonb NOT NULL DEFAULT '{}';
ALTER TABLE runtime.external_calls ADD COLUMN finish_reason text;
ALTER TABLE runtime.runs ADD COLUMN heartbeat_at timestamptz;

CREATE TABLE tutor.delivery_tasks (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    run_id uuid NOT NULL UNIQUE REFERENCES runtime.runs(id),
    kind text NOT NULL CHECK (kind IN ('teaching','planning','lesson')),
    status text NOT NULL DEFAULT 'generating' CHECK (status IN (
        'generating','checking','repairing','accepted','waiting_input',
        'waiting_dependency','waiting_config','blocked_unknown','cancelled','superseded')),
    phase text NOT NULL DEFAULT 'author' CHECK (phase IN ('author','review')),
    focus jsonb NOT NULL,
    author_messages jsonb NOT NULL DEFAULT '[]',
    context_manifest jsonb NOT NULL DEFAULT '{}',
    candidate_call_id uuid REFERENCES runtime.external_calls(id),
    candidate text,
    candidate_input jsonb NOT NULL DEFAULT '[]',
    fragments jsonb NOT NULL DEFAULT '[]',
    revision integer NOT NULL DEFAULT 0,
    issues jsonb NOT NULL DEFAULT '[]',
    repair_strategy text NOT NULL DEFAULT 'diagnostic',
    output_multiplier integer NOT NULL DEFAULT 1 CHECK (output_multiplier > 0),
    cancel_requested boolean NOT NULL DEFAULT false,
    next_action_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tutor.delivery_checks (
    id uuid PRIMARY KEY,
    task_id uuid NOT NULL REFERENCES tutor.delivery_tasks(id),
    candidate_call_id uuid REFERENCES runtime.external_calls(id),
    review_call_id uuid REFERENCES runtime.external_calls(id),
    policy_version text NOT NULL DEFAULT 'delivery_review.v1',
    verdict text NOT NULL,
    issues jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX delivery_tasks_actor_page ON tutor.delivery_tasks(actor_id, created_at DESC, id DESC);
CREATE INDEX delivery_tasks_pending ON tutor.delivery_tasks(status, next_action_at);
