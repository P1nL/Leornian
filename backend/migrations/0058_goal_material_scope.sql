ALTER TABLE learning.goal_requests ADD COLUMN material_scope jsonb
    CHECK (material_scope IS NULL OR jsonb_typeof(material_scope) = 'object');
ALTER TABLE learning.goals ADD COLUMN material_scope jsonb
    CHECK (material_scope IS NULL OR jsonb_typeof(material_scope) = 'object');
