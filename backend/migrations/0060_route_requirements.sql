CREATE TABLE tutor.route_requirements (
    conversation_id uuid PRIMARY KEY REFERENCES tutor.conversations(id),
    revision integer NOT NULL CHECK (revision > 0),
    learner_stated jsonb NOT NULL DEFAULT '{}',
    last_turn_id uuid NOT NULL REFERENCES tutor.turns(id),
    updated_at timestamptz NOT NULL DEFAULT now()
);
