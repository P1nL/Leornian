ALTER TABLE knowledge.document_versions
    DROP CONSTRAINT document_versions_format_check,
    ADD CHECK (format IN ('text','markdown','html','pdf','png','jpeg','docx'));
ALTER TABLE knowledge.material_jobs ADD COLUMN prepared_scope jsonb;
ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CHECK (policy_version IN (
    'tutor.v1','planner.v1','lesson.v1','item_author.v1','item_blind.v1','item_review.v1',
    'gate_relation.v1','transfer_relation.v1','evaluation.v1','artifact.v1','material_check.v1'
));

CREATE TABLE knowledge.material_source_registrations (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    revision integer NOT NULL DEFAULT 1,
    admission text NOT NULL DEFAULT 'allowed' CHECK (admission IN ('allowed','revoked')),
    basis text NOT NULL CHECK (basis IN ('explicit_approval','official_catalog')),
    catalog_id text,
    specification jsonb NOT NULL,
    request_digest text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,goal_id,request_digest)
);
CREATE TABLE knowledge.material_source_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request_digest text NOT NULL,
    source_id uuid NOT NULL REFERENCES knowledge.material_source_registrations(id),
    PRIMARY KEY (actor_id,command_key)
);
ALTER TABLE knowledge.material_uploads ADD COLUMN source_id uuid
    REFERENCES knowledge.material_source_registrations(id);
CREATE TABLE knowledge.material_source_resources (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES knowledge.material_source_registrations(id),
    url text NOT NULL,
    depth integer NOT NULL DEFAULT 0,
    document_id uuid REFERENCES knowledge.documents(id),
    document_revision integer,
    etag text,
    last_modified text,
    raw_digest text,
    teaching_digest text,
    last_observation_id uuid,
    next_check_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id,url)
);
CREATE TABLE knowledge.source_observations (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES knowledge.material_source_registrations(id),
    source_revision integer NOT NULL,
    resource_id uuid NOT NULL REFERENCES knowledge.material_source_resources(id),
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    command_key text NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued','fetching','processing','unchanged','noise_only','changed',
                   'waiting_config','waiting_dependency','blocked_unknown','cancelled')
    ),
    request_identity jsonb NOT NULL,
    response_status integer,
    response_headers jsonb,
    response_url text,
    redirects jsonb,
    raw_digest text,
    raw_byte_size integer,
    original_id uuid,
    teaching_digest text,
    upload_id uuid REFERENCES knowledge.material_uploads(id),
    job_id uuid REFERENCES knowledge.material_jobs(id),
    document_id uuid,
    document_revision integer,
    check_ids jsonb NOT NULL DEFAULT '[]',
    error_code text,
    lease_token uuid,
    lease_until timestamptz,
    dispatched_at timestamptz,
    recorded_at timestamptz,
    published_at timestamptz,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    content_purged boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id,command_key),
    FOREIGN KEY (document_id,document_revision)
        REFERENCES knowledge.document_versions(document_id,revision)
);
CREATE UNIQUE INDEX material_source_active_read ON knowledge.source_observations(resource_id)
    WHERE status IN ('queued','fetching','processing');
CREATE TABLE knowledge.material_source_check_commands (
    source_id uuid NOT NULL REFERENCES knowledge.material_source_registrations(id),
    command_key text NOT NULL,
    request_digest text NOT NULL,
    observation_id uuid NOT NULL REFERENCES knowledge.source_observations(id),
    PRIMARY KEY (source_id,command_key)
);
CREATE INDEX material_source_observation_due ON knowledge.source_observations(next_run_at,id)
    WHERE status IN ('queued','fetching','processing','waiting_config');
CREATE INDEX material_source_resource_due ON knowledge.material_source_resources(next_check_at,id);

CREATE TABLE knowledge.material_discovery_jobs (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    demand_id uuid NOT NULL REFERENCES knowledge.material_demands(id),
    demand_revision integer NOT NULL,
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued','processing','waiting_config','waiting_dependency',
                   'blocked_unknown','ready','cancelled')
    ),
    selection_id uuid REFERENCES knowledge.material_selections(id),
    search_id uuid REFERENCES knowledge.material_searches(id),
    missing_facets jsonb NOT NULL,
    error_code text,
    lease_token uuid,
    lease_until timestamptz,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (demand_id,demand_revision)
);
CREATE INDEX material_discovery_due ON knowledge.material_discovery_jobs(next_run_at,id)
    WHERE status IN ('queued','processing','waiting_config');

CREATE TABLE knowledge.material_repair_attempts (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES knowledge.material_jobs(id),
    input_identity text NOT NULL,
    strategy text NOT NULL,
    state text NOT NULL CHECK (state IN ('prepared','applied','waiting','superseded')),
    issues jsonb NOT NULL,
    result_revision integer,
    replacement_discovery_id uuid REFERENCES knowledge.material_discovery_jobs(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id,input_identity,strategy)
);

CREATE TABLE knowledge.material_parse_parts (
    upload_id uuid NOT NULL REFERENCES knowledge.material_uploads(id),
    ordinal integer NOT NULL,
    page_start integer NOT NULL,
    page_end integer NOT NULL CHECK (page_end>=page_start),
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','parsed','purged')),
    parsed jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (upload_id,ordinal)
);
CREATE TABLE knowledge.material_change_review_parts (
    id uuid PRIMARY KEY,
    review_id uuid NOT NULL REFERENCES knowledge.material_change_reviews(id),
    ordinal integer NOT NULL,
    refs jsonb NOT NULL,
    parent_refs jsonb NOT NULL,
    operation_id uuid UNIQUE,
    result jsonb,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued','result_recorded','reviewed','waiting_dependency',
                   'blocked_unknown','cancelled','purged')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (review_id,ordinal)
);
CREATE TABLE knowledge.material_selection_parts (
    search_id uuid NOT NULL REFERENCES knowledge.material_searches(id),
    ordinal integer NOT NULL,
    refs jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','verified','purged')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (search_id,ordinal)
);

CREATE TABLE knowledge.material_goal_coverage_parts (
    id uuid PRIMARY KEY,
    search_id uuid NOT NULL REFERENCES knowledge.material_searches(id),
    level integer NOT NULL DEFAULT 0,
    ordinal integer NOT NULL,
    refs jsonb NOT NULL,
    child_ids jsonb NOT NULL DEFAULT '[]',
    model_binding jsonb NOT NULL,
    run_id uuid UNIQUE REFERENCES runtime.runs(id),
    state text NOT NULL DEFAULT 'queued' CHECK (
        state IN ('queued','running','reviewed','waiting_config','waiting_dependency',
                  'blocked_unknown','cancelled','purged')
    ),
    result jsonb,
    call_id uuid REFERENCES runtime.external_calls(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (search_id,level,ordinal)
);
