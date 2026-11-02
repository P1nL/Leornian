ALTER TABLE item_bank.packs
    ADD COLUMN gate_feedback_id uuid REFERENCES assessment.concept_gates(id),
    ADD COLUMN revision_feedback jsonb,
    ADD CONSTRAINT gate_revision_feedback_pair CHECK (
        (gate_feedback_id IS NULL) = (revision_feedback IS NULL)
    );
