ALTER TABLE knowledge.material_source_registrations
    DROP CONSTRAINT material_source_registrations_basis_check,
    ADD CHECK (basis IN (
        'explicit_approval','official_catalog','learning_catalog','public_discovery'
    ));
ALTER TABLE knowledge.material_discovery_jobs
    ADD COLUMN acquisition_state jsonb NOT NULL DEFAULT '{}';
ALTER TABLE knowledge.material_goal_coverage_parts
    ADD COLUMN reused_part_id uuid REFERENCES knowledge.material_goal_coverage_parts(id);

CREATE TABLE knowledge.discovered_source_catalog (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    url text NOT NULL,
    metadata jsonb NOT NULL,
    discovery_id uuid NOT NULL REFERENCES knowledge.material_discovery_jobs(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id,url)
);
