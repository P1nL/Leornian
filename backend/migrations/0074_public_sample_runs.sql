ALTER TABLE execution.jobs DROP CONSTRAINT execution_program_environment;
ALTER TABLE execution.jobs ADD CONSTRAINT execution_program_environment
    CHECK ((program_input_ref IS NOT NULL OR
            (example_input IS NOT NULL AND example_input #> '{answer,code}' IS NULL))
           = (program_environment IS NOT NULL));
