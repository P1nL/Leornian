ALTER TABLE knowledge.material_chunks
    ADD COLUMN reused_from_chunk_id uuid REFERENCES knowledge.material_chunks(id);

CREATE TABLE knowledge.material_change_checks (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    binding_id uuid NOT NULL,
    binding_revision integer NOT NULL,
    document_id uuid NOT NULL,
    baseline_revision integer NOT NULL,
    candidate_revision integer NOT NULL CHECK (candidate_revision > baseline_revision),
    report jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (binding_id,binding_revision)
        REFERENCES learning.material_binding_revisions(binding_id,revision),
    FOREIGN KEY (document_id,baseline_revision)
        REFERENCES knowledge.document_versions(document_id,revision),
    FOREIGN KEY (document_id,candidate_revision)
        REFERENCES knowledge.document_versions(document_id,revision),
    UNIQUE (actor_id,binding_id,binding_revision,document_id,candidate_revision)
);
CREATE TABLE knowledge.material_change_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    check_id uuid NOT NULL REFERENCES knowledge.material_change_checks(id),
    PRIMARY KEY (actor_id,command_key)
);
