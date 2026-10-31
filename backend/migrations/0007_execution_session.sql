-- Historical receipts remain intact. Old queued work with no originating session
-- cannot gain a new execution authorization merely from this schema change.
ALTER TABLE execution.jobs ADD COLUMN session_digest text;
