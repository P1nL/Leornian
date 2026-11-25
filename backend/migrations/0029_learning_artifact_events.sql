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
    'tutor.learning_artifact_updated'
));
