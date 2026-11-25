CREATE TABLE knowledge.stage_material_sections (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    plan_id uuid NOT NULL,
    plan_revision integer NOT NULL,
    stage_key text NOT NULL,
    build_id uuid NOT NULL REFERENCES knowledge.material_index_builds(id) ON DELETE CASCADE,
    node_sections jsonb NOT NULL CHECK (jsonb_typeof(node_sections) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id, plan_id, plan_revision, stage_key, build_id),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES learning.plan_revisions(plan_id, revision)
        ON DELETE CASCADE
);
