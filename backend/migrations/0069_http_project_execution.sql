ALTER TABLE item_bank.packs DROP CONSTRAINT packs_kind_check;
ALTER TABLE item_bank.packs ADD CONSTRAINT packs_kind_check CHECK (
    kind IN ('choice','python_io','response','sql_query','python_project',
             'project_stdio','web_project','http_project')
);
ALTER TABLE item_bank.packs DROP CONSTRAINT program_pack_environment;
ALTER TABLE item_bank.packs ADD CONSTRAINT program_pack_environment CHECK (
    (kind IN ('sql_query','python_project','project_stdio','web_project','http_project'))
    = (program_environment IS NOT NULL)
);
ALTER TABLE assessment.program_attempts
    DROP CONSTRAINT program_attempts_comparison_profile_check;
ALTER TABLE assessment.program_attempts
    ADD CONSTRAINT program_attempts_comparison_profile_check CHECK (
        comparison_profile IN ('sql-result-typed.v1','python-project-io-result.v1',
                              'stdio-text.v1','web-check.v1','http-response.v1')
    );
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_checks_kind_check;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_checks_kind_check CHECK (
    kind IN ('choice','python_io','sql_query','python_project',
             'project_stdio','web_project','http_project')
);
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_origin_kind;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_origin_kind CHECK (
    num_nonnulls(remediation_id,python_remediation_id,program_remediation_id)=1 AND (
        (kind='choice' AND remediation_id IS NOT NULL) OR
        (kind='python_io' AND python_remediation_id IS NOT NULL) OR
        (kind IN ('sql_query','python_project','project_stdio','web_project','http_project')
            AND program_remediation_id IS NOT NULL)
    )
);
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_result_kind;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_result_kind CHECK (
    (kind='choice' AND python_result_id IS NULL AND program_result_id IS NULL) OR
    (kind='python_io' AND result_id IS NULL AND selected_key IS NULL
        AND program_result_id IS NULL) OR
    (kind IN ('sql_query','python_project','project_stdio','web_project','http_project')
        AND result_id IS NULL AND selected_key IS NULL AND python_result_id IS NULL)
);
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_checks_policy_version_check;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_checks_policy_version_check CHECK (
    (kind='choice' AND policy_version IN ('concept-transfer.v1','concept-transfer.v2')) OR
    (kind='python_io' AND policy_version='python-io-transfer.v1') OR
    (kind IN ('sql_query','python_project','project_stdio','web_project','http_project')
        AND policy_version='program-transfer.v1')
);
ALTER TABLE item_bank.supply_demands DROP CONSTRAINT supply_demands_kind_check;
ALTER TABLE item_bank.supply_demands ADD CONSTRAINT supply_demands_kind_check CHECK (
    kind IN ('choice','python_io','sql_query','python_project',
             'project_stdio','web_project','http_project')
);
ALTER TABLE item_bank.supply_demands DROP CONSTRAINT supply_origin_kind;
ALTER TABLE item_bank.supply_demands ADD CONSTRAINT supply_origin_kind CHECK (
    num_nonnulls(remediation_id,python_remediation_id,program_remediation_id)=1 AND (
        (kind='choice' AND remediation_id IS NOT NULL) OR
        (kind='python_io' AND python_remediation_id IS NOT NULL) OR
        (kind IN ('sql_query','python_project','project_stdio','web_project','http_project')
            AND program_remediation_id IS NOT NULL)
    )
);
