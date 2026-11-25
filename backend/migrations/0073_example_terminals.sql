ALTER TABLE execution.jobs ADD COLUMN example_terminal jsonb
    CHECK (example_terminal IS NULL OR example_input IS NOT NULL);
