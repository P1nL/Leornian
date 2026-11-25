CREATE TABLE execution.environment_demands (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    local_scope text NOT NULL CHECK (local_scope = 'this-device.v1'),
    plan_id uuid,
    plan_revision integer,
    profile text NOT NULL,
    language text NOT NULL,
    dialect text NOT NULL DEFAULT '',
    requirement_revision integer NOT NULL DEFAULT 1 CHECK (requirement_revision > 0),
    requirement jsonb NOT NULL,
    decision_revision integer NOT NULL DEFAULT 0 CHECK (decision_revision >= 0),
    decision text CHECK (decision IN ('allow','defer','decline','revoke')),
    status text NOT NULL DEFAULT 'waiting_authorization' CHECK (status IN (
        'waiting_authorization','waiting_engine','queued','preparing','verifying','ready',
        'deferred','declined','revoked','failed','blocked_unknown'
    )),
    release_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((plan_id IS NULL) = (plan_revision IS NULL)),
    CHECK (plan_revision IS NULL OR plan_revision > 0)
);
CREATE UNIQUE INDEX environment_demands_scope ON execution.environment_demands
    (actor_id,local_scope,COALESCE(plan_id,'00000000-0000-0000-0000-000000000000'::uuid),
     profile,language,dialect);

CREATE TABLE execution.environment_install_decisions (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    demand_id uuid NOT NULL REFERENCES execution.environment_demands(id),
    requirement_revision integer NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    decision text NOT NULL CHECK (decision IN ('allow','defer','decline','revoke')),
    command_key text NOT NULL,
    command jsonb NOT NULL,
    requirement jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,command_key),
    UNIQUE (demand_id,revision)
);

CREATE TABLE execution.environment_preparation_jobs (
    id uuid PRIMARY KEY,
    demand_id uuid NOT NULL REFERENCES execution.environment_demands(id),
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    requirement_revision integer NOT NULL,
    decision_revision integer NOT NULL,
    requirement jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued','waiting_engine','preparing','verifying','ready','failed','cancelled',
        'blocked_unknown'
    )),
    phase text NOT NULL DEFAULT 'queued',
    runner_id text,
    claim_token uuid,
    lease_until timestamptz,
    error_code text,
    report jsonb,
    late_report jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    reported_at timestamptz
);
CREATE INDEX environment_preparations_due ON execution.environment_preparation_jobs(created_at,id)
    WHERE status IN ('queued','waiting_engine','preparing','verifying');

CREATE TABLE execution.environment_releases (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    demand_id uuid NOT NULL REFERENCES execution.environment_demands(id),
    preparation_id uuid NOT NULL UNIQUE REFERENCES execution.environment_preparation_jobs(id),
    requirement_revision integer NOT NULL,
    recipe_id text NOT NULL,
    recipe_revision integer NOT NULL,
    profile text NOT NULL,
    language text NOT NULL,
    dialect text NOT NULL DEFAULT '',
    runtime_version text NOT NULL,
    image_id text NOT NULL,
    image_ids jsonb NOT NULL,
    toolchains jsonb NOT NULL,
    verification jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE execution.environment_demands ADD FOREIGN KEY (release_id)
    REFERENCES execution.environment_releases(id);

CREATE TABLE execution.environment_engine_observations (
    local_scope text PRIMARY KEY CHECK (local_scope = 'this-device.v1'),
    runner_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('ready','missing','stopped','unsupported')),
    version text,
    operating_system text,
    detail text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE execution.environment_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    operation text NOT NULL CHECK (operation IN ('request','rebuild')),
    demand_id uuid NOT NULL REFERENCES execution.environment_demands(id),
    command jsonb NOT NULL,
    receipt jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id,command_key)
);
