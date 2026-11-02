CREATE TABLE assessment.transfer_checks (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    remediation_id uuid NOT NULL REFERENCES assessment.remediations(id),
    source_pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    plan_id uuid NOT NULL,
    plan_revision integer NOT NULL,
    node_key text NOT NULL,
    idempotency_key text NOT NULL,
    policy_version text NOT NULL DEFAULT 'concept-transfer.v1'
        CHECK (policy_version='concept-transfer.v1'),
    relation_run_id uuid UNIQUE REFERENCES runtime.runs(id),
    exposure_revision bigint NOT NULL,
    context_data jsonb NOT NULL,
    comparisons jsonb NOT NULL,
    relation_report jsonb,
    candidate_pack_id uuid REFERENCES item_bank.packs(id),
    candidate_slot text CHECK (candidate_slot IN ('practice_1','practice_2')),
    status text NOT NULL DEFAULT 'preparing' CHECK (
        status IN ('preparing','ready','opened','passed','not_passed','blocked','cancelled')),
    opened_exposure_revision bigint,
    result_id uuid REFERENCES assessment.choice_results(id),
    submit_key text,
    selected_key text CHECK (selected_key IN ('A','B','C','D')),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    opened_at timestamptz,
    completed_at timestamptz,
    UNIQUE (actor_id,idempotency_key),
    CHECK ((candidate_pack_id IS NULL) = (candidate_slot IS NULL)),
    FOREIGN KEY (plan_id,plan_revision) REFERENCES learning.plan_revisions(plan_id,revision)
);
CREATE UNIQUE INDEX one_current_transfer_per_remediation ON assessment.transfer_checks(remediation_id)
    WHERE status IN ('preparing','ready','opened','passed','not_passed') OR opened_at IS NOT NULL;
CREATE TABLE assessment.transfer_candidates (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL CHECK (slot IN ('practice_1','practice_2')),
    transfer_id uuid NOT NULL REFERENCES assessment.transfer_checks(id),
    PRIMARY KEY (actor_id,pack_id,slot)
);
ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CONSTRAINT runs_policy_version_check CHECK (
    policy_version IN ('tutor.v1','planner.v1','lesson.v1','item_author.v1',
        'item_blind.v1','item_review.v1','gate_relation.v1','transfer_relation.v1')
);
ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (
    event_type IN ('job.queued','goal.created','job.succeeded','job.failed',
        'tutor.queued','tutor.running','tutor.tool_completed','tutor.succeeded',
        'tutor.failed','tutor.cancelled','tutor.blocked_unknown','tutor.result_available',
        'learning.plan_drafted','learning.plan_confirmed','assessment.queued',
        'assessment.completed','learning.lesson_completed','knowledge.created',
        'knowledge.revised','knowledge.admitted','knowledge.revoked',
        'learning.review_scheduled','learning.review_recorded','learning.review_status_changed',
        'learning.dynamic_plan_drafted','learning.dynamic_plan_confirmed',
        'learning.lesson_document_created','item_bank.updated','assessment.choice_recorded',
        'assessment.remediation_updated','assessment.gate_updated','learning.node_completed',
        'assessment.transfer_updated')
);
