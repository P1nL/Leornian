ALTER TABLE item_bank.packs DROP CONSTRAINT packs_kind_check;
ALTER TABLE item_bank.packs ADD CONSTRAINT packs_kind_check
    CHECK (kind IN ('choice','python_io','response','sql_query','python_project'));
ALTER TABLE item_bank.packs ADD COLUMN program_environment jsonb;
ALTER TABLE item_bank.packs ADD CONSTRAINT program_pack_environment CHECK (
    (kind IN ('sql_query','python_project')) = (program_environment IS NOT NULL)
);

CREATE TABLE assessment.program_attempts (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL CHECK (slot IN (
        'practice_1','practice_2','assessment_1','assessment_2','remediation_1'
    )),
    purpose text NOT NULL CHECK (purpose IN ('qualification','training')),
    idempotency_key text NOT NULL,
    environment jsonb NOT NULL,
    answer jsonb NOT NULL,
    execution_input jsonb NOT NULL,
    test_cases jsonb NOT NULL,
    comparison_profile text NOT NULL CHECK (comparison_profile IN (
        'sql-result-typed.v1','python-project-io-result.v1'
    )),
    comparison_order text CHECK (comparison_order IN ('ordered','multiset')),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','passed','not_passed','error')),
    passed_cases integer NOT NULL DEFAULT 0 CHECK (passed_cases BETWEEN 0 AND 3),
    feedback text,
    error_code text,
    attempt_number integer NOT NULL CHECK (attempt_number >= 1),
    previous_attempt_id uuid REFERENCES assessment.program_attempts(id),
    retry_requested boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (actor_id,idempotency_key),
    UNIQUE (actor_id,pack_id,slot,purpose,attempt_number),
    CHECK (purpose != 'qualification'
        OR (attempt_number=1 AND previous_attempt_id IS NULL AND NOT retry_requested)),
    CHECK (purpose != 'training' OR slot IN ('practice_1','practice_2','remediation_1')),
    CHECK ((comparison_profile='sql-result-typed.v1') = (comparison_order IS NOT NULL))
);

CREATE TABLE item_bank.program_qualifications (
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL,
    attempt_id uuid NOT NULL UNIQUE REFERENCES assessment.program_attempts(id),
    outcome text CHECK (outcome IN ('passed','not_passed','error')),
    PRIMARY KEY (pack_id,slot)
);

ALTER TABLE execution.jobs ADD COLUMN program_input_ref uuid UNIQUE
    REFERENCES assessment.program_attempts(id);
ALTER TABLE execution.jobs ADD COLUMN program_environment jsonb;
ALTER TABLE execution.jobs DROP CONSTRAINT one_execution_input;
ALTER TABLE execution.jobs ADD CONSTRAINT one_execution_input CHECK (
    num_nonnulls(input_ref,python_input_ref,program_input_ref)=1
);
ALTER TABLE execution.jobs ADD CONSTRAINT execution_program_environment CHECK (
    (program_input_ref IS NOT NULL) = (program_environment IS NOT NULL)
);

ALTER TABLE tutor.evaluations DROP CONSTRAINT evaluations_source_kind_check;
ALTER TABLE tutor.evaluations ADD CONSTRAINT evaluations_source_kind_check
    CHECK (source_kind IN ('choice','transfer','python','program'));
