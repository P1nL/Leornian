ALTER TABLE assessment.program_attempts
    ADD COLUMN sample_case_index smallint CHECK (sample_case_index BETWEEN 0 AND 2),
    ADD COLUMN sample_result jsonb,
    ADD CONSTRAINT program_public_sample_scope CHECK (
        sample_result IS NULL OR (purpose='training' AND sample_case_index IS NOT NULL)
    );
