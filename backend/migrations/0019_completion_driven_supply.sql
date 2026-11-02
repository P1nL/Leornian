ALTER TABLE item_bank.packs DROP CONSTRAINT packs_revision_check;
ALTER TABLE item_bank.packs ADD CONSTRAINT packs_revision_check CHECK (revision >= 1);

CREATE TABLE item_bank.supply_tasks (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    root_pack_id uuid NOT NULL UNIQUE REFERENCES item_bank.packs(id),
    head_pack_id uuid NOT NULL UNIQUE REFERENCES item_bank.packs(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','waiting','completed','cancelled')),
    action text NOT NULL DEFAULT 'generate',
    reason text,
    strategy text NOT NULL DEFAULT 'targeted_revision',
    last_failure jsonb,
    transfer_id uuid REFERENCES assessment.transfer_checks(id),
    next_action_at timestamptz NOT NULL DEFAULT now(),
    checked_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz
);
ALTER TABLE item_bank.packs ADD COLUMN supply_task_id uuid REFERENCES item_bank.supply_tasks(id);
CREATE INDEX supply_tasks_pending ON item_bank.supply_tasks(next_action_at,checked_at)
    WHERE status <> 'cancelled';

-- Preserve existing automatic lineages and their authority. Manual history is not enrolled.
WITH RECURSIVE lineage AS (
    SELECT id,id AS root_id,actor_id FROM item_bank.packs
    WHERE automatic AND predecessor_id IS NULL
    UNION ALL
    SELECT p.id,l.root_id,l.actor_id FROM item_bank.packs p
    JOIN lineage l ON p.predecessor_id=l.id WHERE p.automatic
), heads AS (
    SELECT DISTINCT ON (l.root_id) l.root_id,l.actor_id,p.id,p.automation_session_digest,
        p.status,p.automation_error,
        EXISTS(SELECT 1 FROM lineage old JOIN item_bank.packs q ON q.id=old.id
            WHERE old.root_id=l.root_id AND q.status='cancelled') AS cancelled
    FROM lineage l JOIN item_bank.packs p ON p.id=l.id
    ORDER BY l.root_id,p.revision DESC
)
INSERT INTO item_bank.supply_tasks
    (id,actor_id,root_pack_id,head_pack_id,session_digest,status,action,reason,cancelled_at)
SELECT root_id,actor_id,root_id,id,automation_session_digest,
    CASE WHEN cancelled THEN 'cancelled'
         WHEN automation_error IS NOT NULL AND automation_error<>'revision_limit'
             THEN 'waiting' ELSE 'running' END,
    CASE WHEN cancelled THEN 'cancelled' ELSE 'recover' END,
    NULLIF(automation_error,'revision_limit'),
    CASE WHEN cancelled THEN now() ELSE NULL END FROM heads;

WITH RECURSIVE lineage AS (
    SELECT id,id AS root_id FROM item_bank.packs WHERE automatic AND predecessor_id IS NULL
    UNION ALL
    SELECT p.id,l.root_id FROM item_bank.packs p JOIN lineage l ON p.predecessor_id=l.id
    WHERE p.automatic
)
UPDATE item_bank.packs p SET supply_task_id=l.root_id,
    automation_error=CASE WHEN p.automation_error='revision_limit' THEN NULL ELSE p.automation_error END
FROM lineage l WHERE p.id=l.id;

ALTER TABLE runtime.runs ADD COLUMN repair_base_messages jsonb;
ALTER TABLE runtime.external_calls DROP CONSTRAINT external_calls_step_check;
ALTER TABLE runtime.external_calls ADD CONSTRAINT external_calls_step_check CHECK (step >= 1);
