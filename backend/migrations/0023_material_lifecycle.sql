-- New material contracts do not reinterpret legacy SourceRef or valid_until.
CREATE TABLE knowledge.documents (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    latest_revision integer NOT NULL DEFAULT 0 CHECK (latest_revision >= 0),
    next_check_at timestamptz NOT NULL DEFAULT now() + interval '30 days',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE knowledge.document_versions (
    document_id uuid NOT NULL REFERENCES knowledge.documents(id),
    revision integer NOT NULL CHECK (revision > 0),
    title text NOT NULL,
    source_url text NOT NULL,
    format text NOT NULL CHECK (format IN ('text','markdown')),
    original_text text NOT NULL,
    content_digest text NOT NULL,
    parser_version text NOT NULL,
    provenance text NOT NULL CHECK (provenance IN ('learner_supplied','legacy_excerpt')),
    legacy_source_id uuid REFERENCES knowledge.sources(id),
    legacy_source_revision integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, revision),
    UNIQUE (legacy_source_id, legacy_source_revision),
    CHECK ((legacy_source_id IS NULL) = (legacy_source_revision IS NULL)),
    CHECK ((provenance = 'legacy_excerpt') = (legacy_source_id IS NOT NULL))
);
CREATE TABLE knowledge.document_blocks (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL,
    document_revision integer NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    kind text NOT NULL CHECK (kind IN ('heading','paragraph','code','table')),
    section_path jsonb NOT NULL,
    span_start integer NOT NULL CHECK (span_start >= 0),
    span_end integer NOT NULL CHECK (span_end > span_start),
    text text NOT NULL,
    content_digest text NOT NULL,
    FOREIGN KEY (document_id, document_revision)
        REFERENCES knowledge.document_versions(document_id, revision),
    UNIQUE (document_id, document_revision, ordinal)
);
CREATE TABLE knowledge.document_permissions (
    document_id uuid NOT NULL,
    document_revision integer NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    purposes jsonb NOT NULL,
    status text NOT NULL DEFAULT 'allowed' CHECK (status IN ('allowed','revoked')),
    use_until timestamptz,
    retain_until timestamptz,
    basis text NOT NULL CHECK (basis IN ('learner_authorized','legacy_admission')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, document_revision),
    FOREIGN KEY (document_id, document_revision)
        REFERENCES knowledge.document_versions(document_id, revision)
);
CREATE TABLE knowledge.document_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    document_id uuid NOT NULL,
    document_revision integer NOT NULL,
    PRIMARY KEY (actor_id, command_key),
    FOREIGN KEY (document_id, document_revision)
        REFERENCES knowledge.document_versions(document_id, revision)
);
CREATE TABLE learning.material_bindings (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    scope_key text NOT NULL,
    purpose text NOT NULL,
    revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, goal_id, scope_key, purpose)
);
CREATE TABLE learning.material_binding_revisions (
    binding_id uuid NOT NULL REFERENCES learning.material_bindings(id),
    revision integer NOT NULL CHECK (revision > 0),
    plan_id uuid REFERENCES learning.plans(id),
    plan_revision integer,
    node_key text,
    refs jsonb NOT NULL,
    expected_completion_at timestamptz,
    review_due_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (binding_id, revision),
    CHECK ((plan_id IS NULL) = (plan_revision IS NULL)),
    CHECK (node_key IS NULL OR plan_id IS NOT NULL)
);
CREATE TABLE learning.material_binding_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    binding_id uuid NOT NULL,
    binding_revision integer NOT NULL,
    PRIMARY KEY (actor_id, command_key),
    FOREIGN KEY (binding_id, binding_revision)
        REFERENCES learning.material_binding_revisions(binding_id, revision)
);
CREATE INDEX document_actor_goal ON knowledge.documents(actor_id, goal_id, created_at, id);
CREATE INDEX document_blocks_page
    ON knowledge.document_blocks(document_id, document_revision, ordinal);
