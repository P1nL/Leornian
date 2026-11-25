ALTER TABLE tutor.conversations ADD COLUMN teaching_revision integer NOT NULL DEFAULT 0;
CREATE TABLE tutor.learning_candidates (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL CHECK (slot IN ('practice_1','practice_2')),
    kind text NOT NULL CHECK (kind IN ('knowledge_check','code_workspace')),
    focus jsonb NOT NULL,
    public_identity text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,conversation_id,pack_id,slot,public_identity)
);
CREATE TABLE tutor.learning_turn_candidates (
    turn_id uuid PRIMARY KEY REFERENCES tutor.turns(id),
    candidate_id uuid NOT NULL REFERENCES tutor.learning_candidates(id),
    expected_teaching_revision integer NOT NULL
);
CREATE TABLE tutor.learning_artifacts (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    source_turn_id uuid NOT NULL UNIQUE REFERENCES tutor.turns(id),
    timeline_item_id uuid NOT NULL UNIQUE,
    candidate_id uuid NOT NULL UNIQUE REFERENCES tutor.learning_candidates(id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision>0),
    kind text NOT NULL CHECK (kind IN ('knowledge_check','code_workspace')),
    state text NOT NULL DEFAULT 'ready' CHECK (
        state IN ('ready','running','completed','cancelled','superseded')
    ),
    choice_result_id uuid REFERENCES assessment.choice_results(id),
    python_attempt_id uuid REFERENCES assessment.python_attempts(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tutor.learning_artifact_actions (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    client_action_id uuid NOT NULL,
    artifact_id uuid NOT NULL REFERENCES tutor.learning_artifacts(id),
    request jsonb NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id,client_action_id)
);
CREATE INDEX learning_artifacts_actor_timeline
    ON tutor.learning_artifacts(actor_id,conversation_id,created_at,id);
