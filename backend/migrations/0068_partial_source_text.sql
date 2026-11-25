ALTER TABLE knowledge.document_versions
    ADD COLUMN unresolved_regions jsonb NOT NULL DEFAULT '[]';
