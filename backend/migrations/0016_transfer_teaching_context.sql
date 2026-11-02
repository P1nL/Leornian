ALTER TABLE assessment.transfer_checks DROP CONSTRAINT transfer_checks_policy_version_check;
ALTER TABLE assessment.transfer_checks ADD CONSTRAINT transfer_checks_policy_version_check CHECK (
    policy_version IN ('concept-transfer.v1','concept-transfer.v2'));
ALTER TABLE assessment.transfer_checks ALTER COLUMN policy_version SET DEFAULT 'concept-transfer.v2';
