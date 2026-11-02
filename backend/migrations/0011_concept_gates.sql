ALTER TABLE item_bank.exposures DROP CONSTRAINT exposures_slot_check;
ALTER TABLE item_bank.exposures ADD CONSTRAINT exposures_slot_check CHECK (
    slot IN ('practice_1', 'practice_2', 'assessment_1', 'assessment_2', 'remediation_1')
);
CREATE TABLE item_bank.exposure_heads (
    actor_id uuid PRIMARY KEY REFERENCES identity.learners(id),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
CREATE TABLE item_bank.exposure_facts (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('question', 'feedback')),
    public_content jsonb NOT NULL,
    exposed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id, pack_id, slot, kind)
);
-- Reconstruct actual prior delivery. Never reset an existing learner to an empty ledger.
INSERT INTO item_bank.exposure_facts(actor_id, pack_id, slot, kind, public_content, exposed_at)
SELECT p.actor_id, e.pack_id, e.slot, 'question',
       jsonb_build_object('question', q.item - 'correct_key' - 'explanation'), e.first_exposed_at
FROM item_bank.exposures e JOIN item_bank.packs p ON p.id=e.pack_id
CROSS JOIN LATERAL jsonb_array_elements(p.document->'items') q(item)
WHERE q.item->>'slot'=e.slot;
INSERT INTO item_bank.exposure_facts(actor_id, pack_id, slot, kind, public_content, exposed_at)
SELECT a.actor_id, a.pack_id, a.slot, 'feedback',
       jsonb_build_object('question', q.item - 'correct_key' - 'explanation',
           'feedback', jsonb_build_object('selected_key', a.selected_key,
               'correct', a.correct, 'explanation', a.explanation)), a.created_at
FROM assessment.choice_results a JOIN item_bank.packs p ON p.id=a.pack_id
CROSS JOIN LATERAL jsonb_array_elements(p.document->'items') q(item)
WHERE q.item->>'slot'=a.slot;
INSERT INTO item_bank.exposure_heads(actor_id, revision)
SELECT actor_id, count(*) FROM item_bank.exposure_facts GROUP BY actor_id;

CREATE TABLE assessment.remediations (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL UNIQUE REFERENCES item_bank.packs(id),
    parent_result_id uuid NOT NULL UNIQUE REFERENCES assessment.choice_results(id),
    status text NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'passed', 'not_passed')),
    transfer_required boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE assessment.remediation_triggers (
    result_id uuid PRIMARY KEY REFERENCES assessment.choice_results(id),
    remediation_id uuid NOT NULL REFERENCES assessment.remediations(id)
);
INSERT INTO assessment.remediations(id, actor_id, pack_id, parent_result_id)
SELECT gen_random_uuid(), actor_id, pack_id, id FROM (
    SELECT DISTINCT ON (pack_id) id,actor_id,pack_id
    FROM assessment.choice_results WHERE NOT correct AND slot IN ('practice_1','practice_2')
    ORDER BY pack_id,created_at,id
) original_errors;
INSERT INTO assessment.remediation_triggers(result_id,remediation_id)
SELECT a.id,r.id FROM assessment.choice_results a
JOIN assessment.remediations r ON r.pack_id=a.pack_id
WHERE NOT a.correct AND a.slot IN ('practice_1','practice_2');
CREATE TABLE assessment.concept_gates (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    plan_id uuid NOT NULL,
    plan_revision integer NOT NULL,
    node_key text NOT NULL,
    lesson_id uuid NOT NULL REFERENCES learning.lesson_documents(id),
    idempotency_key text NOT NULL,
    policy_version text NOT NULL DEFAULT 'concept-gate.v1' CHECK (policy_version='concept-gate.v1'),
    relation_run_id uuid UNIQUE REFERENCES runtime.runs(id),
    exposure_revision bigint NOT NULL,
    exposures jsonb NOT NULL,
    context_data jsonb NOT NULL,
    comparisons jsonb NOT NULL,
    relation_report jsonb,
    status text NOT NULL DEFAULT 'preparing' CHECK (status IN
        ('preparing', 'ready', 'in_progress', 'passed', 'not_passed', 'blocked', 'cancelled')),
    error_code text,
    started_exposure_revision bigint,
    submit_key text,
    answers jsonb,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    FOREIGN KEY (plan_id, plan_revision) REFERENCES learning.plan_revisions(plan_id, revision),
    UNIQUE (actor_id, idempotency_key)
);
CREATE UNIQUE INDEX one_open_concept_gate_per_actor ON assessment.concept_gates(actor_id)
    WHERE status IN ('preparing', 'ready', 'in_progress');
CREATE UNIQUE INDEX one_started_concept_gate_per_pack ON assessment.concept_gates(pack_id)
    WHERE started_at IS NOT NULL;
CREATE TABLE learning.concept_evidence (
    gate_id uuid PRIMARY KEY REFERENCES assessment.concept_gates(id),
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    plan_id uuid NOT NULL,
    plan_revision integer NOT NULL,
    node_key text NOT NULL,
    policy_version text NOT NULL CHECK (policy_version='concept-gate.v1'),
    passed_items integer NOT NULL CHECK (passed_items=2),
    total_items integer NOT NULL CHECK (total_items=2),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES learning.plan_revisions(plan_id, revision)
);
CREATE TABLE learning.node_progress (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    plan_id uuid NOT NULL,
    plan_revision integer NOT NULL,
    node_key text NOT NULL,
    evidence_gate_id uuid NOT NULL REFERENCES learning.concept_evidence(gate_id),
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id, plan_id, plan_revision, node_key),
    FOREIGN KEY (plan_id, plan_revision) REFERENCES learning.plan_revisions(plan_id, revision)
);
ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CONSTRAINT runs_policy_version_check CHECK (
    policy_version IN ('tutor.v1', 'planner.v1', 'lesson.v1',
        'item_author.v1', 'item_blind.v1', 'item_review.v1', 'gate_relation.v1')
);
ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CONSTRAINT events_event_type_check CHECK (
    event_type IN ('job.queued', 'goal.created', 'job.succeeded', 'job.failed',
        'tutor.queued', 'tutor.running', 'tutor.tool_completed', 'tutor.succeeded',
        'tutor.failed', 'tutor.cancelled', 'tutor.blocked_unknown', 'tutor.result_available',
        'learning.plan_drafted', 'learning.plan_confirmed', 'assessment.queued',
        'assessment.completed', 'learning.lesson_completed',
        'knowledge.created', 'knowledge.revised', 'knowledge.admitted', 'knowledge.revoked',
        'learning.review_scheduled', 'learning.review_recorded', 'learning.review_status_changed',
        'learning.dynamic_plan_drafted', 'learning.dynamic_plan_confirmed',
        'learning.lesson_document_created', 'item_bank.updated', 'assessment.choice_recorded',
        'assessment.remediation_updated', 'assessment.gate_updated', 'learning.node_completed')
);
