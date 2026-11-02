-- Extend the existing successor/supply chain with explicit foreign-keyed code origins.
-- Old concept checks keep their original policy, receipts and exposure history.
ALTER TABLE assessment.transfer_checks
    ALTER COLUMN remediation_id DROP NOT NULL,
    ADD COLUMN python_remediation_id uuid REFERENCES assessment.python_attempts(id),
    ADD COLUMN kind text NOT NULL DEFAULT 'choice' CHECK(kind IN ('choice','python_io')),
    ADD COLUMN python_result_id uuid UNIQUE REFERENCES assessment.python_attempts(id),
    ADD CONSTRAINT transfer_origin_kind CHECK(
        (kind='choice' AND remediation_id IS NOT NULL AND python_remediation_id IS NULL) OR
        (kind='python_io' AND remediation_id IS NULL AND python_remediation_id IS NOT NULL)),
    ADD CONSTRAINT transfer_result_kind CHECK(
        (kind='choice' AND python_result_id IS NULL) OR
        (kind='python_io' AND result_id IS NULL AND selected_key IS NULL));
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_checks_policy_version_check;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_checks_policy_version_check CHECK(
    (kind='choice' AND policy_version IN ('concept-transfer.v1','concept-transfer.v2')) OR
    (kind='python_io' AND policy_version='python-io-transfer.v1'));
ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_checks_status_check;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_checks_status_check CHECK(
    status IN ('preparing','ready','opened','submitted','passed','not_passed',
        'error','blocked','cancelled'));
CREATE UNIQUE INDEX one_current_python_transfer ON assessment.transfer_checks(python_remediation_id)
    WHERE status IN ('preparing','ready','opened','submitted','passed','not_passed','error')
        OR opened_at IS NOT NULL;

ALTER TABLE assessment.python_attempts
    ADD COLUMN transfer_id uuid REFERENCES assessment.transfer_checks(id);
ALTER TABLE assessment.python_attempts DROP CONSTRAINT python_attempts_purpose_check;
ALTER TABLE assessment.python_attempts ADD CONSTRAINT python_attempts_purpose_check CHECK(
    purpose IN ('qualification','training','gate','transfer'));
ALTER TABLE assessment.python_attempts ADD CONSTRAINT python_transfer_reference CHECK(
    (purpose='transfer') = (transfer_id IS NOT NULL));

ALTER TABLE item_bank.supply_demands
    ALTER COLUMN remediation_id DROP NOT NULL,
    ADD COLUMN python_remediation_id uuid REFERENCES assessment.python_attempts(id),
    ADD COLUMN kind text NOT NULL DEFAULT 'choice' CHECK(kind IN ('choice','python_io')),
    ADD CONSTRAINT supply_origin_kind CHECK(
        (kind='choice' AND remediation_id IS NOT NULL AND python_remediation_id IS NULL) OR
        (kind='python_io' AND remediation_id IS NULL AND python_remediation_id IS NOT NULL)),
    ADD CONSTRAINT one_python_supply_per_need UNIQUE(actor_id,python_remediation_id);
