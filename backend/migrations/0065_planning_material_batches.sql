ALTER TABLE tutor.turns
    ADD COLUMN material_demand_id uuid,
    ADD COLUMN stage_replies jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE knowledge.material_source_resources
    ADD COLUMN link_label text NOT NULL DEFAULT '',
    ADD COLUMN link_order integer NOT NULL DEFAULT 0;

CREATE INDEX tutor_turn_material_demand ON tutor.turns(material_demand_id)
    WHERE material_demand_id IS NOT NULL;

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (event_type IN (
    'job.queued','goal.created','goal.updated','goal.deleted','job.succeeded','job.failed',
    'tutor.queued','tutor.running','tutor.thinking','tutor.stage_reply','tutor.tool_completed',
    'tutor.succeeded','tutor.failed','tutor.cancelled','tutor.blocked_unknown',
    'tutor.result_available','tutor.conversation_hidden',
    'learning.plan_drafted','learning.plan_confirmed','assessment.queued','assessment.completed',
    'learning.lesson_completed','knowledge.created','knowledge.revised','knowledge.admitted',
    'knowledge.revoked','knowledge.material_permission_changed',
    'learning.review_scheduled','learning.review_recorded','learning.review_status_changed',
    'learning.dynamic_plan_drafted','learning.dynamic_plan_confirmed','learning.lesson_document_created',
    'item_bank.updated','assessment.choice_recorded','assessment.response_recorded',
    'assessment.remediation_updated','assessment.gate_updated','learning.node_completed',
    'assessment.transfer_updated','tutor.artifact_updated','tutor.learning_artifact_updated',
    'tutor.teaching_session_updated','tutor.teaching_intent_updated',
    'knowledge.material_update_offered','learning.material_update_decided','delivery.notification_updated'
));
