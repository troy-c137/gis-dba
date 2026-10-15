-- Additive migration: old clients continue to work without supplying this field.
ALTER TABLE tracking.assets ADD COLUMN description text;
COMMENT ON COLUMN tracking.assets.description IS 'Optional synthetic asset description';
