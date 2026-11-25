ALTER TABLE item_bank.packs ADD COLUMN response_formats jsonb;
ALTER TABLE item_bank.packs ADD CONSTRAINT packs_response_formats_check
    CHECK (response_formats IS NULL OR (
        kind='response' AND jsonb_typeof(response_formats)='object'
    ));

ALTER TABLE item_bank.supply_tasks ADD COLUMN origin_run_id uuid REFERENCES runtime.runs(id);
ALTER TABLE item_bank.supply_tasks ADD COLUMN model_configuration_scope text
    CHECK (model_configuration_scope IN ('user','legacy_development'));
