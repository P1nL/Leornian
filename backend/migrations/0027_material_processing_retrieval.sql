ALTER TABLE knowledge.material_jobs DROP CONSTRAINT material_jobs_state_check;
ALTER TABLE knowledge.material_jobs ADD CHECK (
    state IN ('queued','parsing','processing','waiting_dependency','waiting_config',
              'blocked_unknown','ready','cancelled')
);
ALTER TABLE knowledge.material_jobs DROP CONSTRAINT material_jobs_phase_check;
ALTER TABLE knowledge.material_jobs ADD CHECK (
    phase IN ('parsing','ocr','checking','indexing','validating')
);
DROP INDEX knowledge.document_original_upload;
CREATE INDEX document_original_upload ON knowledge.document_versions(upload_id);

CREATE TABLE knowledge.material_index_builds (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    job_id uuid NOT NULL REFERENCES knowledge.material_jobs(id),
    document_id uuid NOT NULL,
    document_revision integer NOT NULL,
    space jsonb NOT NULL,
    state text NOT NULL DEFAULT 'building' CHECK (state IN ('building','indexed','purged')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (document_id,document_revision)
        REFERENCES knowledge.document_versions(document_id,revision),
    UNIQUE (job_id,document_id,document_revision,space)
);
CREATE TABLE knowledge.material_chunks (
    id uuid PRIMARY KEY,
    build_id uuid NOT NULL REFERENCES knowledge.material_index_builds(id),
    ordinal integer NOT NULL,
    block_id uuid NOT NULL REFERENCES knowledge.document_blocks(id),
    span_start integer NOT NULL,
    span_end integer NOT NULL CHECK (span_end>span_start),
    content_digest text NOT NULL,
    text text,
    lexemes tsvector,
    embedding double precision[],
    UNIQUE (build_id,ordinal)
);
CREATE INDEX material_chunk_lexemes ON knowledge.material_chunks USING gin(lexemes);
CREATE TABLE knowledge.material_operations (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES knowledge.material_jobs(id),
    purpose text NOT NULL CHECK (purpose IN ('ocr','embedding')),
    part text NOT NULL,
    binding jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id,purpose,part,binding)
);
CREATE TABLE knowledge.material_selections (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    demand_id uuid NOT NULL REFERENCES knowledge.material_demands(id),
    purpose text NOT NULL,
    query text,
    facets jsonb NOT NULL,
    mode text NOT NULL CHECK (mode IN ('lexical','hybrid')),
    refs jsonb NOT NULL,
    coverage jsonb NOT NULL,
    scope jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE knowledge.material_searches (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    request_digest text NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued','processing','waiting_config','waiting_dependency',
                   'blocked_unknown','ready','cancelled')
    ),
    selection_id uuid REFERENCES knowledge.material_selections(id),
    error_code text,
    lease_until timestamptz,
    lease_token uuid,
    scope jsonb,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,command_key),
    UNIQUE (actor_id,request_digest)
);
CREATE TABLE knowledge.material_search_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request_digest text NOT NULL,
    search_id uuid NOT NULL REFERENCES knowledge.material_searches(id),
    PRIMARY KEY (actor_id,command_key)
);
CREATE TABLE knowledge.material_search_operations (
    id uuid PRIMARY KEY,
    search_id uuid NOT NULL REFERENCES knowledge.material_searches(id),
    purpose text NOT NULL CHECK (purpose IN ('embedding','rerank')),
    binding jsonb NOT NULL,
    UNIQUE (search_id,purpose)
);
CREATE INDEX material_processing_due ON knowledge.material_jobs(next_run_at,id)
    WHERE state IN ('waiting_config','waiting_dependency','processing','blocked_unknown');
CREATE INDEX material_search_due ON knowledge.material_searches(created_at,id)
    WHERE status NOT IN ('ready','cancelled');
