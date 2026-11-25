ALTER TABLE tutor.conversations
    ADD COLUMN hidden_from_recents boolean NOT NULL DEFAULT false;

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (event_type IN (
    'job.queued','goal.created','goal.updated','goal.deleted','job.succeeded','job.failed',
    'tutor.queued','tutor.running','tutor.thinking','tutor.tool_completed','tutor.succeeded','tutor.failed',
    'tutor.cancelled','tutor.blocked_unknown','tutor.result_available','tutor.conversation_hidden',
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
