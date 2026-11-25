ALTER TABLE item_bank.packs
    ADD COLUMN material_context jsonb;

ALTER TABLE item_bank.packs
    ADD CONSTRAINT chk_item_material_context CHECK (
        material_context IS NULL OR (
            jsonb_typeof(material_context) = 'object'
            AND material_context->>'contract' = 'item-materials.v1'
            AND jsonb_typeof(material_context->'origin_citations') = 'array'
            AND jsonb_typeof(material_context->'author_citations') = 'array'
            AND jsonb_typeof(material_context->'review_citations') = 'array'
        ) IS TRUE
    );
