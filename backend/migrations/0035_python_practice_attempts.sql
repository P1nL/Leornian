ALTER TABLE assessment.python_attempts
    ADD COLUMN policy_version text NOT NULL DEFAULT 'python-io-attempt.v1',
    ADD COLUMN attempt_number integer NOT NULL DEFAULT 1,
    ADD COLUMN retry_requested boolean NOT NULL DEFAULT false,
    ADD COLUMN previous_attempt_id uuid UNIQUE REFERENCES assessment.python_attempts(id);
ALTER TABLE assessment.python_attempts
    DROP CONSTRAINT python_attempts_pack_id_slot_purpose_key;
ALTER TABLE assessment.python_attempts
    ADD CONSTRAINT python_attempt_sequence UNIQUE(pack_id,slot,purpose,attempt_number),
    ADD CONSTRAINT python_attempt_policy CHECK (
        (policy_version='python-io-attempt.v1' AND attempt_number=1
            AND previous_attempt_id IS NULL AND NOT retry_requested)
        OR (policy_version='python-practice.v2' AND purpose='training'
            AND gate_id IS NULL AND transfer_id IS NULL AND attempt_number>=1
            AND ((attempt_number=1 AND previous_attempt_id IS NULL AND NOT retry_requested)
                OR (attempt_number>1 AND previous_attempt_id IS NOT NULL)))
    );

-- Preserve legacy exposure identities; new practice receipts append separate facts.
ALTER TABLE item_bank.exposure_facts
    ADD COLUMN receipt_key text NOT NULL DEFAULT '';
ALTER TABLE item_bank.exposure_facts DROP CONSTRAINT exposure_facts_pkey;
ALTER TABLE item_bank.exposure_facts
    ADD PRIMARY KEY(actor_id,pack_id,slot,kind,receipt_key);
