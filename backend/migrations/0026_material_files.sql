CREATE TABLE knowledge.material_uploads (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    demand_id uuid NOT NULL REFERENCES knowledge.material_demands(id),
    demand_revision integer NOT NULL CHECK (demand_revision > 0),
    specification jsonb NOT NULL,
    request_digest text NOT NULL,
    content_digest text NOT NULL,
    byte_size integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 20000000),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','stored','purged')),
    retain_until timestamptz,
    expires_at timestamptz NOT NULL DEFAULT now() + interval '1 day',
    stored_at timestamptz,
    purged_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,demand_id,request_digest)
);
CREATE TABLE knowledge.material_upload_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    upload_id uuid NOT NULL REFERENCES knowledge.material_uploads(id),
    PRIMARY KEY (actor_id,command_key)
);
ALTER TABLE knowledge.material_jobs
    ADD COLUMN upload_id uuid REFERENCES knowledge.material_uploads(id);
ALTER TABLE knowledge.material_jobs DROP CONSTRAINT material_jobs_state_check;
ALTER TABLE knowledge.material_jobs ADD CHECK (
    state IN ('queued','parsing','waiting_dependency','waiting_config','cancelled')
);
ALTER TABLE knowledge.material_jobs DROP CONSTRAINT material_jobs_phase_check;
ALTER TABLE knowledge.material_jobs ADD CHECK (phase IN ('parsing','ocr','checking','indexing'));
ALTER TABLE knowledge.document_versions
    DROP CONSTRAINT document_versions_format_check,
    ADD CHECK (format IN ('text','markdown','html','pdf')),
    ALTER COLUMN original_text DROP NOT NULL,
    ADD COLUMN upload_id uuid REFERENCES knowledge.material_uploads(id),
    ADD COLUMN text_basis text NOT NULL DEFAULT 'source_text'
        CHECK (text_basis IN ('source_text','extracted_text')),
    ADD COLUMN pages jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN processing_state text NOT NULL DEFAULT 'parsed'
        CHECK (processing_state IN ('parsed','partial')),
    ADD COLUMN content_state text NOT NULL DEFAULT 'retained'
        CHECK (content_state IN ('retained','purged')),
    ADD COLUMN purged_at timestamptz;
CREATE UNIQUE INDEX document_original_upload ON knowledge.document_versions(upload_id)
    WHERE upload_id IS NOT NULL;
ALTER TABLE knowledge.document_blocks
    ALTER COLUMN text DROP NOT NULL,
    ADD COLUMN source_page integer CHECK (source_page > 0);

-- Command identity needs the content identity, not a second retained original.
UPDATE knowledge.document_commands c
SET request=(c.request-'text') || jsonb_build_object('text_digest',v.content_digest)
FROM knowledge.document_versions v
WHERE v.document_id=c.document_id AND v.revision=c.document_revision
    AND c.request ? 'text';
CREATE INDEX material_upload_retention ON knowledge.material_uploads(retain_until,id)
    WHERE state<>'purged';
CREATE INDEX material_upload_expiry ON knowledge.material_uploads(expires_at,id)
    WHERE state<>'purged';
