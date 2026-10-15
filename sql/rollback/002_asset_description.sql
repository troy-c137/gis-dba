-- Destructive: export descriptions first. Run only after application compatibility review.
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE tracking.assets DROP COLUMN description;
DELETE FROM public.schema_migrations WHERE version = '002_asset_description.sql';
COMMIT;
