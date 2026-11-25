ALTER TABLE tutor.learning_candidates DROP CONSTRAINT learning_candidates_kind_check;
ALTER TABLE tutor.learning_candidates DROP CONSTRAINT learning_candidates_content_check;
ALTER TABLE tutor.learning_candidates ADD CONSTRAINT learning_candidates_kind_check
    CHECK (kind IN (
        'knowledge_check','code_workspace','learning_composition','knowledge_response',
        'sql_workspace','project_workspace'
    ));
ALTER TABLE tutor.learning_candidates ADD CONSTRAINT learning_candidates_content_check
    CHECK (
        (kind='learning_composition' AND presentation_id IS NOT NULL
            AND pack_id IS NULL AND slot IS NULL)
        OR (kind IN (
            'knowledge_check','code_workspace','knowledge_response',
            'sql_workspace','project_workspace'
        ) AND presentation_id IS NULL AND pack_id IS NOT NULL AND slot IS NOT NULL)
    );

ALTER TABLE tutor.learning_component_bindings ADD COLUMN program_attempt_id uuid
    REFERENCES assessment.program_attempts(id);
ALTER TABLE tutor.learning_component_bindings DROP CONSTRAINT learning_component_bindings_check;
ALTER TABLE tutor.learning_component_bindings ADD CONSTRAINT learning_component_bindings_check
    CHECK (num_nonnulls(
        choice_result_id,python_attempt_id,response_result_id,program_attempt_id
    )<=1);
