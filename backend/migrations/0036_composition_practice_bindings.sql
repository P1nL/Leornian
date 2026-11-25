ALTER TABLE tutor.learning_presentations
    ADD COLUMN owner_bindings jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE tutor.learning_component_bindings (
    artifact_id uuid NOT NULL REFERENCES tutor.learning_artifacts(id),
    component_id text NOT NULL,
    source_candidate_id uuid NOT NULL UNIQUE REFERENCES tutor.learning_candidates(id),
    state text NOT NULL DEFAULT 'ready'
        CHECK (state IN ('ready','running','completed','cancelled')),
    last_action_id uuid,
    choice_result_id uuid REFERENCES assessment.choice_results(id),
    python_attempt_id uuid REFERENCES assessment.python_attempts(id),
    PRIMARY KEY(artifact_id,component_id),
    CHECK (num_nonnulls(choice_result_id,python_attempt_id)<=1)
);
