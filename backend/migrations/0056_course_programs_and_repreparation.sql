ALTER TABLE item_bank.packs DROP CONSTRAINT packs_kind_check;
ALTER TABLE item_bank.packs ADD CONSTRAINT packs_kind_check CHECK (
    kind IN ('choice','python_io','response','sql_query','python_project',
             'project_stdio','web_project')
);
ALTER TABLE item_bank.packs DROP CONSTRAINT program_pack_environment;
ALTER TABLE item_bank.packs ADD CONSTRAINT program_pack_environment CHECK (
    (kind IN ('sql_query','python_project','project_stdio','web_project'))
    = (program_environment IS NOT NULL)
);

ALTER TABLE assessment.program_attempts DROP CONSTRAINT program_attempts_purpose_check;
ALTER TABLE assessment.program_attempts ADD CONSTRAINT program_attempts_purpose_check CHECK (
    purpose IN ('qualification','training','gate','transfer')
);
ALTER TABLE assessment.program_attempts
    DROP CONSTRAINT program_attempts_comparison_profile_check;
ALTER TABLE assessment.program_attempts
    ADD CONSTRAINT program_attempts_comparison_profile_check CHECK (
        comparison_profile IN ('sql-result-typed.v1','python-project-io-result.v1',
                              'stdio-text.v1','web-check.v1')
    );
ALTER TABLE assessment.program_attempts
    ADD COLUMN compilation jsonb,
    ADD COLUMN gate_id uuid REFERENCES assessment.concept_gates(id),
    ADD COLUMN transfer_id uuid REFERENCES assessment.transfer_checks(id),
    ADD CONSTRAINT program_gate_binding CHECK (
        (purpose='gate') = (gate_id IS NOT NULL)
    ),
    ADD CONSTRAINT program_transfer_binding CHECK (
        (purpose='transfer') = (transfer_id IS NOT NULL)
    ),
    ADD CONSTRAINT program_gate_slots CHECK (
        purpose!='gate' OR slot IN ('assessment_1','assessment_2')
    );

ALTER TABLE assessment.concept_gates DROP CONSTRAINT concept_gates_policy_version_check;
ALTER TABLE assessment.concept_gates ADD CONSTRAINT concept_gates_policy_version_check CHECK (
    policy_version IN ('concept-gate.v1','python-io-gate.v1','program-execution-gate.v1')
);
ALTER TABLE learning.execution_evidence DROP CONSTRAINT execution_evidence_policy_version_check;
ALTER TABLE learning.execution_evidence ADD CONSTRAINT execution_evidence_policy_version_check CHECK (
    policy_version IN ('python-io-gate.v1','program-execution-gate.v1')
);

ALTER TABLE assessment.transfer_checks
    ADD COLUMN program_remediation_id uuid REFERENCES assessment.program_attempts(id),
    ADD COLUMN program_result_id uuid UNIQUE REFERENCES assessment.program_attempts(id);
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_checks_kind_check;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_checks_kind_check CHECK (
    kind IN ('choice','python_io','sql_query','python_project','project_stdio','web_project')
);
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_origin_kind;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_origin_kind CHECK (
    num_nonnulls(remediation_id,python_remediation_id,program_remediation_id)=1 AND (
        (kind='choice' AND remediation_id IS NOT NULL) OR
        (kind='python_io' AND python_remediation_id IS NOT NULL) OR
        (kind IN ('sql_query','python_project','project_stdio','web_project')
            AND program_remediation_id IS NOT NULL)
    )
);
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_result_kind;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_result_kind CHECK (
    (kind='choice' AND python_result_id IS NULL AND program_result_id IS NULL) OR
    (kind='python_io' AND result_id IS NULL AND selected_key IS NULL
        AND program_result_id IS NULL) OR
    (kind IN ('sql_query','python_project','project_stdio','web_project')
        AND result_id IS NULL AND selected_key IS NULL AND python_result_id IS NULL)
);
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_checks_policy_version_check;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_checks_policy_version_check CHECK (
    (kind='choice' AND policy_version IN ('concept-transfer.v1','concept-transfer.v2')) OR
    (kind='python_io' AND policy_version='python-io-transfer.v1') OR
    (kind IN ('sql_query','python_project','project_stdio','web_project')
        AND policy_version='program-transfer.v1')
);
CREATE UNIQUE INDEX one_current_program_transfer
    ON assessment.transfer_checks(program_remediation_id)
    WHERE status IN ('preparing','ready','opened','submitted','passed','not_passed','error')
        OR opened_at IS NOT NULL;

ALTER TABLE item_bank.supply_demands
    ADD COLUMN program_remediation_id uuid REFERENCES assessment.program_attempts(id),
    ADD CONSTRAINT one_program_supply_per_need UNIQUE(actor_id,program_remediation_id);
ALTER TABLE item_bank.supply_demands DROP CONSTRAINT supply_demands_kind_check;
ALTER TABLE item_bank.supply_demands ADD CONSTRAINT supply_demands_kind_check CHECK (
    kind IN ('choice','python_io','sql_query','python_project','project_stdio','web_project')
);
ALTER TABLE item_bank.supply_demands DROP CONSTRAINT supply_origin_kind;
ALTER TABLE item_bank.supply_demands ADD CONSTRAINT supply_origin_kind CHECK (
    num_nonnulls(remediation_id,python_remediation_id,program_remediation_id)=1 AND (
        (kind='choice' AND remediation_id IS NOT NULL) OR
        (kind='python_io' AND python_remediation_id IS NOT NULL) OR
        (kind IN ('sql_query','python_project','project_stdio','web_project')
            AND program_remediation_id IS NOT NULL)
    )
);

CREATE TABLE learning.material_repreparations (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    decision_id uuid NOT NULL REFERENCES learning.material_update_decisions(id),
    kind text NOT NULL CHECK(kind IN ('plan','lesson')),
    source_id uuid NOT NULL,
    source_revision integer NOT NULL CHECK(source_revision>=1),
    goal_id uuid NOT NULL REFERENCES learning.goals(id),
    plan_id uuid NOT NULL REFERENCES learning.plans(id),
    node_key text,
    session_digest text NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK(state IN (
        'queued','waiting_priority','waiting_confirmation','running','waiting_receipt',
        'ready','superseded','cancelled','waiting_dependency'
    )),
    reason text,
    command_key text NOT NULL UNIQUE,
    request_data jsonb,
    run_id uuid,
    delivery_task_id uuid,
    output_plan_revision integer,
    output_lesson_id uuid REFERENCES learning.lesson_documents(id),
    derived_binding_id uuid REFERENCES learning.material_bindings(id),
    derived_binding_revision integer,
    predecessor_binding_revision integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    next_action_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(decision_id,kind,source_id),
    CHECK((kind='lesson')=(node_key IS NOT NULL)),
    CHECK((run_id IS NULL)=(request_data IS NULL)),
    CHECK((derived_binding_id IS NULL)=(derived_binding_revision IS NULL))
);
CREATE INDEX pending_material_repreparations
    ON learning.material_repreparations(next_action_at,created_at,id)
    WHERE state NOT IN ('ready','superseded','cancelled');
