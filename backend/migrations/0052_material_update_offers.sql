CREATE TABLE knowledge.material_update_preparations (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    check_id uuid NOT NULL UNIQUE REFERENCES knowledge.material_change_checks(id),
    review_id uuid NOT NULL REFERENCES knowledge.material_change_reviews(id),
    session_digest text NOT NULL REFERENCES identity.sessions(token_digest),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued','processing','waiting_config','waiting_dependency','blocked_unknown',
        'ready','cancelled'
    )),
    error_code text,
    demand_id uuid REFERENCES knowledge.material_demands(id),
    job_id uuid REFERENCES knowledge.material_jobs(id),
    search_id uuid REFERENCES knowledge.material_searches(id),
    offer_id uuid,
    lease_token uuid,
    lease_until timestamptz,
    published_at timestamptz,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX material_update_preparations_due
    ON knowledge.material_update_preparations(next_run_at,id)
    WHERE status NOT IN ('ready','cancelled');

CREATE TABLE knowledge.material_update_offers (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    preparation_id uuid NOT NULL UNIQUE REFERENCES knowledge.material_update_preparations(id),
    check_id uuid NOT NULL REFERENCES knowledge.material_change_checks(id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision = 1),
    binding_id uuid NOT NULL REFERENCES learning.material_bindings(id),
    binding_revision integer NOT NULL CHECK (binding_revision > 0),
    candidate_selection_id uuid NOT NULL REFERENCES knowledge.material_selections(id),
    candidate_refs jsonb NOT NULL,
    successor_refs jsonb NOT NULL,
    substantive_identity text NOT NULL,
    impact jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,binding_id,binding_revision,substantive_identity)
);
ALTER TABLE knowledge.material_update_preparations ADD FOREIGN KEY (offer_id)
    REFERENCES knowledge.material_update_offers(id);
CREATE TABLE knowledge.material_update_offer_commands (
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    offer_id uuid NOT NULL REFERENCES knowledge.material_update_offers(id),
    PRIMARY KEY (actor_id,command_key)
);

CREATE TABLE delivery.notifications (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    offer_id uuid NOT NULL UNIQUE REFERENCES knowledge.material_update_offers(id),
    kind text NOT NULL CHECK (kind = 'material_update'),
    payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'unread' CHECK (
        state IN ('unread','read','deferred','kept_current','accepted')
    ),
    read_at timestamptz,
    deferred_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_actor_created
    ON delivery.notifications(actor_id,created_at,id);

CREATE TABLE learning.material_update_decisions (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    offer_id uuid NOT NULL REFERENCES knowledge.material_update_offers(id),
    command_key text NOT NULL,
    request jsonb NOT NULL,
    decision text NOT NULL CHECK (
        decision IN ('accept_update','decide_later','keep_current_for_track')
    ),
    binding_id uuid NOT NULL REFERENCES learning.material_bindings(id),
    binding_revision integer NOT NULL,
    successor_binding_id uuid,
    successor_binding_revision integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,command_key),
    FOREIGN KEY (successor_binding_id,successor_binding_revision)
        REFERENCES learning.material_binding_revisions(binding_id,revision),
    CHECK ((successor_binding_id IS NULL) = (successor_binding_revision IS NULL)),
    CHECK ((decision = 'accept_update') = (successor_binding_id IS NOT NULL))
);
CREATE UNIQUE INDEX material_update_final_decision
    ON learning.material_update_decisions(actor_id,offer_id)
    WHERE decision IN ('accept_update','keep_current_for_track');
CREATE UNIQUE INDEX material_update_single_successor
    ON learning.material_update_decisions(actor_id,binding_id,binding_revision)
    WHERE decision = 'accept_update';
CREATE TABLE learning.material_update_migrations (
    decision_id uuid PRIMARY KEY REFERENCES learning.material_update_decisions(id),
    state text NOT NULL CHECK (state = 'requires_reprepare'),
    dependencies jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE delivery.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE delivery.events ADD CHECK (event_type IN (
    'job.queued','goal.created','job.succeeded','job.failed',
    'tutor.queued','tutor.running','tutor.tool_completed','tutor.succeeded','tutor.failed',
    'tutor.cancelled','tutor.blocked_unknown','tutor.result_available',
    'learning.plan_drafted','learning.plan_confirmed','assessment.queued','assessment.completed',
    'learning.lesson_completed','knowledge.created','knowledge.revised','knowledge.admitted',
    'knowledge.revoked','knowledge.material_permission_changed',
    'learning.review_scheduled','learning.review_recorded','learning.review_status_changed',
    'learning.dynamic_plan_drafted','learning.dynamic_plan_confirmed','learning.lesson_document_created',
    'item_bank.updated','assessment.choice_recorded','assessment.response_recorded',
    'assessment.remediation_updated','assessment.gate_updated','learning.node_completed',
    'assessment.transfer_updated','tutor.artifact_updated','tutor.learning_artifact_updated',
    'tutor.teaching_session_updated','tutor.teaching_intent_updated',
    'knowledge.material_update_offered','learning.material_update_decided',
    'delivery.notification_updated'
));
