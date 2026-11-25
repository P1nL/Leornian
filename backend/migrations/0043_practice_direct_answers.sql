CREATE TABLE assessment.practice_assistance (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    pack_revision integer NOT NULL CHECK (pack_revision > 0),
    slot text NOT NULL CHECK (slot IN ('practice_1', 'practice_2')),
    public_identity text NOT NULL CHECK (public_identity ~ '^[a-f0-9]{64}$'),
    profile_version text NOT NULL DEFAULT 'practice-direct-answer.v1'
        CHECK (profile_version = 'practice-direct-answer.v1'),
    assistance_kind text NOT NULL DEFAULT 'direct_answer' CHECK (assistance_kind = 'direct_answer'),
    content jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, pack_id, slot)
);
