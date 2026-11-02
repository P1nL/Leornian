-- Append-only partial reviews keep the frozen exposure snapshot intact.
ALTER TABLE assessment.concept_gates ADD COLUMN relation_parts jsonb NOT NULL DEFAULT '[]';
ALTER TABLE assessment.transfer_checks ADD COLUMN relation_parts jsonb NOT NULL DEFAULT '[]';
