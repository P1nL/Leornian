CREATE TABLE platform.model_connections (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    revision integer NOT NULL CHECK (revision > 0),
    label text NOT NULL,
    protocol text NOT NULL CHECK (protocol IN ('chat_completions','dashscope')),
    base_url text NOT NULL,
    region text NOT NULL,
    local_endpoint boolean NOT NULL,
    enabled boolean NOT NULL,
    deleted boolean NOT NULL DEFAULT false,
    credential_version integer NOT NULL CHECK (credential_version > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform.model_credentials (
    connection_id uuid NOT NULL REFERENCES platform.model_connections(id),
    version integer NOT NULL CHECK (version > 0),
    scheme text NOT NULL,
    ciphertext bytea,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    PRIMARY KEY (connection_id, version)
);
CREATE TABLE platform.model_connection_versions (
    connection_id uuid NOT NULL REFERENCES platform.model_connections(id),
    revision integer NOT NULL,
    configuration jsonb NOT NULL,
    PRIMARY KEY (connection_id, revision)
);
CREATE TABLE platform.model_profiles (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    revision integer NOT NULL CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform.model_profile_versions (
    profile_id uuid NOT NULL REFERENCES platform.model_profiles(id),
    revision integer NOT NULL CHECK (revision > 0),
    configuration jsonb NOT NULL,
    PRIMARY KEY (profile_id, revision)
);
CREATE TABLE platform.model_role_mappings (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    role text NOT NULL,
    profile_id uuid NOT NULL REFERENCES platform.model_profiles(id),
    revision integer NOT NULL CHECK (revision > 0),
    PRIMARY KEY (actor_id, role)
);
CREATE TABLE platform.model_configuration_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    result_ref uuid NOT NULL,
    PRIMARY KEY (actor_id, command_key)
);
-- Existing runs are explicitly development-scoped; new product runs are BYOK.
ALTER TABLE runtime.runs ADD COLUMN model_configuration_scope text NOT NULL
    DEFAULT 'legacy_development'
    CHECK (model_configuration_scope IN ('user','legacy_development'));
ALTER TABLE runtime.runs ALTER COLUMN model_configuration_scope SET DEFAULT 'user';

-- Dedicated operations share the original external-call facts and receipt recorder.
ALTER TABLE runtime.external_calls ALTER COLUMN run_id DROP NOT NULL;
ALTER TABLE runtime.external_calls ADD COLUMN operation_ref uuid UNIQUE;
ALTER TABLE runtime.external_calls ADD COLUMN actor_id uuid REFERENCES identity.learners(id);
ALTER TABLE runtime.external_calls ADD CHECK (
    (run_id IS NOT NULL AND operation_ref IS NULL)
    OR (run_id IS NULL AND operation_ref IS NOT NULL AND actor_id IS NOT NULL)
);
CREATE TABLE platform.model_connection_tests (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    connection_id uuid NOT NULL REFERENCES platform.model_connections(id),
    profile_id uuid NOT NULL REFERENCES platform.model_profiles(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','dispatching','succeeded','failed','unknown','cancelled')),
    result jsonb,
    error_code text,
    deadline_at timestamptz,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (actor_id, command_key)
);
