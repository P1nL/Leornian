CREATE TABLE tutor.review_completions (
    id uuid PRIMARY KEY,
    artifact_id uuid NOT NULL REFERENCES tutor.learning_artifacts(id),
    component_id text NOT NULL,
    presentation_id uuid NOT NULL REFERENCES tutor.learning_presentations(id),
    content_identity text NOT NULL,
    attempt_id uuid NOT NULL,
    evaluation_id uuid NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (artifact_id, component_id)
);
