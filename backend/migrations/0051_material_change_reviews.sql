CREATE TABLE knowledge.material_change_reviews (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    check_id uuid NOT NULL UNIQUE REFERENCES knowledge.material_change_checks(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued','processing','waiting_config','waiting_dependency',
                   'blocked_unknown','reviewed','cancelled')
    ),
    operation_id uuid UNIQUE,
    result jsonb,
    error_code text,
    lease_token uuid,
    lease_until timestamptz,
    published_at timestamptz,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX material_change_reviews_due
    ON knowledge.material_change_reviews(next_run_at,id)
    WHERE status IN ('queued','processing','waiting_config','blocked_unknown');
