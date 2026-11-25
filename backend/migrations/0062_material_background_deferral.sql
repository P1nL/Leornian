ALTER TABLE knowledge.material_jobs
    ADD COLUMN background_deferred boolean NOT NULL DEFAULT false;

ALTER TABLE knowledge.material_source_resources
    ADD COLUMN read_failures integer NOT NULL DEFAULT 0;
