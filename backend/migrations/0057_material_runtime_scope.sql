ALTER TABLE runtime.runs
    DROP CONSTRAINT runs_scope_id_fkey,
    DROP CONSTRAINT runs_input_ref_fkey;

ALTER TABLE runtime.runs
    ADD COLUMN tutor_scope_id uuid GENERATED ALWAYS AS (
        CASE WHEN policy_version <> 'material_check.v1' THEN scope_id END
    ) STORED REFERENCES tutor.conversations(id),
    ADD COLUMN tutor_input_ref uuid GENERATED ALWAYS AS (
        CASE WHEN policy_version <> 'material_check.v1' THEN input_ref END
    ) STORED REFERENCES tutor.turns(id),
    ADD COLUMN material_search_id uuid GENERATED ALWAYS AS (
        CASE WHEN policy_version = 'material_check.v1' THEN scope_id END
    ) STORED REFERENCES knowledge.material_searches(id),
    ADD COLUMN material_part_id uuid GENERATED ALWAYS AS (
        CASE WHEN policy_version = 'material_check.v1' THEN input_ref END
    ) STORED REFERENCES knowledge.material_goal_coverage_parts(id);
