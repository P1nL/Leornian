ALTER TABLE tutor.turns ADD COLUMN planning_requested boolean NOT NULL DEFAULT false;
ALTER TABLE tutor.turns ADD COLUMN planning_state jsonb;

CREATE TABLE platform.material_search_configuration (
    actor_id uuid PRIMARY KEY REFERENCES identity.learners(id),
    id uuid NOT NULL UNIQUE,
    revision integer NOT NULL,
    credential_version integer NOT NULL,
    enabled boolean NOT NULL,
    scheme text NOT NULL,
    ciphertext bytea,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE knowledge.material_web_requests (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    discovery_id uuid REFERENCES knowledge.material_discovery_jobs(id),
    observation_id uuid REFERENCES knowledge.source_observations(id),
    request_digest text NOT NULL,
    applied boolean NOT NULL DEFAULT false,
    retired boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((discovery_id IS NULL) <> (observation_id IS NULL))
);
CREATE UNIQUE INDEX material_web_discovery_request ON knowledge.material_web_requests
    (actor_id,discovery_id,request_digest) WHERE NOT retired;
CREATE UNIQUE INDEX material_web_observation_request ON knowledge.material_web_requests
    (actor_id,observation_id,request_digest) WHERE NOT retired;

ALTER TABLE knowledge.material_source_resources
    ADD COLUMN acquisition_provider text NOT NULL DEFAULT 'direct'
    CHECK (acquisition_provider IN ('direct','tavily'));

ALTER TABLE knowledge.material_operations
    ADD COLUMN retired boolean NOT NULL DEFAULT false,
    DROP CONSTRAINT material_operations_job_id_purpose_part_binding_key;
CREATE UNIQUE INDEX material_operation_current ON knowledge.material_operations
    (job_id,purpose,part,binding) WHERE NOT retired;
ALTER TABLE knowledge.material_search_operations
    ADD COLUMN retired boolean NOT NULL DEFAULT false,
    DROP CONSTRAINT material_search_operations_search_id_purpose_key;
CREATE UNIQUE INDEX material_search_operation_current ON knowledge.material_search_operations
    (search_id,purpose) WHERE NOT retired;
