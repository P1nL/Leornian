ALTER TABLE tutor.learning_presentations
    ADD COLUMN hint_bindings jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE assessment.practice_hints (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES identity.learners(id),
    pack_id uuid NOT NULL REFERENCES item_bank.packs(id),
    pack_revision integer NOT NULL CHECK (pack_revision > 0),
    slot text NOT NULL CHECK (slot IN ('practice_1', 'practice_2')),
    public_identity text NOT NULL CHECK (public_identity ~ '^[a-f0-9]{64}$'),
    hint_identity text NOT NULL CHECK (hint_identity ~ '^[a-f0-9]{64}$'),
    profile_version text NOT NULL DEFAULT 'practice-hints.v1'
        CHECK (profile_version = 'practice-hints.v1'),
    assistance_kind text NOT NULL DEFAULT 'hint' CHECK (assistance_kind = 'hint'),
    level smallint NOT NULL CHECK (level BETWEEN 1 AND 3),
    content jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id, pack_id, slot, level)
);
