ALTER TABLE item_bank.packs DROP CONSTRAINT packs_kind_check;
ALTER TABLE item_bank.packs ADD CONSTRAINT packs_kind_check
    CHECK (kind IN ('choice','python_io','response'));

CREATE TABLE assessment.response_results (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL CHECK (slot IN ('practice_1','practice_2')),
    idempotency_key text NOT NULL,
    response jsonb NOT NULL,
    correct boolean,
    profile_version text NOT NULL CHECK (profile_version IN (
        'knowledge-multiple.v1','knowledge-prediction.v1','knowledge-order.v1',
        'knowledge-line-location.v1','knowledge-reference.v1'
    )),
    explanation text NOT NULL,
    reference jsonb NOT NULL,
    findings jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_id,idempotency_key),
    UNIQUE(actor_id,pack_id,slot),
    CHECK ((profile_version='knowledge-reference.v1') = (correct IS NULL))
);

ALTER TABLE tutor.learning_candidates DROP CONSTRAINT learning_candidates_kind_check;
ALTER TABLE tutor.learning_candidates DROP CONSTRAINT learning_candidates_content_check;
ALTER TABLE tutor.learning_candidates ADD CONSTRAINT learning_candidates_kind_check
    CHECK (kind IN ('knowledge_check','code_workspace','learning_composition','knowledge_response'));
ALTER TABLE tutor.learning_candidates ADD CONSTRAINT learning_candidates_content_check
    CHECK (
        (kind='learning_composition' AND presentation_id IS NOT NULL
            AND pack_id IS NULL AND slot IS NULL)
        OR (kind IN ('knowledge_check','code_workspace','knowledge_response')
            AND presentation_id IS NULL AND pack_id IS NOT NULL AND slot IS NOT NULL)
    );

ALTER TABLE tutor.learning_component_bindings
    DROP CONSTRAINT learning_component_bindings_check;
ALTER TABLE tutor.learning_component_bindings ADD COLUMN response_result_id uuid
    REFERENCES assessment.response_results(id);
ALTER TABLE tutor.learning_component_bindings ADD CONSTRAINT learning_component_bindings_check
    CHECK (num_nonnulls(choice_result_id,python_attempt_id,response_result_id)<=1);

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CHECK (event_type IN (
    'job.queued','goal.created','job.succeeded','job.failed',
    'tutor.queued','tutor.running','tutor.tool_completed','tutor.succeeded','tutor.failed',
    'tutor.cancelled','tutor.blocked_unknown','tutor.result_available',
    'learning.plan_drafted','learning.plan_confirmed','assessment.queued','assessment.completed',
    'learning.lesson_completed','knowledge.created','knowledge.revised','knowledge.admitted',
    'knowledge.revoked','learning.review_scheduled','learning.review_recorded',
    'learning.review_status_changed','learning.dynamic_plan_drafted',
    'learning.dynamic_plan_confirmed','learning.lesson_document_created','item_bank.updated',
    'assessment.choice_recorded','assessment.remediation_updated','assessment.gate_updated',
    'learning.node_completed','assessment.transfer_updated','tutor.artifact_updated',
    'tutor.learning_artifact_updated','knowledge.material_permission_changed',
    'assessment.response_recorded'
));
