ALTER TABLE tutor.turns ADD COLUMN learning_interaction jsonb;
ALTER TABLE tutor.turns ADD CHECK (
    learning_interaction IS NULL OR (
        jsonb_typeof(learning_interaction) = 'object'
        AND learning_interaction->>'type' IN ('none', 'composer', 'artifact')
    )
);
ALTER TABLE tutor.learning_turn_candidates ADD COLUMN selection_origin text
    NOT NULL DEFAULT 'client' CHECK (selection_origin IN ('client', 'model'));
