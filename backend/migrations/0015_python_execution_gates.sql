ALTER TABLE item_bank.packs ADD COLUMN kind text NOT NULL DEFAULT 'choice'
    CHECK(kind IN ('choice','python_io'));
ALTER TABLE item_bank.packs DROP CONSTRAINT packs_status_check;
ALTER TABLE item_bank.packs ADD CONSTRAINT packs_status_check CHECK(
    status IN ('authoring','blind_solving','qualifying','reviewing','changes_required',
        'ready','published','failed','cancelled'));

ALTER TABLE assessment.concept_gates DROP CONSTRAINT concept_gates_policy_version_check;
ALTER TABLE assessment.concept_gates ADD CONSTRAINT concept_gates_policy_version_check CHECK(
    policy_version IN ('concept-gate.v1','python-io-gate.v1'));
ALTER TABLE assessment.concept_gates DROP CONSTRAINT concept_gates_status_check;
ALTER TABLE assessment.concept_gates ADD CONSTRAINT concept_gates_status_check CHECK(
    status IN ('preparing','ready','in_progress','submitted','passed','not_passed','blocked','cancelled'));
ALTER TABLE assessment.concept_gates ADD COLUMN submission_key text;
DROP INDEX assessment.one_open_concept_gate_per_actor;
CREATE UNIQUE INDEX one_open_concept_gate_per_actor ON assessment.concept_gates(actor_id)
    WHERE status IN ('preparing','ready','in_progress','submitted');

CREATE TABLE assessment.python_attempts(
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL CHECK(slot IN
        ('practice_1','practice_2','assessment_1','assessment_2','remediation_1')),
    purpose text NOT NULL CHECK(purpose IN ('qualification','training','gate')),
    gate_id uuid REFERENCES assessment.concept_gates(id),
    idempotency_key text NOT NULL,
    code text NOT NULL,
    test_cases jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','passed','not_passed','error')),
    passed_cases integer NOT NULL DEFAULT 0 CHECK(passed_cases BETWEEN 0 AND 3),
    feedback text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE(actor_id,idempotency_key),
    UNIQUE(pack_id,slot,purpose),
    CHECK ((purpose='gate') = (gate_id IS NOT NULL))
);
CREATE TABLE item_bank.python_qualifications(
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    slot text NOT NULL,
    attempt_id uuid NOT NULL UNIQUE REFERENCES assessment.python_attempts(id),
    outcome text CHECK(outcome IN ('passed','not_passed','error')),
    PRIMARY KEY(pack_id,slot)
);
ALTER TABLE execution.jobs ALTER COLUMN input_ref DROP NOT NULL;
ALTER TABLE execution.jobs ADD COLUMN python_input_ref uuid UNIQUE
    REFERENCES assessment.python_attempts(id);
ALTER TABLE execution.jobs ADD CONSTRAINT one_execution_input CHECK(
    num_nonnulls(input_ref,python_input_ref)=1);

CREATE TABLE learning.execution_evidence(
    gate_id uuid PRIMARY KEY REFERENCES assessment.concept_gates(id),
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    plan_id uuid NOT NULL,
    plan_revision integer NOT NULL,
    node_key text NOT NULL,
    policy_version text NOT NULL CHECK(policy_version='python-io-gate.v1'),
    completed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_id,plan_id,plan_revision,node_key),
    FOREIGN KEY(plan_id,plan_revision) REFERENCES learning.plan_revisions(plan_id,revision)
);
ALTER TABLE tutor.turns DROP CONSTRAINT turn_plan_intent;
ALTER TABLE tutor.turns ADD CONSTRAINT turn_plan_intent CHECK (
    (purpose IN ('teaching','item_supply','evaluation') AND plan_base_revision IS NULL
        AND lesson_request_id IS NULL) OR
    (purpose='planning' AND plan_base_revision IS NOT NULL AND plan_base_revision>=0
        AND lesson_request_id IS NULL) OR
    (purpose='lesson' AND plan_base_revision IS NULL AND lesson_request_id IS NOT NULL));
ALTER TABLE tutor.evaluations DROP CONSTRAINT evaluations_source_kind_check;
ALTER TABLE tutor.evaluations ADD CONSTRAINT evaluations_source_kind_check CHECK (
    source_kind IN ('choice','transfer','python'));
