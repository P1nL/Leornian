CREATE TABLE tutor.learning_presentations (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    conversation_id uuid NOT NULL REFERENCES tutor.conversations(id),
    prepared_run_id uuid NOT NULL REFERENCES runtime.runs(id),
    command_key text NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision = 1),
    definition jsonb NOT NULL,
    context_manifest jsonb NOT NULL,
    public_identity text NOT NULL,
    quality_call_id uuid REFERENCES runtime.external_calls(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    UNIQUE (actor_id,prepared_run_id,command_key)
);

ALTER TABLE tutor.learning_candidates
    ALTER COLUMN pack_id DROP NOT NULL,
    ALTER COLUMN slot DROP NOT NULL,
    ADD COLUMN presentation_id uuid UNIQUE REFERENCES tutor.learning_presentations(id),
    DROP CONSTRAINT learning_candidates_kind_check,
    ADD CONSTRAINT learning_candidates_kind_check
        CHECK (kind IN ('knowledge_check','code_workspace','learning_composition')),
    ADD CONSTRAINT learning_candidates_content_check CHECK (
        (kind='learning_composition' AND presentation_id IS NOT NULL
            AND pack_id IS NULL AND slot IS NULL)
        OR (kind IN ('knowledge_check','code_workspace') AND presentation_id IS NULL
            AND pack_id IS NOT NULL AND slot IS NOT NULL)
    );

ALTER TABLE tutor.learning_artifacts
    DROP CONSTRAINT learning_artifacts_kind_check,
    ADD CONSTRAINT learning_artifacts_kind_check
        CHECK (kind IN ('knowledge_check','code_workspace','learning_composition'));
