ALTER TABLE tutor.learning_presentations
    ADD COLUMN demo_bindings jsonb NOT NULL DEFAULT '[]';

CREATE TABLE tutor.demo_observations (
    artifact_id uuid NOT NULL REFERENCES tutor.learning_artifacts(id),
    component_id text NOT NULL,
    generation integer NOT NULL DEFAULT 0 CHECK (generation >= 0),
    nonce uuid,
    state text NOT NULL DEFAULT 'ready'
        CHECK (state IN ('ready', 'started', 'acknowledged', 'completed')),
    inputs jsonb NOT NULL DEFAULT '{}',
    last_step integer CHECK (last_step >= 0),
    sequence integer NOT NULL DEFAULT 0 CHECK (sequence BETWEEN 0 AND 2),
    PRIMARY KEY (artifact_id, component_id)
);

CREATE TABLE tutor.demo_completions (
    id uuid PRIMARY KEY,
    artifact_id uuid NOT NULL REFERENCES tutor.learning_artifacts(id),
    component_id text NOT NULL,
    generation integer NOT NULL CHECK (generation > 0),
    presentation_id uuid NOT NULL REFERENCES tutor.learning_presentations(id),
    content_identity text NOT NULL,
    inputs jsonb NOT NULL,
    event text NOT NULL CHECK (event IN ('timeline_end', 'preview_snapshot')),
    last_step integer,
    completed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (artifact_id, component_id, generation)
);
