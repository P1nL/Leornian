ALTER TABLE item_bank.packs
    ADD COLUMN automatic boolean NOT NULL DEFAULT false,
    ADD COLUMN automation_session_digest text REFERENCES identity.sessions(token_digest),
    ADD COLUMN automation_error text,
    ADD COLUMN automation_checked_at timestamptz NOT NULL DEFAULT now(),
    ADD CONSTRAINT pack_automation_authority CHECK (
        automatic = (automation_session_digest IS NOT NULL)
    );

-- Existing candidates remain manual. Enabling the new policy never replays old failures.
CREATE INDEX packs_pending_automation
    ON item_bank.packs (automation_checked_at, id)
    WHERE automatic AND automation_error IS NULL
        AND status IN ('reviewing', 'changes_required', 'ready', 'failed', 'published');
