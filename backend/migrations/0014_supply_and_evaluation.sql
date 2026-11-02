CREATE TABLE item_bank.supply_demands (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    remediation_id uuid NOT NULL REFERENCES assessment.remediations(id),
    source_pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    plan_revision integer NOT NULL,
    idempotency_key text NOT NULL,
    instruction text NOT NULL,
    allowed_difficulties jsonb NOT NULL,
    context_data jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_id,idempotency_key),
    UNIQUE(actor_id,remediation_id)
);
ALTER TABLE item_bank.packs
    ADD COLUMN supply_demand_id uuid REFERENCES item_bank.supply_demands(id),
    ADD COLUMN transfer_feedback_id uuid REFERENCES assessment.transfer_checks(id),
    ADD COLUMN transfer_feedback jsonb,
    ADD CONSTRAINT pack_transfer_feedback_pair CHECK (
        (transfer_feedback_id IS NULL) = (transfer_feedback IS NULL)),
    ADD CONSTRAINT one_revision_feedback CHECK (
        gate_feedback_id IS NULL OR transfer_feedback_id IS NULL);

CREATE TABLE tutor.evaluations (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    source_kind text NOT NULL CHECK(source_kind IN ('choice','transfer')),
    source_id uuid NOT NULL,
    context_data jsonb NOT NULL,
    run_id uuid UNIQUE REFERENCES runtime.runs(id),
    document jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_id,source_kind,source_id)
);
ALTER TABLE tutor.turns DROP CONSTRAINT turns_purpose_check;
ALTER TABLE tutor.turns ADD CONSTRAINT turns_purpose_check CHECK (
    purpose IN ('teaching','planning','lesson','item_supply','evaluation'));
ALTER TABLE runtime.runs DROP CONSTRAINT runs_policy_version_check;
ALTER TABLE runtime.runs ADD CONSTRAINT runs_policy_version_check CHECK (
    policy_version IN ('tutor.v1','planner.v1','lesson.v1','item_author.v1',
        'item_blind.v1','item_review.v1','gate_relation.v1','transfer_relation.v1','evaluation.v1')
);
