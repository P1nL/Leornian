ALTER TABLE tutor.delivery_tasks
    ADD COLUMN last_progress_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN protocol_repair jsonb NOT NULL DEFAULT '{}';

ALTER TABLE tutor.delivery_tasks DROP CONSTRAINT delivery_tasks_status_check;
ALTER TABLE tutor.delivery_tasks ADD CHECK (status IN (
    'generating','checking','repairing','accepted','waiting_input',
    'waiting_dependency','waiting_config','blocked_unknown','blocked_protocol',
    'cancelled','superseded'
));

-- Stop legacy format-repair loops before a new worker can claim them.
-- Provider call records remain unchanged, including unresolved dispatches.
WITH paused AS (
    UPDATE tutor.delivery_tasks t SET status=CASE WHEN EXISTS (
        SELECT 1 FROM runtime.external_calls c WHERE c.run_id=t.run_id
        AND c.status IN ('dispatching','unknown')
    ) THEN 'blocked_unknown' ELSE 'blocked_protocol' END,
        protocol_repair='{"legacy":true}',updated_at=now()
    WHERE status='checking' AND issues->0->>'code'='invalid_delivery_review'
    RETURNING run_id
)
UPDATE runtime.runs r SET
    status=CASE WHEN EXISTS (
        SELECT 1 FROM runtime.external_calls c WHERE c.run_id=r.id
        AND c.status IN ('dispatching','unknown')
    ) THEN 'blocked_unknown' ELSE 'failed' END,
    error_code=CASE WHEN EXISTS (
        SELECT 1 FROM runtime.external_calls c WHERE c.run_id=r.id
        AND c.status IN ('dispatching','unknown')
    ) THEN 'external_result_unknown' ELSE 'delivery_protocol_stalled' END,
    lease_token=NULL,lease_until=NULL,completed_at=now()
FROM paused WHERE r.id=paused.run_id AND r.status IN ('queued','running');
