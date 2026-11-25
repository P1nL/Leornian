ALTER TABLE tutor.turns ADD COLUMN pacing jsonb;
CREATE INDEX teaching_node_turn_order ON tutor.turns
    (conversation_id, (context_focus->>'node_key'), created_at DESC, id DESC)
    WHERE purpose='teaching' AND teaching_branch_id IS NULL;

ALTER TABLE tutor.teaching_intents DROP CONSTRAINT teaching_intents_trigger_kind_check;
ALTER TABLE tutor.teaching_intents ADD CONSTRAINT teaching_intents_trigger_kind_check
    CHECK(trigger_kind IN ('artifact_action','expected_result','interaction_event','review_due','node_window'));
ALTER TABLE tutor.teaching_intents DROP CONSTRAINT teaching_intents_source;
ALTER TABLE tutor.teaching_intents ADD CONSTRAINT teaching_intents_source CHECK (
    (trigger_kind='review_due' AND review_activity_id IS NOT NULL
        AND artifact_id IS NULL AND source_run_id IS NULL AND session_digest IS NOT NULL)
    OR (trigger_kind='node_window' AND review_activity_id IS NULL
        AND artifact_id IS NULL AND source_run_id IS NULL)
    OR (trigger_kind NOT IN ('review_due','node_window') AND review_activity_id IS NULL
        AND artifact_id IS NOT NULL AND source_run_id IS NOT NULL)
);
CREATE UNIQUE INDEX teaching_node_window_once ON tutor.teaching_intents
    (conversation_id, generation, trigger_ref) WHERE trigger_kind='node_window';
