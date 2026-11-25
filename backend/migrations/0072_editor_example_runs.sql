ALTER TABLE execution.jobs ADD COLUMN example_input jsonb;
ALTER TABLE execution.jobs DROP CONSTRAINT one_execution_input;
ALTER TABLE execution.jobs ADD CONSTRAINT one_execution_input
    CHECK (num_nonnulls(input_ref, python_input_ref, program_input_ref, example_input) = 1);
ALTER TABLE execution.jobs DROP CONSTRAINT execution_program_environment;
ALTER TABLE execution.jobs ADD CONSTRAINT execution_program_environment
    CHECK ((program_input_ref IS NOT NULL OR example_input IS NOT NULL)
           = (program_environment IS NOT NULL));
CREATE UNIQUE INDEX execution_example_command ON execution.jobs
    (actor_id, (example_input->>'command_id')) WHERE example_input IS NOT NULL;
