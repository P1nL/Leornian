ALTER TABLE tutor.learning_presentations
    ADD COLUMN review_bindings jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(review_bindings) = 'array');
