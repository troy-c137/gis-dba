-- Geography distance uses meters; longitude is X and latitude is Y.
SELECT equipment_id, ST_Distance(geom::geography,
       ST_SetSRID(ST_MakePoint(-140,-40),4326)::geography) AS meters
FROM tracking.current_assets
WHERE ST_DWithin(geom::geography,ST_SetSRID(ST_MakePoint(-140,-40),4326)::geography,10000)
ORDER BY meters;
-- Boundary points count as inside; overlapping areas may return more than one row per asset.
SELECT equipment_id, area_name FROM tracking.assets_in_areas;
-- History query can use the geography GiST index directly.
EXPLAIN (ANALYZE, BUFFERS)
SELECT message_id FROM tracking.locations
WHERE ST_DWithin(position,ST_SetSRID(ST_MakePoint(-140,-40),4326)::geography,1000);
