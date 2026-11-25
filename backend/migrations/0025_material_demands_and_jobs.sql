CREATE TABLE knowledge.material_demands (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    specification jsonb NOT NULL,
    consumer_ref text NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','ready','cancelled')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE knowledge.material_demand_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    demand_id uuid NOT NULL REFERENCES knowledge.material_demands(id),
    PRIMARY KEY (actor_id,command_key)
);
CREATE TABLE knowledge.material_jobs (
    id uuid PRIMARY KEY,
    root_id uuid NOT NULL REFERENCES knowledge.material_jobs(id),
    demand_id uuid NOT NULL REFERENCES knowledge.material_demands(id),
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    demand_revision integer NOT NULL CHECK (demand_revision > 0),
    request_identity jsonb NOT NULL,
    request_digest text NOT NULL,
    input_text text,
    state text NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued','parsing','waiting_dependency','cancelled')),
    phase text NOT NULL DEFAULT 'parsing' CHECK (phase IN ('parsing','checking','indexing')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    issues jsonb NOT NULL DEFAULT '[]',
    reason_code text,
    document_id uuid,
    document_revision integer,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    lease_token uuid,
    lease_until timestamptz,
    published_at timestamptz,
    retain_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (document_id,document_revision)
        REFERENCES knowledge.document_versions(document_id,revision),
    CHECK ((document_id IS NULL) = (document_revision IS NULL)),
    CHECK ((lease_token IS NULL) = (lease_until IS NULL)),
    UNIQUE (actor_id,demand_id,request_digest)
);
CREATE TABLE knowledge.material_job_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    job_id uuid NOT NULL REFERENCES knowledge.material_jobs(id),
    PRIMARY KEY (actor_id,command_key)
);
CREATE TABLE knowledge.material_job_steps (
    job_id uuid NOT NULL REFERENCES knowledge.material_jobs(id),
    revision integer NOT NULL,
    state text NOT NULL,
    phase text NOT NULL,
    reason_code text,
    issues jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id,revision)
);
CREATE INDEX material_demands_actor_goal ON knowledge.material_demands(actor_id,goal_id,created_at,id);
CREATE INDEX material_jobs_due ON knowledge.material_jobs(next_run_at,id)
    WHERE state IN ('queued','parsing');
